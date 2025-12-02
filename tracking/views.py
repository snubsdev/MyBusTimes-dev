from django.shortcuts import render
from .models import *
from fleet.models import MBTOperator, helper
from mybustimes.permissions import ReadOnly
from rest_framework import generics
from .serializers import trackingSerializer, trackingDataSerializer, TripSerializer, TrackingSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
#from rest_framework_api_key.permissions import HasAPIKey
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .forms import trackingForm
from django.shortcuts import redirect
from main.models import UserKeys
from rest_framework import generics, serializers
from routes.models import routeStop
from fleet.models import fleet
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def get_user_from_key(request):
    session_key = request.headers.get("Authorization")
    if not session_key:
        return None, Response({"detail": "Missing Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    if session_key.startswith("SessionKey "):
        session_key = session_key.split("SessionKey ")[1]

    try:
        user_key = UserKeys.objects.select_related("user").get(session_key=session_key)
    except UserKeys.DoesNotExist:
        return None, Response({"detail": "Invalid session key"}, status=status.HTTP_401_UNAUTHORIZED)

    return user_key.user, None


@csrf_exempt
class create_tracking(generics.CreateAPIView):
    serializer_class = trackingSerializer

    def post(self, request, *args, **kwargs):
        user, error = get_user_from_key(request)
        if error:
            return error  # Unauthorized

        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "data": serializer.data}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# List all trips
class TripListView(generics.ListAPIView):
    queryset = Trip.objects.all().order_by("-trip_start_at")
    serializer_class = TripSerializer


# Get a single trip by ID
class TripDetailView(generics.RetrieveAPIView):
    queryset = Trip.objects.all()
    serializer_class = TripSerializer
    lookup_field = "trip_id"


# List all tracking records
class TrackingListView(generics.ListAPIView):
    queryset = Tracking.objects.all().order_by("-tracking_updated_at")
    serializer_class = TrackingSerializer


# Get a single tracking record by ID
class TrackingDetailView(generics.RetrieveAPIView):
    queryset = Tracking.objects.all()
    serializer_class = TrackingSerializer
    lookup_field = "tracking_id"


# Filter tracking by vehicle (useful for live bus display)
class TrackingByVehicleView(generics.ListAPIView):
    serializer_class = TrackingSerializer

    def get_queryset(self):
        vehicle_id = self.kwargs["vehicle_id"]
        return Tracking.objects.filter(tracking_vehicle_id=vehicle_id).order_by("-tracking_updated_at")

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import Trip, Tracking, fleet, route, CustomUser  # adjust imports

@csrf_exempt
def StartNewTripView(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only API"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        data_session_key = data.get("session_key")
        vehicle_id = data.get("vehicle_id")
        route_id = data.get("route_id")
        route_number = data.get("route_number")
        trip_end_location = data.get("outbound_destination")
        trip_start_at = data.get("trip_date_time")  # should be ISO8601 string
    except Exception as e:
        return JsonResponse({"error": "Invalid request data", "details": str(e)}, status=400)

    if not data_session_key:
        return JsonResponse({"error": "Missing session_key"}, status=400)
    if not vehicle_id:
        return JsonResponse({"error": "Missing vehicle_id"}, status=400)
    
    try:
        user_key = UserKeys.objects.select_related("user").get(session_key=data_session_key)
        user = user_key.user
    except UserKeys.DoesNotExist:
        return JsonResponse({"error": "Invalid session key"}, status=400)

    # Get related objects
    try:
        vehicle = fleet.objects.get(id=vehicle_id)
        operator_inst = vehicle.operator
    except fleet.DoesNotExist:
        return JsonResponse({"error": "Vehicle not found"}, status=404)
            
    # Permission check
    if operator_inst.owner != user:
        # See if this user is listed as a helper for this operator
        is_helper = helper.objects.filter(
            operator=operator_inst,
            helper=user
        ).exists()

        if not is_helper:
            return JsonResponse({"error": "Permission denied"}, status=403)

    route_obj = None
    if route_id:
        try:
            route_obj = route.objects.get(id=route_id)
        except route.DoesNotExist:
            route_obj = None

    # Create Trip
    trip = Trip.objects.create(
        trip_vehicle=vehicle,
        trip_route=route_obj,
        trip_route_num=route_number,
        trip_end_location=trip_end_location,
        trip_start_at=trip_start_at or timezone.now(),
        trip_driver = user
        # You may want to attach the driver via session_key -> CustomUser lookup
    )

    # Create Tracking (initial data)
    tracking = Tracking.objects.create(
        tracking_vehicle=vehicle,
        tracking_route=route_obj,
        tracking_trip=trip,
        tracking_data={"X": 0, "Y": 0, "delay": 0, "heading": 0, "current_stop_idx": "0"},
        tracking_start_location="Depot",  # optional: replace with real value
        tracking_end_location=trip_end_location,
        tracking_start_at=trip_start_at or timezone.now(),
    )

    return JsonResponse(
        {
            "message": "Trip started",
            "session_key": data_session_key,
            "trip_id": trip.trip_id,
            "tracking_id": tracking.tracking_id,
        },
        status=201
    )

def active_trips(request):
    active_trips = Tracking.objects.filter(trip_ended=False).all()
    return JsonResponse({"active_trips": list(active_trips)}, status=200)

def update_tracking(request, tracking_id):
    if request.method == 'POST':
        new_tracking_data = request.POST.get('tracking_data')

        tracking = Tracking.objects.get(tracking_id=tracking_id)
        tracking.tracking_data = new_tracking_data
        tracking.save()

        data = {
            'tracking_id': tracking.tracking_id,
            'tracking_data': tracking.tracking_data,
        }

        return JsonResponse({"success": True, "data": data}, status=200)
    else:
        return JsonResponse({"success": False, "error": "Invalid method"}, status=400)

def update_tracking_template(request, tracking_id):
    tracking = Tracking.objects.get(tracking_id=tracking_id)
    return render(request, 'update.html', {'tracking': tracking})

def create_tracking_template(request, operator_slug):
    operator_instance = MBTOperator.objects.filter(operator_slug=operator_slug).first()
    form = trackingForm(operator=operator_instance)  # 👈 Pass operator_instance to form

    if request.method == 'POST':
        form = trackingForm(request.POST, operator=operator_instance)  # 👈 Again, pass it for POST too

        try:
            vehicle = fleet.objects.get(id=request.POST.get('tracking_vehicle'))
            route_obj = route.objects.get(id=request.POST.get('tracking_route'))
        except (fleet.DoesNotExist, route.DoesNotExist):
            return JsonResponse({"success": False, "error": "Vehicle or route not found."}, status=404)

        if form.is_valid():
            trip = Trip.objects.create(
                trip_vehicle=vehicle,
                trip_route=route_obj,
                trip_start_location=form.cleaned_data.get('tracking_start_location'),
                trip_end_location=form.cleaned_data.get('tracking_end_location'),
                trip_start_at=form.cleaned_data.get('tracking_start_at'),
            )
            form.instance.tracking_trip = trip
            form.save()

            return redirect('update-tracking-template', tracking_id=form.instance.tracking_id)
        else:
            return JsonResponse({"success": False, "errors": form.errors, "data": form.data}, status=400)

    return render(request, 'create.html', {'form': form})

def end_trip(request, tracking_id):
    try:
        tracking = Tracking.objects.get(tracking_id=tracking_id)
        tracking.trip_ended = True
        tracking.save()
        return redirect('vehicle_detail', operator_slug=tracking.tracking_vehicle.operator, vehicle_id=tracking.tracking_vehicle.id)
    except Tracking.DoesNotExist:
        return JsonResponse({"success": False, "error": "Tracking ID not found"}, status=404)

class map_view(generics.ListAPIView):
    serializer_class = trackingDataSerializer
    permission_classes = [ReadOnly]

    def get_queryset(self):
        tracking_game = self.kwargs.get('game_id')
        tracking_id = self.kwargs.get('tracking_id')
        if tracking_id:
            return Tracking.objects.filter(tracking_id=tracking_id)
        if tracking_game:
            return Tracking.objects.filter(game_id=tracking_game, trip_ended=False)
        return Tracking.objects.filter(trip_ended=False)

class map_view_history(generics.ListAPIView):
    serializer_class = trackingDataSerializer
    permission_classes = [ReadOnly]

    def get_queryset(self):
        tracking_game = self.kwargs.get('game_id')
        tracking_id = self.kwargs.get('tracking_id')
        if tracking_id:
            return Tracking.objects.filter(tracking_id=tracking_id)
        if tracking_game:
            return Tracking.objects.filter(game_id=tracking_game)
        return Tracking.objects.all()

class current_vehicle_trips(generics.ListAPIView):
    serializer_class = TripSerializer
    permission_classes = [ReadOnly]
    def get_queryset(self):
        current_time = timezone.now()
        print(f"[DEBUG] current_vehicle_trips: current_time = {current_time}")
        queryset = Trip.objects.filter(
            trip_start_at__lte=current_time,
            trip_end_at__gte=current_time
        )
        print(f"[DEBUG] current_vehicle_trips: found {queryset.count()} trips")
        return queryset
    
import math
def calculate_heading(lat1, lng1, lat2, lng2):
    """
    Returns heading in degrees (0–360),
    where 0 = North, 90 = East, 180 = South, 270 = West.
    """
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    d_lng = math.radians(lng2 - lng1)

    x = math.sin(d_lng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lng)

    heading = math.degrees(math.atan2(x, y))
    heading = (heading + 360) % 360
    return heading
    
def get_route_coordinates(route_id, trip_end_location):
    print(f"[DEBUG] get_route_coordinates_for_trip: route_id={route_id}, trip_end_location='{trip_end_location}'")

    stops_qs = routeStop.objects.filter(route_id=route_id).order_by("id")
    print(f"[DEBUG] found {stops_qs.count()} routeStop rows")

    if not stops_qs:
        print("[DEBUG] no routeStops found → returning []")
        return []

    direction_candidates = []

    for rs in stops_qs:
        print(f"[DEBUG] processing routeStop id={rs.id}")

        coords = []
        last_stop_name = None

        if not rs.stops or not isinstance(rs.stops, list):
            print(f"[DEBUG] routeStop {rs.id} has invalid stops field")
            continue

        for i, stop in enumerate(rs.stops):
            if not isinstance(stop, dict):
                print(f"[DEBUG] skipping non-dict stop at index {i} in routeStop {rs.id}")
                continue

            # Try to extract stop name
            sname = stop.get("stop") or stop.get("name") or stop.get("title")
            if sname:
                last_stop_name = sname

            # cords: "lat,lng"
            cords = stop.get("cords") or stop.get("coords")
            if cords:
                try:
                    lat_str, lng_str = cords.split(",")
                    coords.append((float(lat_str.strip()), float(lng_str.strip())))
                    continue
                except Exception as e:
                    print(f"[DEBUG] failed to parse cords '{cords}' in routeStop {rs.id}: {e}")

            # lat/lng fields
            lat = stop.get("lat") or stop.get("latitude")
            lng = stop.get("lng") or stop.get("longitude") or stop.get("long")
            if lat is not None and lng is not None:
                try:
                    coords.append((float(lat), float(lng)))
                    continue
                except Exception as e:
                    print(f"[DEBUG] failed parsing lat/lng in routeStop {rs.id}: {e}")

        print(f"[DEBUG] routeStop {rs.id} → extracted {len(coords)} coords, last_stop='{last_stop_name}'")

        if coords:
            direction_candidates.append({
                "coords": coords,
                "last_stop": last_stop_name
            })
        else:
            print(f"[DEBUG] routeStop {rs.id} had NO valid coords → skipping")

    # NEW SAFETY CHECK — prevents IndexError
    if not direction_candidates:
        print("[DEBUG] No valid routeStops produced coords → returning []")
        return []

    # Try matching by trip_end_location
    trip_end_location = (trip_end_location or "").lower().strip()

    for d in direction_candidates:
        ls = (d["last_stop"] or "").lower().strip()
        if trip_end_location and ls and trip_end_location in ls:
            print(f"[DEBUG] MATCH FOUND: using direction with last_stop '{d['last_stop']}'")
            return d["coords"]

    print("[DEBUG] NO MATCH FOUND → using default (first routeStop)")
    return direction_candidates[0]["coords"]

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


class VehicleDetailSerializer(serializers.Serializer):
    url = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()
    livery = serializers.SerializerMethodField()
    colour = serializers.SerializerMethodField()
    text_colour = serializers.SerializerMethodField()
    white_text = serializers.SerializerMethodField()
    left_css = serializers.SerializerMethodField()
    right_css = serializers.SerializerMethodField()
    stroke_colour = serializers.SerializerMethodField()

    def _get_vehicle_obj(self, obj):
        # Convert int → vehicle instance AND cache so we don't hit DB multiple times
        if isinstance(obj, int):
            if not hasattr(self, "_vehicle_cache"):
                self._vehicle_cache = {}
            if obj not in self._vehicle_cache:
                self._vehicle_cache[obj] = fleet.objects.select_related("operator", "livery").get(id=obj)
            return self._vehicle_cache[obj]

        return obj

    def get_url(self, obj):
        obj = self._get_vehicle_obj(obj)
        return f"/operator/{obj.operator.operator_slug}/vehicles/{obj.id}/"

    def get_name(self, obj):
        obj = self._get_vehicle_obj(obj)
        if obj.fleet_number:
            return f"{obj.fleet_number} - {obj.reg}"
        return obj.reg or "Unknown Vehicle"

    def get_features(self, obj):
        obj = self._get_vehicle_obj(obj)
        if not obj.features:
            return ""
        if isinstance(obj.features, list):
            return "<br>".join(obj.features)
        return str(obj.features)

    def get_livery(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.id if obj.livery else None

    def get_colour(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.colour if obj.livery else (obj.colour or "#000000")

    def get_text_colour(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.text_colour if obj.livery else "#ffffff"

    def get_white_text(self, obj):
        return self.get_text_colour(obj).lower() in ["#fff", "#ffffff", "white"]

    def get_left_css(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.left_css if obj.livery else ""

    def get_right_css(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.right_css if obj.livery else ""

    def get_stroke_colour(self, obj):
        obj = self._get_vehicle_obj(obj)
        return obj.livery.stroke_colour if obj.livery else ""
    
class ServiceDetailSerializer(serializers.Serializer):
    url = serializers.SerializerMethodField()
    line_name = serializers.SerializerMethodField()

    def _get_route(self, service_id):
        return route.objects.filter(id=service_id).first()

    def get_url(self, service_id):
        r = self._get_route(service_id)
        if not r:
            return None

        op = r.route_operators.first()
        if not op:
            return None

        return f"/operator/{op.operator_slug}/route/{r.id}/"
    
    def get_line_name(self, service_id):
        r = self._get_route(service_id)
        return r.route_num if r else "Unknown Service"

class EstimatedPositionSerializer(serializers.Serializer):
    trip_id = serializers.IntegerField()
    vehicle = VehicleDetailSerializer()
    service_id = serializers.IntegerField()
    service = ServiceDetailSerializer()
    progress = serializers.FloatField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    destination = serializers.CharField()
    heading = serializers.FloatField()

class VehiclePositionAPIView(generics.ListAPIView):
    serializer_class = EstimatedPositionSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        now = timezone.now()
        print(f"[DEBUG] VehiclePositionAPIView: now = {now}")

        # -------------------------------
        # NEW: read filters from query params
        # -------------------------------
        filter_route_id = self.request.query_params.get("route_id")
        filter_operator_id = self.request.query_params.get("operator_id")

        if filter_route_id:
            print(f"[DEBUG] filtering by route_id={filter_route_id}")

        if filter_operator_id:
            print(f"[DEBUG] filtering by operator_id={filter_operator_id}")

        # -------------------------------
        # Base queryset
        # -------------------------------
        trips = Trip.objects.filter(
            trip_start_at__lte=now,
            trip_end_at__gte=now,
            trip_ended=False
        )

        # -------------------------------
        # Apply route filter
        # -------------------------------
        if filter_route_id:
            trips = trips.filter(trip_route_id=filter_route_id)

        # -------------------------------
        # Apply operator filter
        # -------------------------------
        if filter_operator_id:
            trips = trips.filter(
                trip_vehicle__operator_id=filter_operator_id
            )

        print(f"[DEBUG] VehiclePositionAPIView: filtered active trips = {trips.count()}")

        # -------------------------------
        # Existing bounding box code
        # -------------------------------
        min_lat = self.request.query_params.get("ymin")
        max_lat = self.request.query_params.get("ymax")
        min_lng = self.request.query_params.get("xmin")
        max_lng = self.request.query_params.get("xmax")

        print(f"[DEBUG] VehiclePositionAPIView: bounding box = min_lat={min_lat}, max_lat={max_lat}, min_lng={min_lng}, max_lng={max_lng}")

        results = []

        # -------------------------------
        # PROCESS TRIPS
        # -------------------------------
        for trip in trips:
            print(f"[DEBUG] VehiclePositionAPIView: processing trip_id={trip.pk}")

            coords = get_route_coordinates(
                trip.trip_route_id,
                trip.trip_end_location or ""
            )

            progress = get_progress(trip)
            lat, lng, seg_index = interpolate(coords, progress)

            if lat is None or lng is None:
                continue

            # compute heading
            heading = None
            if seg_index < len(coords) - 1:
                next_lat, next_lng = coords[seg_index + 1]
                heading = calculate_heading(lat, lng, next_lat, next_lng)

            # bbox skip
            if min_lat and lat < float(min_lat): continue
            if max_lat and lat > float(max_lat): continue
            if min_lng and lng < float(min_lng): continue
            if max_lng and lng > float(max_lng): continue

            results.append({
                "trip_id": trip.pk,
                "vehicle": trip.trip_vehicle_id,
                "service_id": trip.trip_route_id,
                "service": trip.trip_route_id,
                "progress": round(progress, 4),
                "lat": lat,
                "lng": lng,
                "heading": heading,
                "destination": trip.trip_end_location or ""
            })

        print(f"[DEBUG] VehiclePositionAPIView: returning {len(results)} results")
        return results