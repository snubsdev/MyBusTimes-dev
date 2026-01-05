from django.core.management.base import BaseCommand
from main.models import CustomUser


class Command(BaseCommand):
    help = 'Remove empty history records and records where only last_active changed from CustomUser history'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting records',
        )
        parser.add_argument(
            '--test',
            action='store_true',
            help='Limit to 1000 records for testing',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        test_mode = options['test']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No records will be deleted'))
        
        if test_mode:
            self.stdout.write(self.style.WARNING('TEST MODE - Limited to 1000 records'))
        
        # Get the historical model
        HistoricalCustomUser = CustomUser.history.model
        
        # Get all history records ordered by user and date
        all_history = HistoricalCustomUser.objects.all().order_by('id', 'history_date')
        
        if test_mode:
            all_history = all_history[:1000]
        
        records_to_delete = []
        
        # Fields to ignore when checking for changes
        ignore_fields = {'last_active', 'history_id', 'history_date', 'history_change_reason', 
                         'history_type', 'history_user_id', 'history_user'}
        
        # Get field names from the historical model (excluding ignored fields)
        # Use attname to get the actual DB column name (e.g., theme_id instead of theme)
        model_fields = [f.attname for f in HistoricalCustomUser._meta.fields 
                        if f.name not in ignore_fields and f.attname not in ignore_fields]
        
        self.stdout.write(f'Checking {all_history.count()} history records...')
        
        # Group records by the tracked object ID
        user_histories = {}
        for record in all_history:
            user_id = record.id
            if user_id not in user_histories:
                user_histories[user_id] = []
            user_histories[user_id].append(record)
        
        for user_id, history_records in user_histories.items():
            # Sort by history date
            history_records.sort(key=lambda x: x.history_date)
            
            prev_record = None
            for record in history_records:
                should_delete = False
                
                if record.history_type == '~':  # Changed record
                    if prev_record is not None:
                        # Check if any meaningful field changed
                        has_meaningful_change = False
                        
                        for field in model_fields:
                            old_value = getattr(prev_record, field, None)
                            new_value = getattr(record, field, None)
                            
                            if old_value != new_value:
                                has_meaningful_change = True
                                break
                        
                        if not has_meaningful_change:
                            should_delete = True
                            records_to_delete.append(record)
                            
                            if dry_run:
                                self.stdout.write(
                                    f'  Would delete: User {user_id} - {record.history_date} '
                                    f'(no meaningful changes)'
                                )
                
                if not should_delete:
                    prev_record = record
        
        self.stdout.write(f'\nFound {len(records_to_delete)} empty/last_active-only history records')
        
        if not dry_run and records_to_delete:
            # Delete the records
            delete_ids = [r.history_id for r in records_to_delete]
            deleted_count, _ = HistoricalCustomUser.objects.filter(history_id__in=delete_ids).delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_count} history records'))
        elif dry_run:
            self.stdout.write(self.style.WARNING(f'\nRun without --dry-run to delete these records'))
        else:
            self.stdout.write(self.style.SUCCESS('No records to delete'))
