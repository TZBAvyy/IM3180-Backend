import os
import re
import json
import concurrent.futures
from typing import Dict, Optional, List, Any, Set

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


def normalize_location_key(name: Optional[str], city: Optional[str], address: Optional[str]) -> str:
    """
    Produce a normalized key for deduplicating locations across attempts.
    """
    def clean(value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip().lower()

    parts = [clean(name), clean(city), clean(address)]
    return "|".join(parts)


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
            keyword_guidance_lines.append(f"- {cat}: {', '.join(hints[:5])}")
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

    def build_avoid_list(current_output: Dict[str, list], limit: int = 40) -> List[str]:
        """
        Build a deduplicated, ordered list of existing locations to help the LLM avoid repeats.
        """
        seen: Set[str] = set()
        ordered: List[str] = []
        for cat in allowed_categories:
            for activity in current_output.get(cat, []):
                if not isinstance(activity, dict):
                    continue
                name = activity.get("name")
                city_val = activity.get("city")
                if not isinstance(name, str) or not isinstance(city_val, str):
                    continue
                label = f"{name.strip()} ({city_val.strip()})"
                if not label or label in seen:
                    continue
                seen.add(label)
                ordered.append(label)
                if len(ordered) >= limit:
                    return ordered
        return ordered

    def compute_remaining_state(current_output: Dict[str, list]):
        """
        Calculate outstanding category and city allocations based on the accumulated output.
        """
        category_remaining = {
            cat: max(0, category_quotas.get(cat, 0) - len(current_output.get(cat, [])))
            for cat in allowed_categories
        }
        city_remaining = {city: city_target_totals[city] for city in cleaned_cities}
        category_city_remaining = {
            city: {cat: category_city_targets[city][cat] for cat in allowed_categories}
            for city in cleaned_cities
        }

        for cat, activities in current_output.items():
            if cat not in category_remaining:
                continue
            for activity in activities:
                if not isinstance(activity, dict):
                    continue
                city_val = activity.get("city")
                if not isinstance(city_val, str):
                    continue
                canonical_city = allowed_city_lookup.get(city_val.strip().lower(), city_val.strip())
                if canonical_city not in city_remaining:
                    continue
                city_remaining[canonical_city] = max(0, city_remaining[canonical_city] - 1)
                if cat in category_city_remaining[canonical_city]:
                    category_city_remaining[canonical_city][cat] = max(
                        0, category_city_remaining[canonical_city][cat] - 1
                    )

        return category_remaining, city_remaining, category_city_remaining

    def build_prompt(
        extra_guidance: str = "",
        attempt: int = 1,
        avoided_locations: Optional[List[str]] = None,
        compact: bool = False,
    ) -> str:
        retry_block = ""
        if extra_guidance:
            guidance_lines = "\n".join(f"    {line}" for line in extra_guidance.strip().splitlines())
            retry_block = f"""
    Retry guidance (attempt #{attempt}):
{guidance_lines}
    You must correct every remaining slot listed above within this attempt."""

        avoid_block = ""
        if avoided_locations:
            avoid_lines = "\n".join(f"    - {place}" for place in avoided_locations)
            avoid_block = f"""
    Locations already selected (do not repeat any of these):
{avoid_lines}
    Only suggest brand new places not listed above."""

        if compact:
            compact_keyword_hint = "Keep the list varied and authentic; avoid duplicate places or chains."
            compact_language_hint = "Verify addresses belong to the specified city; transliterations are acceptable."
            return f"""
    You are planning activities only in: {cities_inline}.
    Summarized preferences: {prefs_text}.
    Respond with strict JSON keyed by "categories".

    Constraints:
    - Total activities: {activities_total}
    - Exactly {max_locations_per_city} per city ({", ".join(f"{city}={city_target_totals[city]}" for city in cleaned_cities)})
    - Category quotas (must match precisely):
    {quota_guidance}
    - City/category allocations (every cell required):
    {category_city_guidance}
{retry_block}{avoid_block}

    Guidance:
    - {compact_keyword_hint}
    - {compact_language_hint}
    - Allowed categories only: {allowed_cats_text}
    - Each item requires name, address, city (exactly one of the listed cities).

    JSON schema (no markdown or commentary):
    {{
      "categories": {{
        "Food Tour": [{{"name": "...", "address": "...", "city": "..."}}, ...],
        ...
      }}
    }}
    """

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
    - Your list must be fresh for each attempt - no duplicate locations across attempts.
{retry_block}{avoid_block}
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


    def run_single_attempt(
        prompt: str,
        attempt: int,
        forbidden_keys: Optional[Set[str]] = None,
    ) -> tuple[Dict[str, list], Dict[str, int], Dict[str, int], Dict[str, Dict[str, int]]]:
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
        attempt_seen_keys: Set[str] = set()

        for cat, activities in llm_categories.items():
            if cat not in valid_categories:
                continue
            for activity in activities:
                try:
                    name = activity.get("name") or "Unknown"
                    address_value = activity.get("address", "Address not available")
                    addr = address_value if isinstance(address_value, str) else str(address_value)
                    raw_city = activity.get("city")
                    city_name = None
                    if isinstance(raw_city, str):
                        city_name = allowed_city_lookup.get(raw_city.strip().lower())
                    addr_lower = addr.lower()
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
                    key = normalize_location_key(name, city_name, addr)
                    if key in attempt_seen_keys:
                        continue
                    if forbidden_keys and key in forbidden_keys:
                        continue

                    categories_output[cat].append(
                        {
                            "name": name,
                            "address": addr,
                            "city": city_name,
                            "category": cat,
                            "photo_url": None,
                            "photo_pending": False,
                            "latitude": None,
                            "longitude": None,
                            "place_id": None,
                        }
                    )
                    attempt_seen_keys.add(key)
                    category_remaining[cat] -= 1
                    city_remaining[city_name] -= 1
                    category_city_remaining[city_name][cat] -= 1

                except Exception as err:
                    print(f"Skipping activity in {cat} due to error: {err}")
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

        return categories_output, category_remaining, city_remaining, category_city_remaining

    max_attempts = 3
    retry_guidance = ""
    accumulated_output: Dict[str, List[Dict[str, Any]]] = {cat: [] for cat in allowed_categories}
    seen_location_keys: Set[str] = set()
    geocode_cache: Dict[str, Optional[Dict[str, Any]]] = {}

    category_remaining, city_remaining, category_city_remaining = compute_remaining_state(accumulated_output)

    for attempt in range(1, max_attempts + 1):
        avoid_for_prompt = build_avoid_list(accumulated_output)
        use_compact_prompt = attempt == 1 and not retry_guidance
        prompt = build_prompt(
            retry_guidance,
            attempt,
            avoid_for_prompt if avoid_for_prompt else None,
            compact=use_compact_prompt,
        )
        output, _, _, _ = run_single_attempt(prompt, attempt, seen_location_keys)

        for cat, activities in output.items():
            if cat not in accumulated_output:
                continue
            for activity in activities:
                if not isinstance(activity, dict):
                    continue
                name = activity.get("name")
                address_value = activity.get("address", "")
                city_value = activity.get("city")
                if not isinstance(name, str) or not isinstance(city_value, str):
                    continue
                if category_remaining.get(cat, 0) <= 0:
                    continue
                addr = address_value if isinstance(address_value, str) else str(address_value)
                canonical_guess = allowed_city_lookup.get(city_value.strip().lower(), city_value.strip())
                initial_key = normalize_location_key(name, canonical_guess, addr)
                if initial_key in seen_location_keys:
                    continue

                if initial_key in geocode_cache:
                    geo = geocode_cache[initial_key]
                else:
                    geo = resolve_latlng_from_address(
                        addr,
                        canonical_guess,
                        allowed_city_variants,
                        allowed_city_lookup,
                    )
                    geocode_cache[initial_key] = geo

                if not (geo and geo.get("matched_city_ok")):
                    continue
                final_city = canonical_guess
                if geo.get("matched_city"):
                    matched_canonical = allowed_city_lookup.get(
                        geo["matched_city"].lower(),
                        final_city,
                    )
                    if matched_canonical:
                        final_city = matched_canonical
                final_key = normalize_location_key(name, final_city, addr)
                if final_key != initial_key:
                    geocode_cache[final_key] = geo
                if final_key in seen_location_keys:
                    continue
                if final_city not in city_remaining:
                    continue
                if city_remaining.get(final_city, 0) <= 0:
                    continue
                if category_city_remaining[final_city].get(cat, 0) <= 0:
                    continue
                activity["city"] = final_city
                activity["latitude"] = geo["latitude"]
                activity["longitude"] = geo["longitude"]
                activity["place_id"] = geo.get("place_id")
                accumulated_output[cat].append(activity)
                seen_location_keys.add(final_key)
                category_remaining[cat] -= 1
                city_remaining[final_city] -= 1
                category_city_remaining[final_city][cat] -= 1

        category_remaining, city_remaining, category_city_remaining = compute_remaining_state(accumulated_output)
        if sum(category_remaining.values()) == 0:
            retry_guidance = ""
            break

        if attempt == max_attempts:
            break

        retry_lines = []
        for city, remaining in city_remaining.items():
            if remaining <= 0:
                continue
            cat_breakdown = [
                f"{cat}: {category_city_remaining[city][cat]}"
                for cat in allowed_categories
                if category_city_remaining[city].get(cat, 0) > 0
            ]
            if cat_breakdown:
                retry_lines.append(f"- {city}: {remaining} slots missing (need {', '.join(cat_breakdown)})")
            else:
                retry_lines.append(f"- {city}: {remaining} slots missing")
        if not retry_lines:
            retry_lines.append("- Some slots remain unfilled; provide fresh options for the outstanding city/category pairs.")
        retry_lines.append("- Provide brand new locations that have not appeared in earlier attempts.")
        retry_lines.append("- Return only the new places needed for the slots above; omit categories that are already full.")
        retry_guidance = "\n".join(retry_lines)

    category_remaining, city_remaining, category_city_remaining = compute_remaining_state(accumulated_output)

    for city, remaining in city_remaining.items():
        if remaining > 0:
            print(f"[Gemini] City {city} still short by {remaining} after {max_attempts} attempts")

    for cat, remaining in category_remaining.items():
        if remaining > 0:
            print(f"[Gemini] Category {cat} still short by {remaining} after {max_attempts} attempts")

    for city, cat_map in category_city_remaining.items():
        for cat, remaining in cat_map.items():
            if remaining > 0:
                print(f"[Gemini] Outstanding -> {city} / {cat}: {remaining}")

    return accumulated_output




# --- Gemini utilities ---
def call_gemini_once(prompt: str, model: str = "gemini-2.5-flash", timeout: int = 50):
    client = get_next_client()

    def _generate():
        tuned_kwargs = {
            "candidate_count": 1,
            "temperature": 0.7,
            "top_p": 0.95,
            "max_output_tokens": 4096,
            "response_mime_type": "application/json",
        }
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                **tuned_kwargs,
            )
        except TypeError:
            return client.models.generate_content(
                model=model,
                contents=prompt,
            )

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            fut = executor.submit(
                _generate,
            )
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
