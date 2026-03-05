import requests
from django.core.management.base import BaseCommand
from routes.models import route, timetableEntry, routeStop
from fleet.models import MBTOperator


class Command(BaseCommand):
    help = "Move all routes with no operators into a selected operator"

    def add_arguments(self, parser):
        parser.add_argument('--code', help='The code of the operator to move the routes to')
        parser.add_argument('--dry-run', action='store_true', help='Show how many routes would be moved without actually moving them')
        parser.add_argument('--clean-up', action='store_true', help='Deletes any routes on the selected operator that have no timetable and no stops with coordinates')

    def handle(self, *args, **kwargs):
        code = kwargs['code']
        dry_run = kwargs['dry_run']
        clean_up = kwargs['clean_up']

        if not code and (not dry_run or clean_up):
            self.stdout.write(self.style.ERROR("Please provide an operator code using --code"))
            return

        if code:
            try:
                operator = MBTOperator.objects.get(operator_code=code)
            except MBTOperator.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"No operator found with code '{code}'"))
                return

        # Find routes with no operators
        unused_routes = route.objects.filter(route_operators__isnull=True)
        count = unused_routes.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No unused routes found."))
            return

        # Move them to the selected operator
        if not dry_run:
            for r in unused_routes:
                r.route_operators.add(operator)
            self.stdout.write(self.style.SUCCESS(f"Moved {count} unused routes to operator '{operator.operator_name}' (code: {operator.operator_code})."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would move {count} unused routes to operator 'DRY RUN' (code: DRY RUN)."))

        if clean_up:
            # Clean up
            self.stdout.write("Starting clean-up of routes with no timetable and no stops with coordinates...")
            routes_to_delete = []

            for r in route.objects.filter(route_operators=operator):
                self.stdout.write(f"Checking route {r.route_num} (ID: {r.id})...")
                has_timetable = timetableEntry.objects.filter(route=r).exists()
                has_stops_with_coordinates = routeStop.objects.filter(route=r, stops__contains='"cords":').exists()

                if not has_timetable and not has_stops_with_coordinates:
                    routes_to_delete.append(r.id)

            if routes_to_delete:
                if not dry_run:
                    deleted_count, _ = route.objects.filter(id__in=routes_to_delete).delete()
                    self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} routes with no timetable and no stops with coordinates."))
                else:
                    self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would delete {len(routes_to_delete)} routes with no timetable and no stops with coordinates."))
            else:
                self.stdout.write(self.style.SUCCESS("No routes found to clean up."))