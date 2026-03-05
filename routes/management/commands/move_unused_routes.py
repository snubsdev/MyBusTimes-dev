import requests
from django.core.management.base import BaseCommand
from routes.models import route
from fleet.models import MBTOperator


class Command(BaseCommand):
    help = "Move all routes with no operators into a selected operator"


    def add_arguments(self, parser):
        parser.add_argument('--code', help='The code of the operator to move the routes to')
        parser.add_argument('--dry-run', action='store_true', help='Show how many routes would be moved without actually moving them')

    def handle(self, *args, **kwargs):
        code = kwargs['code']
        dry_run = kwargs['dry_run']
        if not code and not dry_run:
            self.stdout.write(self.style.ERROR("Please provide an operator code using --code"))
            return

        try:
            operator = MBTOperator.objects.get(operator_code=code)
        except MBTOperator.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"No operator found with code '{code}'"))
            return

        # Find routes with no operators
        unused_routes = route.objects.filter(operators__isnull=True)
        count = unused_routes.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No unused routes found."))
            return

        # Move them to the selected operator

        if (not dry_run):
            for r in unused_routes:
                r.operators.add(operator)
            self.stdout.write(self.style.SUCCESS(f"Moved {count} unused routes to operator '{operator.operator_name}' (code: {operator.operator_code})."))
        else:
            self.stdout.write(self.style.SUCCESS(f"[DRY RUN] Would move {count} unused routes to operator '{operator.operator_name}' (code: {operator.operator_code})."))
        