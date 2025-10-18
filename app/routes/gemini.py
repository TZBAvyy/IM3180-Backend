import os
import re
import json
import concurrent.futures
from typing import Dict, Optional, List, Any

import requests
from fastapi import APIRouter, HTTPException
from google import genai

from app.models.gemini_models import PlanItinIn, PlanItinOut
from app.models.error_models import HTTPError

DEFAULT_CATEGORIES: List[str] = [
    "Food Tour",
    "Culture & Attraction",
    "Nightlife & Entertainment",
    "Nature & Outdoor",
    "Shopping & Lifestyle",
]

CATEGORY_KEYWORDS = {
    "Food Tour": [
        "restaurants", "cafes", "hawker centres", "street food", "food courts",
        "local delicacies", "signature dishes", "bakeries", "seafood restaurants",
        "fine dining", "local eateries", "brunch spots", "coffee shops",
        "dessert cafes", "food markets"
    ],

    "Culture & Attraction": [
        "museums", "heritage sites", "temples", "art galleries", "historical landmarks",
        "monuments", "cultural villages", "architecture", "street art", "performance theatres",
        "historic districts", "cathedrals", "exhibitions", "palaces", "observatories"
    ],

    "Nightlife & Entertainment": [
        "bars", "rooftop lounges", "pubs", "nightclubs", "karaoke", "live music venues",
        "cinemas", "arcades", "game cafes", "night markets", "comedy clubs",
        "late-night eateries", "billiard halls", "speakeasies", "entertainment hubs"
    ],

    "Nature & Outdoor": [
        "parks", "gardens", "beaches", "hiking trails", "reserves", "scenic viewpoints",
        "cycling paths", "botanic gardens", "lakes", "outdoor adventure parks",
        "boardwalks", "nature trails", "mountains", "wetlands", "skywalks"
    ],

    "Shopping & Lifestyle": [
        "shopping malls", "fashion boutiques", "local markets", "souvenir shops",
        "luxury stores", "vintage shops", "department stores", "street markets",
        "lifestyle hubs", "tech stores", "design studios", "concept stores",
        "wellness spas", "salons", "home decor stores"
    ]
}

CITY_LANGUAGE_HINTS = {
    "Tokyo": "Japanese",
    "Kyoto": "Japanese",
    "Osaka": "Japanese",
    "Yokohama": "Japanese",
    "Nagoya": "Japanese",
    "Singapore": "English, Mandarin Chinese, Malay, or Tamil",
    "Seoul": "Korean",
    "Busan": "Korean",
    "Jeju": "Korean",
    "Bangkok": "Thai",
    "Chiang Mai": "Thai",
    "Hanoi": "Vietnamese",
    "Ho Chi Minh City": "Vietnamese",
    "Taipei": "Traditional Chinese",
    "Taichung": "Traditional Chinese",
    "Hong Kong": "Traditional Chinese",
    "Shanghai": "Simplified Chinese",
    "Beijing": "Simplified Chinese",
    "Kuala Lumpur": "Malay or English",
    "Penang": "Malay or English",
    "Jakarta": "Indonesian",
    "Bali": "Indonesian",
    "Manila": "Filipino",
    "Cebu": "Filipino",
}

CITY_SYNONYMS = {
    "Penang": ["George Town", "Pulau Pinang", "Penang Island", "Georgetown"],
    "Singapore": ["SG", "Lion City"],
    "Tokyo": ["Toukyou", "東京都"],
    "Kyoto": ["Kyōto", "京都"],
    "Osaka": ["Ōsaka", "大阪"],
    "Seoul": ["서울", "Soul"],
    "Busan": ["부산"],
    "Bangkok": ["Krung Thep", "กรุงเทพมหานคร"],
    "Hanoi": ["Hà Nội"],
    "Ho Chi Minh City": ["Saigon", "Sài Gòn"],
    "Taipei": ["臺北", "台北"],
    "Hong Kong": ["香港"],
    "Shanghai": ["上海"],
    "Beijing": ["北京市", "北京"],
    "Jakarta": ["DKI Jakarta"],
    "Bali": ["Denpasar"],
    "Manila": ["Metro Manila"],
}

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

def resolve_place_photo(
    name: str,
    address: Optional[str] = None,
    city: Optional[str] = None,
) -> Optional[str]:
    """
    Look up a place via Unsplash API and return a photo URL.
    """
    if not UNSPLASH_KEY:
        return None
    if not name:
        return None
    try:
        components: List[str] = [name]
        if address and "not available" not in address.lower():
            components.append(address)
        if city:
            components.append(city)
        query = ", ".join(component for component in components if component)

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
        print(f"cities={request.cities}")
        result = generate_itinerary(prefs, request.cities)
        return {"status": "done", "categories": result}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "categories": {}, "error": f"Unexpected error: {e}"}


@router.post("/photos")
def get_places_photos(places: List[Dict[str, str]]):
    """
    Resolve multiple photo URLs in parallel.
    Input: [{ "name": "...", "address": "...", "city": "..." }]
    Output: { "results": { "Place Name": "url", ... } }
    Note: Unsplash integration is disabled; all URLs are returned as None.
    """

    def worker(p: Dict[str, str]):
        return p.get("name"), None

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
    cities: List[str] | None = None,
    max_locations_per_city: int = 20,
) -> Dict[str, list]:
    if not isinstance(trip_preferences, dict):
        trip_preferences = {}

    city_candidates = cities or []
    cleaned_cities: List[str] = []
    seen_cities_lower = set()
    for city in city_candidates:
        if not isinstance(city, str):
            continue
        normalized = city.strip()
        if not normalized:
            continue
        lower = normalized.lower()
        if lower in seen_cities_lower:
            continue
        seen_cities_lower.add(lower)
        cleaned_cities.append(normalized)
    if not cleaned_cities:
        cleaned_cities = ["Tokyo"]
    allowed_city_lookup: Dict[str, str] = {}
    allowed_city_variants: List[str] = []
    for city in cleaned_cities:
        allowed_city_lookup[city.lower()] = city
        allowed_city_variants.append(city)
        for alias in CITY_SYNONYMS.get(city, []):
            if not isinstance(alias, str):
                continue
            alias_clean = alias.strip()
            if not alias_clean:
                continue
            allowed_city_lookup[alias_clean.lower()] = city
            allowed_city_variants.append(alias_clean)
    # Deduplicate while preserving order
    seen_variants = set()
    deduped_variants: List[str] = []
    for name in allowed_city_variants:
        lower_name = name.lower()
        if lower_name in seen_variants:
            continue
        seen_variants.add(lower_name)
        deduped_variants.append(name)
    allowed_city_variants = deduped_variants

    cities_text = "\n".join(f"- {city}" for city in cleaned_cities)
    cities_inline = " | ".join(cleaned_cities)
    max_locations_per_city = max(1, int(max_locations_per_city))
    activities_total = max_locations_per_city * len(cleaned_cities)
    total_weight = sum(trip_preferences.values())

    # --- Build category quotas ---
    category_quotas: Dict[str, int] = {}
    if total_weight > 0:
        for cat, weight in trip_preferences.items():
            category_quotas[cat] = round((weight / total_weight) * activities_total)

    if not category_quotas:
        base_categories = DEFAULT_CATEGORIES
        base = activities_total // len(base_categories)
        remainder = activities_total % len(base_categories)
        category_quotas = {
            cat: base + (1 if idx < remainder else 0)
            for idx, cat in enumerate(base_categories)
        }
    else:
        diff = activities_total - sum(category_quotas.values())
        if diff != 0:
            sorted_cats = sorted(
                category_quotas.items(),
                key=lambda kv: trip_preferences.get(kv[0], 1),
                reverse=True,
            )
            for i in range(abs(diff)):
                cat = sorted_cats[i % len(sorted_cats)][0]
                category_quotas[cat] += 1 if diff > 0 else -1

    allowed_categories = [cat for cat, count in category_quotas.items() if count > 0]
    if not allowed_categories:
        allowed_categories = DEFAULT_CATEGORIES.copy()

    quota_guidance = "\n".join(f"- {cat}: {category_quotas.get(cat, 0)} places" for cat in allowed_categories)

    prefs_text = (
        "Visitor preferences not provided; assume balanced mix."
        if total_weight == 0
        else ", ".join(
            f"{cat} ({round(val / total_weight * 100)}%)"
            for cat, val in trip_preferences.items()
            if val > 0
        )
    )

    category_city_targets: Dict[str, Dict[str, int]] = {
        city: {cat: 0 for cat in allowed_categories} for city in cleaned_cities
    }
    for cat in allowed_categories:
        total_for_cat = category_quotas.get(cat, 0)
        base_share = total_for_cat // len(cleaned_cities)
        remainder = total_for_cat % len(cleaned_cities)
        for idx, city in enumerate(cleaned_cities):
            category_city_targets[city][cat] = base_share + (1 if idx < remainder else 0)

    city_target_totals = {
        city: sum(category_city_targets[city].values()) for city in cleaned_cities
    }

    category_city_guidance_lines: List[str] = []
    for cat in allowed_categories:
        allocations = ", ".join(
            f"{city}: {category_city_targets[city][cat]} places"
            for city in cleaned_cities
            if category_city_targets[city][cat] > 0
        )
        category_city_guidance_lines.append(f"- {cat}: {allocations}")
    category_city_guidance = "\n".join(category_city_guidance_lines)

    allowed_cats_text = " | ".join(allowed_categories)
    default_city_placeholder = cleaned_cities[0] if cleaned_cities else "Requested City"

    keyword_guidance_lines: List[str] = []
    for cat in allowed_categories:
        hints = CATEGORY_KEYWORDS.get(cat, [])
        if hints:
            keyword_guidance_lines.append(f"- {cat}: {', '.join(hints)}")
    keyword_guidance = (
        "\n".join(keyword_guidance_lines)
        if keyword_guidance_lines
        else "- Use authentic, city-specific search terms for each category."
    )

    language_guidance_lines: List[str] = []
    for city in cleaned_cities:
        hint = CITY_LANGUAGE_HINTS.get(city, "the city's primary local language")
        language_guidance_lines.append(
            f"- {city}: use keywords in {hint} (alongside English transliterations) to surface authentic places."
        )
    language_guidance = "\n".join(language_guidance_lines)

    def build_prompt(extra_guidance: str = "", attempt: int = 1) -> str:
        retry_block = ""
        if extra_guidance:
            guidance_lines = "\n".join(f"    {line}" for line in extra_guidance.strip().splitlines())
            retry_block = f"""
    Retry guidance (attempt #{attempt}):
{guidance_lines}
    You must correct every remaining slot listed above within this attempt."""

        return f"""
    You are a travel planner working only with these cities: {cities_inline}.
    Generate a list of **max {activities_total} recommended places** in **strict JSON** format.

    Trip details:
    - Visitor preference weights: {prefs_text}
    - Category quotas (must respect these counts exactly; do not overfill or underfill):
    {quota_guidance}
    - Requested cities (cover each with relevant, non-duplicated places):
    {cities_text}
    - Total activities required: {activities_total} (no more, no less).
    - Each city must return exactly {max_locations_per_city} places (no more, no less).
    - City totals to fulfill: {", ".join(f"{city} = {city_target_totals[city]}" for city in cleaned_cities)}
    - City/category allocations (each pair must be satisfied exactly):
    {category_city_guidance}
    - Your list must be fresh for each attempt—no duplicate locations across attempts.
{retry_block}
    - Suggested keyword hints per category (use to find distinctive spots):
    {keyword_guidance}
    - Native-language search guidance (apply when researching places):
    {language_guidance}

    Rules:
    - Use only these categories: {allowed_cats_text}
    - Do not include categories with quota 0
    - Return exactly the number of activities per category listed above. Do not add or omit entries.
    - Within each category, split the items across cities according to the city/category allocations above.
    - Pick **real, specific locations** in the listed cities that fit the vibe of each category.
    - When validating locations, rely on both English and the native-language keywords above to ensure they truly belong to the specified city.
    - Keep generating unique, non-duplicate locations until all category and city counts are satisfied.
    - Avoid generic tourist cliches unless they directly match preferences.
    - Spread activities across different areas to reduce repetition.
    - Every location MUST include:
      - name
      - real address
      - city (must exactly match one of: {cities_inline})
    - Do NOT return "N/A", "Address not available", or empty values.

    Output format:
    {{
      "categories": {{
        "Food Tour": [
          {{
            "name": "Example Place",
            "address": "123 Example Rd, {default_city_placeholder}",
            "city": "{default_city_placeholder}"
          }}
        ],
        "Culture & Attraction": [ ... ],
        "Nightlife & Entertainment": [ ... ],
        "Nature & Outdoor": [ ... ],
        "Shopping & Lifestyle": [ ... ]
      }}
    }}

    Return ONLY valid JSON.
    """

    def run_single_attempt(prompt: str, attempt: int) -> tuple[Dict[str, list], Dict[str, int], Dict[str, int], Dict[str, Dict[str, int]]]:
        try:
            print(f"[Gemini] Attempt {attempt}: requesting itinerary for {', '.join(cleaned_cities)}")
            response = call_gemini_once(prompt)
            llm_text = getattr(response, "text", str(response))
            llm_data = safe_parse_llm_output(llm_text)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Gemini call failed or invalid JSON: {e}")

        if not isinstance(llm_data, dict) or "categories" not in llm_data:
            raise HTTPException(status_code=500, detail="Could not normalize Gemini output")

        llm_categories = llm_data["categories"]
        valid_categories = set(allowed_categories)
        categories_output = {cat: [] for cat in valid_categories}
        category_remaining = {cat: category_quotas.get(cat, 0) for cat in allowed_categories}
        city_remaining = city_target_totals.copy()
        category_city_remaining = {
            city: category_city_targets[city].copy() for city in cleaned_cities
        }

        for cat, activities in llm_categories.items():
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
                    raw_city = a.get("city")
                    city_name = None
                    if isinstance(raw_city, str):
                        city_name = allowed_city_lookup.get(raw_city.strip().lower())
                    addr_lower = addr.lower() if isinstance(addr, str) else ""
                    if not city_name and addr_lower:
                        for city_lower, city_proper in allowed_city_lookup.items():
                            if city_lower in addr_lower:
                                city_name = city_proper
                                break
                    if not city_name:
                        city_name = cleaned_cities[0]
                    if city_name not in category_city_remaining:
                        continue
                    if category_remaining.get(cat, 0) <= 0:
                        continue
                    if city_remaining.get(city_name, 0) <= 0:
                        continue
                    if category_city_remaining[city_name].get(cat, 0) <= 0:
                        continue

                    categories_output[cat].append(
                        {
                            "name": name,
                            "address": addr,
                            "city": city_name,
                            "category": cat,
                            "photo_url": None,
                            "photo_pending": False,
                            "preference_score": score,
                            "latitude": None,
                            "longitude": None,
                            "place_id": None,
                        }
                    )
                    category_remaining[cat] -= 1
                    city_remaining[city_name] -= 1
                    category_city_remaining[city_name][cat] -= 1

                    geo = resolve_latlng_from_address(
                        addr,
                        city_name,
                        allowed_city_variants,
                        allowed_city_lookup,
                    )
                    if geo and geo.get("matched_city_ok"):
                        categories_output[cat][-1]["latitude"] = geo["latitude"]
                        categories_output[cat][-1]["longitude"] = geo["longitude"]
                        categories_output[cat][-1]["place_id"] = geo["place_id"]
                        if geo.get("matched_city"):
                            matched_canonical = allowed_city_lookup.get(
                                geo["matched_city"].lower(),
                                categories_output[cat][-1]["city"],
                            )
                            categories_output[cat][-1]["city"] = matched_canonical
                    else:
                        categories_output[cat].pop()
                        category_remaining[cat] += 1
                        city_remaining[city_name] += 1
                        category_city_remaining[city_name][cat] += 1
                        continue

                except Exception as e:
                    print(f"Skipping activity in {cat} due to error: {e}")
                    continue

        for cat, remaining in category_remaining.items():
            if remaining > 0:
                print(f"[Attempt {attempt}] Category {cat} underfilled: missing {remaining}")

        for city, remaining in city_remaining.items():
            if remaining > 0:
                print(f"[Attempt {attempt}] City {city} underfilled: missing {remaining}")

        for city, cats in category_city_remaining.items():
            for cat, remaining in cats.items():
                if remaining > 0:
                    print(f"[Attempt {attempt}] City {city} / Category {cat} underfilled: missing {remaining}")

        for cat in categories_output:
            for a in categories_output[cat]:
                a.pop("preference_score", None)

        return categories_output, category_remaining, city_remaining, category_city_remaining

    max_attempts = 3
    severe_underfill_threshold = 5
    retry_guidance = ""
    best_output: Optional[Dict[str, list]] = None
    last_city_remaining: Optional[Dict[str, int]] = None
    last_category_city_remaining: Optional[Dict[str, Dict[str, int]]] = None

    for attempt in range(1, max_attempts + 1):
        prompt = build_prompt(retry_guidance, attempt)
        output, category_remaining, city_remaining, category_city_remaining = run_single_attempt(prompt, attempt)
        best_output = output
        last_city_remaining = city_remaining
        last_category_city_remaining = category_city_remaining

        severe_deficits = {
            city: remaining for city, remaining in city_remaining.items() if remaining > severe_underfill_threshold
        }
        if not severe_deficits:
            break

        retry_lines = []
        for city, remaining in severe_deficits.items():
            cat_breakdown = [
                f"{cat}: {category_city_remaining[city][cat]}"
                for cat in allowed_categories
                if category_city_remaining[city].get(cat, 0) > 0
            ]
            if cat_breakdown:
                retry_lines.append(f"- {city}: {remaining} slots missing (need {', '.join(cat_breakdown)})")
            else:
                retry_lines.append(f"- {city}: {remaining} slots missing")

        retry_lines.append("- Provide brand new locations that have not appeared in earlier attempts.")
        retry_guidance = "\n".join(retry_lines)

    if best_output is None:
        best_output = {cat: [] for cat in allowed_categories}

    if last_city_remaining:
        still_missing = {city: rem for city, rem in last_city_remaining.items() if rem > 0}
        if still_missing:
            print(f"[Gemini] Final itinerary still missing slots: {still_missing}")
            if last_category_city_remaining:
                for city, cat_map in last_category_city_remaining.items():
                    for cat, rem in cat_map.items():
                        if rem > 0:
                            print(f"[Gemini] Outstanding -> {city} / {cat}: {rem}")

    return best_output


# --- Gemini utilities ---
def call_gemini_once(prompt: str, model: str = "gemini-2.5-flash", timeout: int = 50):
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

def resolve_latlng_from_address(
    address: str,
    city: Optional[str] = None,
    allowed_cities: Optional[List[str]] = None,
    allowed_city_map: Optional[Dict[str, str]] = None,
    timeout: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """
    Resolve an address string into latitude/longitude using Google Geocoding API.
    """
    GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
    if not GOOGLE_API_KEY or not address:
        return None
    query_parts = [address]
    if city:
        query_parts.append(city)
    query = ", ".join(part for part in query_parts if part)
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": GOOGLE_API_KEY},
            timeout=timeout,
        )
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            if allowed_city_map:
                allowed_lookup = {k.lower(): v for k, v in allowed_city_map.items()}
            else:
                allowed_lookup = {c.lower(): c for c in (allowed_cities or [])}
            selected_result = None
            matched_city_name = None
            for result in data["results"]:
                address_components = result.get("address_components", [])
                formatted_address = result.get("formatted_address", "")
                match_name = None
                for component in address_components:
                    for key in ("long_name", "short_name"):
                        name = component.get(key)
                        if not name:
                            continue
                        name_lower = name.lower()
                        if name_lower in allowed_lookup:
                            match_name = allowed_lookup[name_lower]
                            break
                    if match_name:
                        break
                if not match_name and city:
                    target_lower = city.lower()
                    if formatted_address and target_lower in formatted_address.lower():
                        match_name = allowed_lookup.get(target_lower, city)
                if match_name:
                    selected_result = result
                    matched_city_name = match_name
                    break
                if selected_result is None:
                    selected_result = result
            if not selected_result:
                selected_result = data["results"][0]
            loc = selected_result["geometry"]["location"]
            pid = selected_result.get("place_id")
            formatted_address = selected_result.get("formatted_address", "")
            if not matched_city_name and city and formatted_address:
                target_lower = city.lower()
                if target_lower in formatted_address.lower():
                    matched_city_name = city
            if not matched_city_name and allowed_lookup:
                for city_lower, proper in allowed_lookup.items():
                    if city_lower in formatted_address.lower():
                        matched_city_name = proper
                        break
            return {
                "latitude": loc["lat"],
                "longitude": loc["lng"],
                "place_id": pid,
                "matched_city_ok": matched_city_name is not None,
                "matched_city": matched_city_name,
            }
    except Exception as e:
        print(f"[Geocode Error] {e}")
    return None
