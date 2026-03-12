from django.core.management.base import BaseCommand, CommandError

from fleet.models import fleet


HISTORY_TYPE_LABELS = {
    '+': 'create',
    '~': 'update',
    '-': 'delete',
}


class Command(BaseCommand):
    help = 'Show fleet simple-history entries for vehicles matching a specific fleet number.'

    def add_arguments(self, parser):
        parser.add_argument(
            'fleet_number',
            nargs='?',
            type=str,
            help='Fleet number to search for.',
        )
        parser.add_argument(
            '--fleet-number',
            '--fleet_number',
            dest='fleet_number_flag',
            type=str,
            help='Fleet number to search for.',
        )

    def handle(self, *args, **options):
        fleet_number = self.resolve_fleet_number(
            options.get('fleet_number'),
            options.get('fleet_number_flag'),
        )
        if not fleet_number:
            raise CommandError('fleet_number is required.')

        historical_fleet_model = fleet.history.model

        current_vehicle_ids = set(
            fleet.objects.filter(fleet_number__iexact=fleet_number).values_list('id', flat=True)
        )
        historical_vehicle_ids = set(
            historical_fleet_model.objects.filter(fleet_number__iexact=fleet_number)
            .values_list('id', flat=True)
            .distinct()
        )
        vehicle_ids = sorted(current_vehicle_ids | historical_vehicle_ids)

        if not vehicle_ids:
            self.stdout.write(f'No fleet history found for fleet number "{fleet_number}".')
            return

        history_entries = historical_fleet_model.objects.filter(id__in=vehicle_ids).order_by(
            'id', 'history_date', 'history_id'
        )

        self.stdout.write(
            f'Found {len(vehicle_ids)} vehicle(s) with current or historical fleet number '
            f'"{fleet_number}".'
        )

        last_vehicle_id = None
        for entry in history_entries:
            if entry.id != last_vehicle_id:
                current_vehicle = fleet.objects.filter(id=entry.id).only(
                    'id', 'fleet_number', 'reg'
                ).first()
                current_label = self.format_current_vehicle(current_vehicle, entry)
                self.stdout.write('')
                self.stdout.write(f'Vehicle {entry.id}: {current_label}')
                self.stdout.write('=' * 120)
                last_vehicle_id = entry.id

            history_user = getattr(entry, 'history_user', None)
            history_user_label = history_user.username if history_user else '-'
            history_type = HISTORY_TYPE_LABELS.get(entry.history_type, entry.history_type)
            change_reason = entry.history_change_reason or '-'
            delta = self.describe_delta(entry)

            self.stdout.write(
                f'{entry.history_date:%Y-%m-%d %H:%M:%S} | '
                f'action={history_type} | '
                f'fleet_number={entry.fleet_number or "-"} | '
                f'reg={entry.reg or "-"} | '
                f'user={history_user_label}'
            )
            self.stdout.write(f'changes={delta}')
            self.stdout.write(f'reason={change_reason}')
            self.stdout.write('-' * 120)

    def resolve_fleet_number(self, positional_value, flagged_value):
        positional_value = (positional_value or '').strip()
        flagged_value = (flagged_value or '').strip()

        if positional_value and flagged_value and positional_value != flagged_value:
            raise CommandError(
                'Provide the fleet number either positionally or with --fleet-number, not both.'
            )

        return flagged_value or positional_value

    def format_current_vehicle(self, current_vehicle, history_entry):
        if current_vehicle is None:
            return f'{history_entry.fleet_number or "-"} / {history_entry.reg or "-"} (not currently present)'

        return f'{current_vehicle.fleet_number or "-"} / {current_vehicle.reg or "-"}'

    def describe_delta(self, entry):
        if entry.history_type != '~':
            return '-'

        previous_record = entry.prev_record
        if previous_record is None:
            return '-'

        try:
            delta = entry.diff_against(previous_record)
        except Exception:
            return '-'

        if not delta.changes:
            return '-'

        parts = []
        for change in delta.changes:
            old_value = self.format_value(change.old)
            new_value = self.format_value(change.new)
            parts.append(f'{change.field}: {old_value} -> {new_value}')

        return '; '.join(parts)

    def format_value(self, value):
        if value in (None, ''):
            return '-'

        text = str(value).replace('\n', ' ')
        if len(text) > 80:
            return f'{text[:77]}...'

        return text