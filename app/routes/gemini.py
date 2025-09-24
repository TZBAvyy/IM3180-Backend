import os
import re
import json
import time
import random
import itertools
from math import ceil
import concurrent.futures

import numpy as np
from sklearn.cluster import DBSCAN
from fastapi import APIRouter, HTTPException
from google import genai

from app.models.gemini_models import PlanItinIn, PlanItinOut
from app.models.error_models import HTTPError


# --- API Key Rotation ---
API_KEYS = [
    os.getenv("GEMINI_API_KEY1"),
    os.getenv("GEMINI_API_KEY2"),
    os.getenv("GEMINI_API_KEY3"),
]
API_KEYS = [k for k in API_KEYS if k]  # filter out None
if not API_KEYS:
    raise RuntimeError("No Gemini API keys found in .env")

_current_key_index = -1


def get_next_client():
    """Rotate to the next API key for each new request."""
    global _current_key_index
    _current_key_index = (_current_key_index + 1) % len(API_KEYS)
    api_key = API_KEYS[_current_key_index]
    print(f"[Gemini] Using API key index: {_current_key_index}")
    return genai.Client(api_key=api_key)


# --- FastAPI Router ---
router = APIRouter(prefix="/llm", tags=["Gemini LLM"])


@router.get("/")
def test():
    """Health check endpoint for Gemini route."""
    return {"message": "Gemini LLM Endpoint", "success": True}


@router.post(
    "/",
    responses={
        200: {"model": PlanItinOut, "description": "Successful Response"},
        500: {"model": HTTPError, "description": "LLM Unexpected Output"},
        503: {"model": HTTPError, "description": "LLM Model Overloaded"},
    },
)
def plan_itinerary(request: PlanItinIn):
    try:
        result = generate_itinerary(
            request.user_stay_days,
            request.max_hours_per_day,
            getattr(request, "trip_preferences", None),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


# --- Core Itinerary Logic ---
def generate_itinerary(user_stay_days: int, max_hours_per_day: float, trip_preferences=None):
    if trip_preferences is None:
        trip_preferences = {}

    # --- Build preferences text ---
    prefs_text = ""
    if trip_preferences:
        total = sum(trip_preferences.values())
        if total > 0:
            trip_preferences_prompt = {k: round(v / total * 100) for k, v in trip_preferences.items()}
            prefs_list = [f"{k} ({v}%)" for k, v in trip_preferences_prompt.items()]
            prefs_text = "Visitor preferences: " + ", ".join(prefs_list) + "."

    # --- Build prompt ---
    prompt = f"""
    You are an expert travel planner for Singapore. 
    Your goal is to create the perfect itinerary by strictly following the user's preferences. 
    Do not include unrelated attractions.

    Here is the user request:
    - Trip duration: {user_stay_days} days
    - Daily activity hours: ~{max_hours_per_day}h
    - User preferences: {prefs_text}

    Instructions:
    1. Only include attractions that directly match the given preferences. 
    Example:
    - If the preference is Food, only include hawker centres, local food streets, night markets, restaurants, cafes.
    - If the preference is Nightlife, only include bars, clubs, night markets, rooftop lounges.
    - If the preference is Tourist Attraction, include landmarks, museums, parks, iconic sightseeing spots.
    2. Each attraction must explicitly relate to at least one preference. 
    If no attraction matches, return an empty list for that day.
    3. For each attraction, include:
    - "name" (string, exact place name in Singapore),
    - "latitude" (float),
    - "longitude" (float),
    - "suggested_visit_hours" (string, e.g. "10:00 - 22:00"),
    - "priority" (integer, higher = more important),
    - "preference_score" (float, 0–100; 100 = perfect match, 80–99 = strong match).
    4. Do not add general tourist spots if they do not fit the preference.
    5. Format Output: Return **JSON only**.
    Format: [[{{"name": "...", "latitude": ..., "longitude": ..., "suggested_visit_hours": "...", "priority": ..., "preference_score": ...}}, ...], [...]]
    """

    # --- Call Gemini robustly ---
    try:
        response = call_gemini_with_retry(prompt)
        llm_text = getattr(response, "text", str(response))
        llm_data = safe_parse_llm_output(llm_text)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Gemini call failed: {e}")

    if not llm_data:
        raise HTTPException(status_code=500, detail="Empty itinerary from Gemini")

    # --- Flatten activities ---
    try:
        all_activities = list(itertools.chain.from_iterable(llm_data))
    except Exception:
        raise HTTPException(status_code=500, detail=f"LLM JSON not in expected format. Raw: {llm_data}")

    # --- Extract only {name, preference_score, suggested_visit_hours} ---
    simplified = []
    for a in all_activities:
        if "name" in a and "preference_score" in a and "suggested_visit_hours" in a:
            try:
                simplified.append({
                    "name": a["name"],
                    "preference_score": float(a["preference_score"]),
                    "suggested_visit_hours": str(a["suggested_visit_hours"])
                })
            except Exception:
                continue


    if not simplified:
        raise HTTPException(
            status_code=500,
            detail=f"No valid activities after parsing. Raw Gemini output:\n{json.dumps(llm_data, indent=2)}"
        )

    return {"locations": simplified}




# --- Utilities ---
def safe_parse_llm_output(llm_text):
    """
    Attempt to extract and parse JSON (array or object) from LLM output.
    Tries several fallbacks: direct JSON, first {...} or [...] block, simple trailing-comma fixes.
    Returns Python object or raises ValueError.
    """
    if not isinstance(llm_text, str):
        llm_text = str(llm_text)

    # 1) Try direct parse
    try:
        return json.loads(llm_text)
    except Exception:
        pass

    # 2) Extract first JSON array or object block
    first_obj_idx = llm_text.find('{')
    first_arr_idx = llm_text.find('[')
    candidates = []
    if first_arr_idx != -1:
        last_arr_idx = llm_text.rfind(']')
        if last_arr_idx != -1 and last_arr_idx > first_arr_idx:
            candidates.append(llm_text[first_arr_idx:last_arr_idx + 1])
    if first_obj_idx != -1:
        last_obj_idx = llm_text.rfind('}')
        if last_obj_idx != -1 and last_obj_idx > first_obj_idx:
            candidates.append(llm_text[first_obj_idx:last_obj_idx + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                return json.loads(fixed)
            except Exception:
                continue

    # 3) Last resort: try all blocks
    braces_blocks = re.findall(r'(\{(?:[^{}]|\{[^}]*\})*\})', llm_text, flags=re.DOTALL)
    bracket_blocks = re.findall(r'(\[(?:[^\[\]]|\[[^\]]*\])*\])', llm_text, flags=re.DOTALL)
    all_blocks = sorted(braces_blocks + bracket_blocks, key=len, reverse=True)
    for block in all_blocks:
        try:
            return json.loads(block)
        except Exception:
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", block)
                return json.loads(fixed)
            except Exception:
                continue

    raise ValueError("Could not parse JSON from LLM output")


def call_gemini_with_retry(prompt, max_retries=5, model="gemini-2.5-flash-lite", timeout=50):
    """
    Call Gemini with retries, key rotation, timeouts, and fallback model.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            client = get_next_client()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(client.models.generate_content, model=model, contents=prompt)
                resp = future.result(timeout=timeout)
            if hasattr(resp, "text"):
                return resp
            else:
                class R: pass
                r = R()
                r.text = str(resp)
                return r
        except concurrent.futures.TimeoutError:
            print(f"[Gemini] Timeout ({timeout}s) attempt {attempt+1}")
            last_exc = "timeout"
            continue
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if any(x in msg for x in ["overload", "unavailable", "capacity"]):
                wait = min(2 ** attempt, 5) + random.random()
                print(f"[Gemini] Overloaded. Retrying in {wait:.1f}s...")
                time.sleep(wait)
                continue
            else:
                raise

    # fallback to stable model
    try:
        client = get_next_client()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(client.models.generate_content, model="gemini-2.0-flash", contents=prompt)
            resp = future.result(timeout=timeout)
        if hasattr(resp, "text"):
            return resp
        else:
            class R: pass
            r = R()
            r.text = str(resp)
            return r
    except Exception as e2:
        raise RuntimeError(f"All retries failed ({last_exc}); fallback also failed ({e2})")

def convert_numpy_types(obj):
    """Convert numpy types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_numpy_types(i) for i in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj
