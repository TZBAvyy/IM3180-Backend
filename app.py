import os, time
from typing import Optional
#from math import radians, sin, cos, asin, sqrt  # (not required; keep if you extend)
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import bcrypt, jwt
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv

import numpy as np
from sklearn.cluster import DBSCAN
import folium
from math import ceil
import json
import re
from google import genai

API_KEY = "AIzaSyBugSwhaA8n5qWDGmyIHF8O0fy_7b8lPGo"
client = genai.Client(api_key=API_KEY)

# --- config & DB pool ---
load_dotenv()  # loads .env if present

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "autocommit": True,
}
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
JWT_ALG = "HS256"

# Validate env quickly
for k in ("host","user","password","database"):
    if not DB_CONFIG.get(k):
        raise RuntimeError(f"Missing env var {k}")

pool = pooling.MySQLConnectionPool(pool_name="authpool", pool_size=5, **DB_CONFIG)

def db():
    conn = pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()

# --- models ---
class SignupIn(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = ""

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class MeOut(BaseModel):
    id: int
    email: EmailStr
    name: str

# --- app ---
app = FastAPI(title="Login API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your frontend domain in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- helpers ---
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_token(user_id: int, email: str) -> TokenOut:
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "email": email, "exp": exp}
    token = jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)
    return TokenOut(access_token=token, expires_in=JWT_EXPIRE_MINUTES * 60)

def get_user_by_email(conn, email: str):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, name, password_hash FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    return row

def create_user(conn, email: str, name: str, password: str):
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (%s,%s,%s)",
            (email, name, hash_password(password)),
        )
        user_id = cur.lastrowid
        return user_id
    except mysql.connector.errors.IntegrityError:
        return None
    finally:
        cur.close()

# --- endpoints ---
@app.get("/")
def root():
    return {"ok": True, "endpoints": ["/signup", "/login", "/me"]}

@app.post("/signup", response_model=MeOut, status_code=201)
def signup(body: SignupIn, conn=Depends(db)):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    existing = get_user_by_email(conn, body.email)
    if existing:
        raise HTTPException(409, "Email already registered")
    user_id = create_user(conn, body.email, body.name or "", body.password)
    if not user_id:
        raise HTTPException(409, "Email already registered")
    return MeOut(id=user_id, email=body.email, name=body.name or "")

@app.post("/login", response_model=TokenOut)
def login(body: LoginIn, conn=Depends(db)):
    row = get_user_by_email(conn, body.email)
    if not row or not verify_password(body.password, row["password_hash"]):
        # don't reveal which part failed
        raise HTTPException(401, "Invalid email or password")
    return create_token(row["id"], row["email"])

# Minimal token auth for demo /me
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
security = HTTPBearer()

@app.get("/me", response_model=MeOut)
def me(creds: HTTPAuthorizationCredentials = Depends(security), conn=Depends(db)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
        uid = int(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, email, name FROM users WHERE id=%s", (uid,))
    row = cur.fetchone()
    cur.close()
    if not row:
        raise HTTPException(404, "User not found")
    return MeOut(**row)


def convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, np.generic):
        return obj.item()
    else:
        return obj

# --- Endpoint 1: Generate itinerary using LLM ---
def generate_itinerary(user_stay_days, max_hours_per_day):
    prompt = f"""
    Suggest tourist attractions in Singapore that a visitor can explore in {user_stay_days} days.
    Return strictly a JSON array where each entry includes:

    {{
      "name": "Gardens by the Bay",
      "latitude": 1.2827,
      "longitude": 103.865,
      "suggested_visit_hours": 2,
      "priority": 1
    }}

    Requirements:
    - Include enough attractions to fill {user_stay_days} days of sightseeing, assuming {max_hours_per_day} hours per day.
    - Latitude and longitude must be decimal numbers.
    - suggested_visit_hours must be a number (hours spent at the attraction).
    - Priority: 1 = must see, 5 = optional.
    - Return only valid JSON. Do not include extra text or comments.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    llm_output = response.text

    # --- Robust JSON extraction ---
    try:
        start_idx = llm_output.index("[")
        end_idx = llm_output.rindex("]") + 1
        json_str = llm_output[start_idx:end_idx]
        try:
            llm_data = json.loads(json_str)
        except json.JSONDecodeError:
            json_str_fixed = re.sub(r",\s*\{[^\{\}]*$", "", json_str)
            llm_data = json.loads(json_str_fixed)
    except (ValueError, json.JSONDecodeError) as e:
        return {"error": "Failed to parse JSON from LLM output", "details": str(e)}

    # --- Convert to locations ---
    locations_sorted = [
        (d["latitude"], d["longitude"], d["suggested_visit_hours"], d["name"], d["priority"])
        for d in llm_data
    ]

    # --- Add hotel/start location ---
    hotel_lat, hotel_lon = 1.3000, 103.8300
    locations_sorted.insert(0, (hotel_lat, hotel_lon, 0, "Hotel/Start", 1))

    # --- DBSCAN clustering ---
    coords = np.array([(lat, lon) for lat, lon, _, _, _ in locations_sorted[1:]])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    locations_data = []
    for i, loc in enumerate(locations_sorted[1:]):
        locations_data.append({
            "latitude": loc[0],
            "longitude": loc[1],
            "suggested_visit_hours": loc[2],
            "name": loc[3],
            "priority": loc[4],
            "cluster": int(labels[i])
        })

    # --- Assign locations to days based on priority ---
    sorted_by_priority = sorted(locations_data, key=lambda x: x["priority"])
    solution_days_raw = [[] for _ in range(user_stay_days)]
    day_hours = [0 for _ in range(user_stay_days)]

    for loc in sorted_by_priority:
        for day_idx in range(user_stay_days):
            if day_hours[day_idx] + loc["suggested_visit_hours"] <= max_hours_per_day:
                solution_days_raw[day_idx].append(loc)
                day_hours[day_idx] += loc["suggested_visit_hours"]
                break

    # --- Group by cluster within each day ---
    solution_days = []
    for day_locs in solution_days_raw:
        clusters_dict = {}
        for loc in day_locs:
            clusters_dict.setdefault(loc["cluster"], []).append({
                "name": loc["name"],
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "priority": loc["priority"],
                "suggested_visit_hours": loc["suggested_visit_hours"]
            })

        day_clusters = []
        for cid, locs in clusters_dict.items():
            highest_priority = min([l["priority"] for l in locs])
            day_clusters.append({
                "cluster": cid,
                "highest_priority": highest_priority,
                "locations": sorted(locs, key=lambda x: x["priority"])
            })

        day_clusters_sorted = sorted(day_clusters, key=lambda x: x["highest_priority"])
        for c in day_clusters_sorted:
            c.pop("highest_priority")
        solution_days.append(day_clusters_sorted)

    return {"solution": "solution1", "days": solution_days}

@app.post("/plan_itinerary_llm")
def plan_itinerary():
    data = request.json
    user_stay_days = data.get("user_stay_days", 1)
    max_hours_per_day = data.get("max_hours_per_day", 8)
    result = generate_itinerary(user_stay_days, max_hours_per_day)
    return jsonify(result)


# --- Endpoint 2: Cluster provided locations and generate maps ---
@app.post('/get_clusters')
def get_clusters():
    data = request.get_json()
    locations_sorted = data.get('locations_sorted', [])
    requested_days = data.get('requested_days', 1)
    max_hours_per_day = data.get('max_hours_per_day', 10)

    if not locations_sorted:
        return jsonify({"error": "locations_sorted must be provided"}), 400

    coords = np.array([(lat, lon) for lat, lon, _, _ in locations_sorted[1:]])
    db = DBSCAN(eps=0.0225, min_samples=1).fit(coords)
    labels = db.labels_

    locations_data = []
    for i, loc in enumerate(locations_sorted[1:]):
        locations_data.append(tuple(loc) + (labels[i],))

    clusters_dict = {}
    for loc in locations_data:
        clusters_dict.setdefault(loc[4], []).append(loc)

    # Solution 1: fit into day1
    sorted_by_priority = sorted(locations_data, key=lambda x: x[2])
    current_day_hours = 0
    solution1_day1 = []
    solution1_rejected = []
    for loc in sorted_by_priority:
        if current_day_hours + loc[3] <= max_hours_per_day:
            solution1_day1.append(loc)
            current_day_hours += loc[3]
        else:
            solution1_rejected.append(loc)

    # Solution 2: split clusters across requested days
    total_stay_hours = sum([loc[3] for loc in locations_data])
    min_days_needed = ceil(total_stay_hours / max_hours_per_day)
    num_days = max(requested_days, min_days_needed)

    cluster_ids = sorted(clusters_dict.keys())
    clusters_per_day = ceil(len(cluster_ids) / num_days)
    solution2_days = []

    for day in range(num_days):
        start_idx = day * clusters_per_day
        end_idx = start_idx + clusters_per_day
        day_cluster_ids = cluster_ids[start_idx:end_idx]
        day_locs = []
        for cid in day_cluster_ids:
            day_locs.extend(clusters_dict[cid])
        solution2_days.append(day_locs)

    # Prepare response
    clusters_response = {
        'solution1': {
            'day1': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                      'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in solution1_day1],
            'rejected': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                          'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in solution1_rejected]
        },
        'solution2': [{'day': day_idx+1,
                       'locations': [{'latitude': loc[0], 'longitude': loc[1], 'priority': loc[2],
                                      'stay_hours': loc[3], 'cluster_id': loc[4]} for loc in day_locs]}
                      for day_idx, day_locs in enumerate(solution2_days)]
    }

    # Convert numpy types
    clusters_response = convert_numpy_types(clusters_response)

    # Visualization (optional: generates map HTML files)
    colors = itertools.cycle(["red", "blue", "green", "purple", "orange", "darkred",
                              "lightblue", "lightgreen", "cadetblue", "pink"])
    for day_idx, day_locs in enumerate(solution2_days):
        m_day = folium.Map(location=(1.3521, 103.8198), zoom_start=12)
        for loc in day_locs:
            lat, lon, prio, stay, cluster_id = loc
            folium.CircleMarker(
                location=(lat, lon),
                radius=7,
                color=next(colors),
                fill=True,
                fill_opacity=0.7,
                popup=f"Priority {prio}, Stay {stay}h, Cluster {cluster_id}"
            ).add_to(m_day)
        html_file = f"day_{day_idx + 1}.html"
        m_day.save(html_file)
        # Optional: open automatically
        # import webbrowser
        # webbrowser.open(f'file:///{html_file}')

    return jsonify(clusters_response)