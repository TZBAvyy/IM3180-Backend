from fastapi import APIRouter, Depends, HTTPException
from app.db.mysql_pool import get_db

router = APIRouter(prefix="/trips", tags=["trips"])

# ---------------- READ ----------------

@router.get("/list/recommended")
def get_recommended_trips(conn=Depends(get_db)):
    """
    Returns all trips that have a thumbnail_url (i.e., those with images)
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM trips WHERE thumbnail_url IS NOT NULL AND thumbnail_url != '' ORDER BY created_at DESC")
    trips = cur.fetchall()
    cur.close()
    return trips


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

    # dynamic update: only update provided valid fields
    allowed_fields = [
        "destination", "type", "start_time", "end_time", "description",
        "rating", "address", "place_id", "thumbnail", "lat", "lng"
    ]

    fields, values = [], []
    for key, val in body.items():
        if key in allowed_fields:
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


@router.put("/{trip_id}")
def update_trip(trip_id: int, body: dict, conn=Depends(get_db)):
    cur = conn.cursor(dictionary=True)

    # Verify trip exists
    cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
    trip = cur.fetchone()
    if not trip:
        cur.close()
        raise HTTPException(404, "Trip not found")

    # Update trip-level info
    trip_fields = []
    trip_values = []
    for key in ["name", "start_date", "end_date"]:
        if key in body:
            trip_fields.append(f"{key}=%s")
            trip_values.append(body[key])

    if trip_fields:
        trip_values.append(trip_id)
        cur.execute(f"UPDATE trips SET {', '.join(trip_fields)} WHERE id=%s", tuple(trip_values))

    # Update days and activities if provided
    if "days" in body:
        for day in body["days"]:
            day_id = day.get("id")
            if not day_id:
                continue

            # update day info
            if any(k in day for k in ["date", "destination"]):
                cur.execute(
                    "UPDATE day_trips SET date=%s, destination=%s WHERE id=%s",
                    (day.get("date"), day.get("destination"), day_id),
                )

            # update activities
            for activity in day.get("activities", []):
                activity_id = activity.get("id")
                if not activity_id:
                    continue

                cur.execute(
                    """
                    UPDATE activities
                    SET destination=%s,
                        type=%s,
                        start_time=%s,
                        end_time=%s,
                        description=%s,
                        rating=%s,
                        address=%s,
                        place_id=%s,
                        thumbnail=%s,
                        lat=%s,
                        lng=%s
                    WHERE id=%s
                    """,
                    (
                        activity.get("destination"),
                        activity.get("type"),
                        activity.get("start_time"),
                        activity.get("end_time"),
                        activity.get("description"),
                        activity.get("rating"),
                        activity.get("address"),
                        activity.get("place_id"),
                        activity.get("thumbnail"),
                        activity.get("lat"),
                        activity.get("lng"),
                        activity_id,
                    ),
                )

    conn.commit()

    # Return updated trip
    cur.execute("SELECT * FROM trips WHERE id=%s", (trip_id,))
    updated_trip = cur.fetchone()
    cur.close()
    return updated_trip




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
    Body should include: day_number, date
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "INSERT INTO day_trips (trip_id, day_number, date) VALUES (%s,%s,%s)",
        (trip_id, body["day_number"], body["date"]),
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
        (day_trip_id, destination, type, start_time, end_time, description, rating, address, place_id, thumbnail, lat, lng)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            body.get("place_id"),
            body.get("thumbnail"),
            body.get("lat"),
            body.get("lng"),
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
    cur = conn.cursor(dictionary=True)
    try:
        # Insert trip
        cur.execute(
            "INSERT INTO trips (user_id, name, start_date, end_date) VALUES (%s,%s,%s,%s)",
            (body["user_id"], body["name"], body["start_date"], body["end_date"]),
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
                    (day_trip_id, destination, type, start_time, end_time, description, rating, address, place_id, thumbnail, lat, lng)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                        a.get("place_id"),
                        a.get("thumbnail"),
                        a.get("lat"),
                        a.get("lng"),
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
