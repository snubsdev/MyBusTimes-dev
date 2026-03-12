from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.dateparse import parse_date


PAGE_SIZE = 100
ACTION_LABELS = {
    ADDITION: 'add',
    CHANGE: 'change',
    DELETION: 'delete',
}


class Command(BaseCommand):
    help = (
        'Show Django admin log entries with optional user and model filters. '
        'Results are paginated at 100 logs per page.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Filter by user ID, username, or email.',
        )
        parser.add_argument(
            '--model',
            type=str,
            help='Filter by model name or app_label.model.',
        )
        parser.add_argument(
            '--page',
            type=int,
            default=1,
            help='Page number to return. Each page contains 100 logs.',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Filter by action date in YYYY-MM-DD format.',
        )

    def handle(self, *args, **options):
        page = options['page']
        if page < 1:
            raise CommandError('--page must be greater than or equal to 1.')

        queryset = LogEntry.objects.select_related('user', 'content_type').order_by('-action_time')

        if options.get('user'):
            user = self.get_user(options['user'])
            queryset = queryset.filter(user=user)

        if options.get('model'):
            content_type = self.get_content_type(options['model'])
            queryset = queryset.filter(content_type=content_type)

        if options.get('date'):
            action_date = self.parse_action_date(options['date'])
            queryset = queryset.filter(action_time__date=action_date)

        total_logs = queryset.count()
        total_pages = max((total_logs + PAGE_SIZE - 1) // PAGE_SIZE, 1)

        if total_logs == 0:
            self.stdout.write('No admin logs found for the supplied filters.')
            return

        if page > total_pages:
            raise CommandError(
                f'--page {page} is out of range. There are {total_pages} page(s) available.'
            )

        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        entries = queryset[start:end]

        self.stdout.write(
            f'Showing page {page}/{total_pages} '
            f'({len(entries)} of {total_logs} matching log entries)'
        )
        self.stdout.write('-' * 120)

        for entry in entries:
            action_label = ACTION_LABELS.get(entry.action_flag, str(entry.action_flag))
            content_type_label = self.format_content_type(entry.content_type)
            change_message = entry.change_message or '-'
            object_repr = entry.object_repr or '-'

            self.stdout.write(
                f'{entry.action_time:%Y-%m-%d %H:%M:%S} | '
                f'user={entry.user} | '
                f'model={content_type_label} | '
                f'action={action_label}'
            )
            self.stdout.write(f'object={object_repr}')
            self.stdout.write(f'change={change_message}')
            self.stdout.write('-' * 120)

    def get_user(self, value):
        user_model = get_user_model()
        queryset = user_model.objects.all()

        filters = Q(username__iexact=value) | Q(email__iexact=value)
        if value.isdigit():
            filters |= Q(pk=int(value))

        matches = list(queryset.filter(filters).order_by('pk')[:2])

        if not matches:
            raise CommandError(f'No user matched "{value}".')

        if len(matches) > 1:
            raise CommandError(
                f'"{value}" matched multiple users. Use the numeric user ID to disambiguate.'
            )

        return matches[0]

    def get_content_type(self, value):
        base_queryset = ContentType.objects.filter(logentry__isnull=False).distinct()

        if '.' in value:
            app_label, model_name = value.split('.', 1)
            content_types = list(
                base_queryset.filter(app_label=app_label, model=model_name.lower())[:2]
            )
        else:
            content_types = list(base_queryset.filter(model=value.lower())[:2])

        if not content_types:
            raise CommandError(
                f'No logged model matched "{value}". Use app_label.model if needed.'
            )

        if len(content_types) > 1:
            matches = ', '.join(
                f'{content_type.app_label}.{content_type.model}' for content_type in content_types
            )
            raise CommandError(
                f'"{value}" matched multiple models: {matches}. Use app_label.model.'
            )

        return content_types[0]

    def format_content_type(self, content_type):
        if not content_type:
            return '-'

        return f'{content_type.app_label}.{content_type.model}'

    def parse_action_date(self, value):
        action_date = parse_date(value)
        if action_date is None:
            raise CommandError('--date must be a valid date in YYYY-MM-DD format.')

        return action_date