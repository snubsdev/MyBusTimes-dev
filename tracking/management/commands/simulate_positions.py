from django.core.management.base import BaseCommand
from django.utils import timezone
from tracking.models import Trip
from fleet.models import fleet

# Import your existing helper functions
from tracking.utils import (
    get_route_coordinates,
    get_progress,
    interpolate,
    calculate_heading,
)

class Command(BaseCommand):
    help = "Simulate vehicle positions for all active trips"

    def handle(self, *args, **kwargs):
        now = timezone.now()

        # ---------------------------------------------------------
        # 1. Get active trips (start <= now <= end)
        # ---------------------------------------------------------
        active_trips = (    
            Trip.objects
            .filter(trip_start_at__lte=now, trip_end_at__gte=now, trip_missed=False)
            .select_related("trip_vehicle", "trip_vehicle__operator")
        )

        if not active_trips.exists():
            self.stdout.write("No active trips found.")
            return
        
        # ---------------------------------------------------------
        # 2. Clear sim data for vehicles not on active trips
        # ---------------------------------------------------------
        fleet.objects.filter(
            current_trip__trip_end_at__lt=now - timezone.timedelta(minutes=15)
        ).update(
            sim_lat=None,
            sim_lon=None,
            sim_heading=None,
            current_trip=None,
            updated_at=None
        )

        self.stdout.write("Cleared old trip positions.")

        # ---------------------------------------------------------
        # 3. Update each active trip
        # ---------------------------------------------------------
        for trip in active_trips:

            print(f"Processing Trip {trip.pk}")

            vehicle = trip.trip_vehicle
            if not vehicle:
                continue

            # Load route shape
            coords = get_route_coordinates(trip.trip_route, trip)
            if not coords:
                continue

            # Compute progress (0..1)
            progress = get_progress(trip)

            if progress >= 1:
                lat, lng = coords[-1]  # last coordinate on route
                # heading = keep previous or set 0, but this is optional
                heading = vehicle.sim_heading or 0

                vehicle.sim_lat = lat
                vehicle.sim_lon = lng
                vehicle.sim_heading = heading
                vehicle.current_trip = trip
                vehicle.updated_at = now

                print(f"Vehicle {vehicle.pk} finalised at trip end location.")

                vehicle.save(update_fields=[
                    "sim_lat",
                    "sim_lon",
                    "sim_heading",
                    "current_trip",
                    "updated_at",
                ])

                continue

            # Interpolate coordinate
            lat, lng, seg_index = interpolate(coords, progress)

            # If we're at the last point, re-use previous point
            if seg_index >= len(coords) - 1:
                lat2, lng2 = coords[seg_index - 1]
            else:
                lat2, lng2 = coords[seg_index + 1]

            heading = calculate_heading(lat, lng, lat2, lng2)

            # Update vehicle
            vehicle.sim_lat = lat
            vehicle.sim_lon = lng
            vehicle.sim_heading = heading
            vehicle.current_trip = trip
            vehicle.updated_at = now

            print(f"Vehicle {vehicle.pk} updated: lat={lat}, lon={lng}, heading={heading}, trip={trip.pk}")

            vehicle.save(update_fields=[
                "sim_lat",
                "sim_lon",
                "sim_heading",
                "current_trip",
                "updated_at",
            ])

            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {vehicle} → lat={lat}, lon={lng}, heading={heading}"
                )
            )
