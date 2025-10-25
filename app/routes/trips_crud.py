from fastapi import APIRouter, Depends, HTTPException
from app.db.mysql_pool import get_db

router = APIRouter(prefix="/trips", tags=["trips"])

# ---------------- READ ----------------
@router.get("/{trip_id}")
def read_trip(trip_id: int, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)

    # get trip
    cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
    trip = cur.fetchone()
    if not trip:
        cur.close()
        raise HTTPException(404, "Trip not found")

    # get day_trips
    cur.execute("SELECT * FROM day_trips WHERE trip_id=%s ORDER BY day_number", (trip_id,))
    days = cur.fetchall()

    # attach activities for each day
    for d in days:
        cur.execute("SELECT * FROM activities WHERE day_trip_id=%s", (d["id"],))
        d["activities"] = cur.fetchall()

    trip["days"] = days
    cur.close()
    return trip


@router.get("/user/{user_id}")
def read_user_trips(user_id: int, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)

    # get all trips for this user
    cur.execute("SELECT * FROM trips WHERE user_id=%s ORDER BY start_date", (user_id,))
    userTrips = cur.fetchall()

    if not userTrips:
        cur.close()
        return []  # return empty list instead of 404

    for trip in userTrips:
        # get days for this trip
        cur.execute("SELECT * FROM day_trips WHERE trip_id=%s ORDER BY day_number", (trip["id"],))
        days = cur.fetchall()

        for d in days:
            # get activities for this day
            cur.execute("SELECT * FROM activities WHERE day_trip_id=%s", (d["id"],))
            d["activities"] = cur.fetchall()

        trip["days"] = days

    cur.close()
    return userTrips

# ---------------- UPDATE ----------------
@router.put("/activities/{activity_id}")
def update_activity(activity_id: int, body: dict, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM activities WHERE id=%s", (activity_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        raise HTTPException(404, "Activity not found")

    # dynamic update: only update provided fields
    fields = []
    values = []
    for key, val in body.items():
        if key in ["destination", "type", "start_time", "end_time", "description", "rating", "address"]:
            fields.append(f"{key}=%s")
            values.append(val)

    if not fields:
        cur.close()
        raise HTTPException(400, "No valid fields to update")

    values.append(activity_id)
    sql = f"UPDATE activities SET {', '.join(fields)} WHERE id=%s"
    cur.execute(sql, tuple(values))
    conn.commit()

    cur.execute("SELECT * FROM activities WHERE id=%s", (activity_id,))
    updated = cur.fetchone()
    cur.close()
    return updated

@router.put("/days/{day_id}")
def update_day(day_id: int, body: dict, conn=Depends(get_db)):
    """
    Body can include any of:
    accommodation_name, accommodation_address, accommodation_notes,
    preferred_start_time, preferred_end_time
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM day_trips WHERE id=%s", (day_id,))
    existing = cur.fetchone()
    if not existing:
        cur.close()
        raise HTTPException(404, "Day trip not found")

    fields = []
    values = []
    allowed = [
        "accommodation_name",
        "accommodation_address",
        "accommodation_notes",
        "preferred_start_time",
        "preferred_end_time",
    ]

    for key, val in body.items():
        if key in allowed:
            fields.append(f"{key}=%s")
            values.append(val)

    if not fields:
        cur.close()
        raise HTTPException(400, "No valid fields to update")

    values.append(day_id)
    sql = f"UPDATE day_trips SET {', '.join(fields)} WHERE id=%s"
    cur.execute(sql, tuple(values))
    conn.commit()

    cur.execute("SELECT * FROM day_trips WHERE id=%s", (day_id,))
    updated = cur.fetchone()
    cur.close()
    return updated


# ---------------- CREATE ----------------
@router.post("/", status_code=201)
def create_trip(body: dict, conn=Depends(get_db)):
    """
    Body should include: user_id, name, start_date, end_date
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "INSERT INTO trips (user_id, name, start_date, end_date) VALUES (%s,%s,%s,%s)",
        (body["user_id"], body["name"], body["start_date"], body["end_date"]),
    )
    conn.commit()
    trip_id = cur.lastrowid

    cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
    trip = cur.fetchone()
    cur.close()
    return trip


@router.post("/{trip_id}/days", status_code=201)
def create_day(trip_id: int, body: dict, conn=Depends(get_db)):
    """
    Body should include:
    day_number, date
    Optional: accommodation_name, accommodation_address, accommodation_notes,
              preferred_start_time, preferred_end_time
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        INSERT INTO day_trips (
            trip_id, day_number, date,
            accommodation_name, accommodation_address, accommodation_notes,
            preferred_start_time, preferred_end_time
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            trip_id,
            body["day_number"],
            body["date"],
            body.get("accommodation_name"),
            body.get("accommodation_address"),
            body.get("accommodation_notes"),
            body.get("preferred_start_time"),
            body.get("preferred_end_time"),
        ),
    )
    conn.commit()
    day_id = cur.lastrowid

    cur.execute("SELECT * FROM day_trips WHERE id=%s", (day_id,))
    day = cur.fetchone()
    cur.close()
    return day



@router.post("/days/{day_id}/activities", status_code=201)
def create_activity(day_id: int, body: dict, conn=Depends(get_db)):
    """
    Body should include: destination, type, start_time, end_time, description, rating, address
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        INSERT INTO activities 
        (day_trip_id, destination, type, start_time, end_time, description, rating, address)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            day_id,
            body["destination"],
            body.get("type"),
            body.get("start_time"),
            body.get("end_time"),
            body.get("description"),
            body.get("rating"),
            body.get("address"),
        ),
    )
    conn.commit()
    activity_id = cur.lastrowid

    cur.execute("SELECT * FROM activities WHERE id=%s", (activity_id,))
    activity = cur.fetchone()
    cur.close()
    return activity

# ---------------- CREATE FULL TRIP (BULK INSERT) ----------------
@router.post("/full", status_code=201)
def create_full_trip(body: dict, conn=Depends(get_db)):
    """
    Body example:
    {
      "user_id": 2,
      "name": "Japan Autumn Adventure",
      "start_date": "2025-11-10",
      "end_date": "2025-11-15",
      "days": [
        {
          "day_number": 1,
          "date": "2025-11-10",
          "activities": [
            {
              "destination": "Shinjuku Gyoen National Garden",
              "type": "Nature",
              "start_time": "09:00:00",
              "end_time": "11:00:00",
              "description": "Beautiful garden with autumn leaves.",
              "rating": 4.7,
              "address": "11 Naitomachi, Shinjuku City, Tokyo"
            }
          ]
        }
      ]
    }
    """
    cur = conn.cursor(dictionary=True)
    try:
        # Insert trip
        cur.execute(
            """
            INSERT INTO day_trips (
                trip_id, day_number, date,
                accommodation_name, accommodation_address, accommodation_notes,
                preferred_start_time, preferred_end_time
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
                (
                    trip_id,
                    d["day_number"],
                    d["date"],
                    d.get("accommodation_name"),
                    d.get("accommodation_address"),
                    d.get("accommodation_notes"),
                    d.get("preferred_start_time"),
                    d.get("preferred_end_time"),
                ),
        )

        trip_id = cur.lastrowid

        # Insert days + activities
        for d in body.get("days", []):
            cur.execute(
                "INSERT INTO day_trips (trip_id, day_number, date) VALUES (%s,%s,%s)",
                (trip_id, d["day_number"], d["date"]),
            )
            day_id = cur.lastrowid

            for a in d.get("activities", []):
                cur.execute(
                    """
                    INSERT INTO activities
                    (day_trip_id, destination, type, start_time, end_time, description, rating, address)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        day_id,
                        a["destination"],
                        a.get("type"),
                        a.get("start_time"),
                        a.get("end_time"),
                        a.get("description"),
                        a.get("rating"),
                        a.get("address"),
                    ),
                )

        conn.commit()
        cur.close()
        return {"message": "Trip created successfully", "trip_id": trip_id}

    except Exception as e:
        conn.rollback()
        cur.close()
        raise HTTPException(400, f"Failed to create trip: {e}")

# ---------------- DELETE ----------------
@router.delete("/del/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: int, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)
    
    # Check if activity exists
    cur.execute("SELECT * FROM activities WHERE id=%s", (activity_id,))
    activity = cur.fetchone()
    if not activity:
        cur.close()
        raise HTTPException(404, "Activity not found")
    
    # Delete the activity
    cur.execute("DELETE FROM activities WHERE id=%s", (activity_id,))
    conn.commit()
    cur.close()
    
    return None  # 204 No Content

@router.delete("/del/days/{day_id}", status_code=204)
def delete_day(day_id: int, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)
    
    # Check if day exists
    cur.execute("SELECT * FROM day_trips WHERE id=%s", (day_id,))
    day = cur.fetchone()
    if not day:
        cur.close()
        raise HTTPException(404, "Day trip not found")
    
    try:
        # Delete all activities for this day
        cur.execute("DELETE FROM activities WHERE day_trip_id=%s", (day_id,))
        
        # Delete the day trip
        cur.execute("DELETE FROM day_trips WHERE id=%s", (day_id,))
        
        conn.commit()
        cur.close()
        return None  # 204 No Content
        
    except Exception as e:
        conn.rollback()
        cur.close()
        raise HTTPException(400, f"Failed to delete day trip: {e}")
    
@router.delete("/del/{trip_id}", status_code=204)
def delete_trip(trip_id: int, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)
    
    # Check if trip exists
    cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
    trip = cur.fetchone()
    if not trip:
        cur.close()
        raise HTTPException(404, "Trip not found")
    
    try:
        # Get all day_trips for this trip
        cur.execute("SELECT id FROM day_trips WHERE trip_id=%s", (trip_id,))
        days = cur.fetchall()
        
        # Delete all activities for each day
        for day in days:
            cur.execute("DELETE FROM activities WHERE day_trip_id=%s", (day["id"],))
        
        # Delete all day_trips for this trip
        cur.execute("DELETE FROM day_trips WHERE trip_id=%s", (trip_id,))
        
        # Delete the trip itself
        cur.execute("DELETE FROM trips WHERE id=%s", (trip_id,))
    
        conn.commit()
        cur.close()
        return None  # 204 No Content
        
    except Exception as e:
        conn.rollback()
        cur.close()
        raise HTTPException(400, f"Failed to delete trip: {e}")
