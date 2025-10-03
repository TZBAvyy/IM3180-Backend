import os
import re
import json
import concurrent.futures
from typing import Dict, Optional, List

import requests
from fastapi import APIRouter, HTTPException
from google import genai

from app.models.gemini_models import PlanItinIn, PlanItinOut
from app.models.error_models import HTTPError

# --- API Key Rotation (Gemini) ---
API_KEYS = [
    os.getenv("GEMINI_API_KEY1"),
    os.getenv("GEMINI_API_KEY2"),
    os.getenv("GEMINI_API_KEY3"),
]
API_KEYS = [k for k in API_KEYS if k]
if not API_KEYS:
    raise RuntimeError("No Gemini API keys found in .env")

_current_key_index = -1

def get_next_client():
    global _current_key_index
    _current_key_index = (_current_key_index + 1) % len(API_KEYS)
    api_key = API_KEYS[_current_key_index]
    print(f"[Gemini] Using API key index: {_current_key_index}")
    return genai.Client(api_key=api_key)


# --- Unsplash API (Free Photos) ---
UNSPLASH_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
if not UNSPLASH_KEY:
    print(" Warning: UNSPLASH_ACCESS_KEY not set. Photos will not be resolved.")

def resolve_place_photo(name: str, address: Optional[str] = None) -> Optional[str]:
    """
    Look up a place via Unsplash API and return a photo URL.
    """
    if not UNSPLASH_KEY:
        return None
    try:
        query = f"{name} Singapore"
        if address and "not available" not in address.lower():
            query = f"{name}, {address}, Singapore"

        url = "https://api.unsplash.com/search/photos"
        resp = requests.get(
            url,
            params={
                "query": query,
                "per_page": 1,
                "orientation": "landscape",
                "client_id": UNSPLASH_KEY,
            },
            timeout=5,
        )
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        return results[0]["urls"]["regular"]  # Medium-quality image
    except Exception as e:
        print(f"[Unsplash API] Failed to fetch photo for {name}: {e}")
        return None


# --- FastAPI Router ---
router = APIRouter(prefix="/llm", tags=["Gemini LLM"])

@router.get("/")
def test():
    return {"message": "Gemini LLM Endpoint", "success": True}


# ---------------- Itinerary API ----------------
@router.post(
    "/",
    response_model=PlanItinOut,
    responses={
        200: {"model": PlanItinOut, "description": "Successful Response"},
        500: {"model": HTTPError, "description": "LLM Unexpected Output"},
        503: {"model": HTTPError, "description": "LLM Model Overloaded / Unavailable"},
    },
)
def plan_itinerary(request: PlanItinIn):
    """
    Generate itinerary (names + addresses only, no photos).
    """
    try:
        prefs = request.trip_preferences or {}
        print(f"trip_preferences={prefs}")
        result = generate_itinerary(prefs)
        return {"categories": result}
    except HTTPException:
        raise
    except Exception as e:
        return {"categories": {}, "error": f"Unexpected error: {e}"}


@router.post("/photos")
def get_places_photos(places: List[Dict[str, str]]):
    """
    Resolve multiple photo URLs in parallel.
    Input: [{ "name": "...", "address": "..." }]
    Output: { "results": { "Place Name": "url", ... } }
    """

    def worker(p: Dict[str, str]):
        name = p.get("name")
        addr = p.get("address")
        url = resolve_place_photo(name, addr)
        return name, url

    results = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_place = {executor.submit(worker, p): p for p in places}
            for future in concurrent.futures.as_completed(future_to_place):
                try:
                    name, url = future.result()
                    results[name] = url
                except Exception as e:
                    print(f"[Photos API] Failed to fetch for {future_to_place[future]}: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch photo fetch error: {e}")

    return {"results": results}


# --- Core Itinerary Logic ---
def generate_itinerary(
    trip_preferences: Dict[str, int] | None = None,
    max_locations: int = 20,
) -> Dict[str, list]:
    if not isinstance(trip_preferences, dict):
        trip_preferences = {}

    total_weight = sum(trip_preferences.values())
    activities_total = max_locations

    # --- Build category quotas ---
    category_quotas: Dict[str, int] = {}
    if total_weight > 0:
        for cat, weight in trip_preferences.items():
            category_quotas[cat] = round((weight / total_weight) * activities_total)

    # --- Fix rounding drift ---
    diff = activities_total - sum(category_quotas.values())
    if diff != 0 and category_quotas:
        sorted_cats = sorted(
            category_quotas.items(),
            key=lambda kv: trip_preferences.get(kv[0], 1),
            reverse=True,
        )
        for i in range(abs(diff)):
            cat = sorted_cats[i % len(sorted_cats)][0]
            category_quotas[cat] += 1 if diff > 0 else -1

    prefs_text = (
        "Visitor preferences not provided; assume balanced mix."
        if total_weight == 0
        else ", ".join(
            f"{cat} ({round(val / total_weight * 100)}%)"
            for cat, val in trip_preferences.items()
            if val > 0
        )
    )
    quota_guidance = "\n".join(f"- {cat}: {count} places" for cat, count in category_quotas.items())
    allowed_categories = [cat for cat, count in category_quotas.items() if count > 0]
    allowed_cats_text = " | ".join(allowed_categories)

    # --- Prompt ---
    prompt = f"""
    You are a Singapore travel planner.
    Generate a list of **max {activities_total} recommended places** in **strict JSON** format.

    Trip details:
    - Visitor preference weights: {prefs_text}
    - Category quotas (must respect these counts exactly):
    {quota_guidance}

    Rules:
    - Use only these categories: {allowed_cats_text}
    - Do not include categories with quota 0
    - Pick **real, specific locations** in Singapore that fit the vibe of each category.
    - Avoid generic tourist clichés unless they directly match preferences.
    - Spread activities across different areas to reduce repetition.
    - Every location MUST include:
      • name
      • real Singapore address
    - Do NOT return "N/A", "Address not available", or empty values.

    Output format:
    {{
      "categories": {{
        "Food Tour": [ ... ],
        "Culture & Attraction": [ ... ],
        "Nightlife & Entertainment": [ ... ],
        "Nature & Outdoor": [ ... ],
        "Shopping & Lifestyle": [ ... ]
      }}
    }}

    Return ONLY valid JSON.
    """

    # --- Call Gemini ---
    try:
        response = call_gemini_once(prompt)
        llm_text = getattr(response, "text", str(response))
        llm_data = safe_parse_llm_output(llm_text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Gemini call failed or invalid JSON: {e}")

    if not isinstance(llm_data, dict) or "categories" not in llm_data:
        raise HTTPException(status_code=500, detail="Could not normalize Gemini output")

    llm_data = llm_data["categories"]

    # --- Post-process activities ---
    valid_categories = set(allowed_categories)
    categories_output = {cat: [] for cat in valid_categories}

    for cat, activities in llm_data.items():
        if cat not in valid_categories:
            continue
        for a in activities:
            try:
                weight = (trip_preferences.get(cat, 0) / total_weight) if total_weight else 0
                score = min(
                    100.0,
                    max(0.0, float(a.get("preference_score", 50)) * (0.5 + weight)),
                )
                name = a.get("name", "Unknown")
                addr = a.get("address", "Address not available")

                categories_output[cat].append(
                    {
                        "name": name,
                        "address": addr,
                        "category": cat,
                        "photo_url": None,        # frontend fetches later
                        "photo_pending": True,
                        "preference_score": score,
                    }
                )
            except Exception as e:
                print(f"Skipping activity in {cat} due to error: {e}")
                continue

    # --- Enforce quotas strictly ---
    for cat, required in category_quotas.items():
        actual = len(categories_output.get(cat, []))
        if actual > required:
            categories_output[cat].sort(key=lambda x: x.get("preference_score", 0))
            categories_output[cat] = categories_output[cat][actual - required :]
        elif actual < required:
            print(f"Category {cat} underfilled: got {actual}, need {required}")

    # --- Strip preference_score before returning ---
    for cat in categories_output:
        for a in categories_output[cat]:
            a.pop("preference_score", None)

    return categories_output


# --- Gemini utilities ---
def call_gemini_once(prompt: str, model: str = "gemini-2.5-flash-lite", timeout: int = 40):
    client = get_next_client()
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            fut = executor.submit(client.models.generate_content, model=model, contents=prompt)
            resp = fut.result(timeout=timeout)
        if hasattr(resp, "text"):
            return resp
        else:
            class R: pass
            r = R()
            r.text = str(resp)
            return r
    except concurrent.futures.TimeoutError:
        raise HTTPException(status_code=503, detail=f"Gemini request timed out after {timeout}s")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Gemini error: {e}")

def safe_parse_llm_output(llm_text: str):
    if not isinstance(llm_text, str):
        llm_text = str(llm_text)
    try:
        return json.loads(llm_text)
    except Exception:
        pass
    # fallback cleaning...
    first_obj_idx = llm_text.find("{")
    first_arr_idx = llm_text.find("[")
    candidates = []
    if first_arr_idx != -1:
        last_arr_idx = llm_text.rfind("]")
        if last_arr_idx != -1 and last_arr_idx > first_arr_idx:
            candidates.append(llm_text[first_arr_idx : last_arr_idx + 1])
    if first_obj_idx != -1:
        last_obj_idx = llm_text.rfind("}")
        if last_obj_idx != -1 and last_obj_idx > first_obj_idx:
            candidates.append(llm_text[first_obj_idx : last_obj_idx + 1])
    for candidate in candidates:
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                return json.loads(attempt)
            except Exception:
                continue
    raise ValueError("Could not parse JSON from LLM output")
