import json
import math
from django.utils import timezone
from routes.models import routeStop

def get_snapped_coords(rs):
    """
    Parse rs.snapped_route (JSON text) → list[(lat,lng)]
    DB format is [[lng,lat], ...] so flip to (lat,lng).
    """
    if not rs.snapped_route:
        return None

    try:
        data = json.loads(rs.snapped_route)
        coords = []
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            lng, lat = pair
            coords.append((float(lat), float(lng)))
        return coords if coords else None
    except:
        return None
    
def calculate_heading(lat1, lng1, lat2, lng2):
    """
    Returns heading in degrees (0–360),
    where 0 = North, 90 = East, 180 = South, 270 = West.
    Handles identical or near-identical points safely.
    """

    # If no movement → return 0 (or keep last heading outside this function)
    if abs(lat1 - lat2) < 1e-9 and abs(lng1 - lng2) < 1e-9:
        return 0.0

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lng = math.radians(lng2 - lng1)

    # Standard great-circle bearing
    x = math.sin(d_lng) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(d_lng)

    heading = math.degrees(math.atan2(x, y))

    # Normalise 0–360
    heading = (heading + 360) % 360

    return heading
def get_route_coordinates(route_id, trip):
    """
    Determine which routeStop direction to use.

    Priority:
    1) If trip.trip_inbound is True → inbound direction (2nd routeStop)
    2) If trip.trip_inbound is False → outbound direction (1st routeStop)
    3) If trip.trip_inbound is None → fallback to old last-stop detection
    """

    print(f"[DEBUG] get_route_coordinates: route_id={route_id}, inbound={trip.trip_inbound}")

    stops_qs = routeStop.objects.filter(route_id=route_id).order_by("id")
    print(f"[DEBUG] found {stops_qs.count()} routeStop rows")

    if not stops_qs:
        print("[DEBUG] no routeStops found → returning []")
        return []

    # -------------------------------
    # EXPLICIT INBOUND/OUTBOUND CHOICE
    # -------------------------------
    if trip.trip_inbound is False:
        print("[DEBUG] trip_inbound=False → using inbound (index 1)")
        if stops_qs.count() >= 2:
            return extract_coords_from_routeStop(stops_qs[1])
        return extract_coords_from_routeStop(stops_qs[0])

    if trip.trip_inbound is True:
        print("[DEBUG] trip_inbound=True → using outbound (index 0)")
        return extract_coords_from_routeStop(stops_qs[0])

    # -------------------------------
    # FALLBACK: AUTO-DETECT LIKE BEFORE
    # -------------------------------
    print("[DEBUG] trip_inbound=None → using auto-detect fallback")

    direction_candidates = []

    for rs in stops_qs:
        coords, last_stop_name = extract_coords_and_last_stop(rs)

        if coords:
            direction_candidates.append({
                "coords": coords,
                "last_stop": last_stop_name
            })

    if not direction_candidates:
        print("[DEBUG] no valid directions → return []")
        return []

    trip_end_location = (trip.trip_end_location or "").lower().strip()

    for d in direction_candidates:
        ls = (d["last_stop"] or "").lower().strip()
        if trip_end_location and ls and trip_end_location in ls:
            print(f"[DEBUG] MATCH FOUND: using last_stop '{d['last_stop']}'")
            return d["coords"]

    print("[DEBUG] no match → using first direction")
    return direction_candidates[0]["coords"]


def extract_coords_from_routeStop(rs):
    # Prefer snapped route if present
    snapped = get_snapped_coords(rs)
    if snapped:
        return snapped

    coords, _ = extract_coords_and_last_stop(rs)
    return coords or []


def extract_coords_and_last_stop(rs):
    # Prefer snapped route if present
    snapped = get_snapped_coords(rs)
    if snapped:
        return snapped, None
    """Shared logic from your old loop."""
    coords = []
    last_stop_name = None

    if not rs.stops or not isinstance(rs.stops, list):
        return coords, None

    for stop in rs.stops:
        if not isinstance(stop, dict):
            continue

        sname = stop.get("stop") or stop.get("name") or stop.get("title")
        if sname:
            last_stop_name = sname

        cords = stop.get("cords") or stop.get("coords")
        if cords:
            try:
                lat_str, lng_str = cords.split(",")
                coords.append((float(lat_str.strip()), float(lng_str.strip())))
                continue
            except:
                pass

        lat = stop.get("lat") or stop.get("latitude")
        lng = stop.get("lng") or stop.get("longitude") or stop.get("long")
        if lat is not None and lng is not None:
            try:
                coords.append((float(lat), float(lng)))
                continue
            except:
                pass

    return coords, last_stop_name

def get_progress(trip):
    now = timezone.now()
    start = trip.trip_start_at
    end = trip.trip_end_at
    print(f"[DEBUG] get_progress: trip_id={trip.pk}, now={now}, start={start}, end={end}")
    duration = (end - start).total_seconds()
    elapsed = (now - start).total_seconds()
    print(f"[DEBUG] get_progress: duration={duration}s, elapsed={elapsed}s")
    if elapsed <= 0:
        print(f"[DEBUG] get_progress: returning 0.0 (not started)")
        return 0.0
    if elapsed >= duration:
        print(f"[DEBUG] get_progress: returning 1.0 (completed)")
        return 1.0
    progress = elapsed / duration
    print(f"[DEBUG] get_progress: returning {progress}")
    return progress

def interpolate(coords, progress):
    if not coords:
        return (None, None, None)
    if len(coords) == 1:
        return coords[0][0], coords[0][1], 0

    total_segments = len(coords) - 1
    segment_float = progress * total_segments
    seg_index = int(segment_float)

    if seg_index >= total_segments:
        return coords[-1][0], coords[-1][1], total_segments - 1

    seg_progress = segment_float - seg_index

    (lat1, lng1) = coords[seg_index]
    (lat2, lng2) = coords[seg_index + 1]

    lat = lat1 + (lat2 - lat1) * seg_progress
    lng = lng1 + (lng2 - lng1) * seg_progress

    return lat, lng, seg_index
