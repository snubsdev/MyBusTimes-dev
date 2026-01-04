from datetime import datetime, time, timedelta
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from main.models import CustomUser, ActiveSubscription, StripeSubscription


class Command(BaseCommand):
    help = 'Migrate existing users with ad_free_until or sub_plan to ActiveSubscription model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating records',
        )

    def get_plan_periods(self, user):
        """
        Get distinct plan periods from user history.
        Returns list of (plan, start_date, end_date) tuples.
        """
        history = user.history.all().order_by('history_date')
        periods = []
        current_plan = None
        current_start = None
        
        for record in history:
            plan = record.sub_plan
            if plan and plan != 'free' and plan != current_plan:
                # End previous period if exists
                if current_plan and current_start:
                    periods.append((current_plan, current_start, record.history_date))
                # Start new period
                current_plan = plan
                current_start = record.history_date
        
        # Add final period (still active)
        if current_plan and current_start:
            periods.append((current_plan, current_start, None))  # None = ongoing
        
        return periods

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No records will be created\n'))

        # Get all users with either ad_free_until set OR sub_plan not 'free'
        users = CustomUser.objects.filter(
            Q(ad_free_until__isnull=False) | ~Q(sub_plan='free')
        ).distinct()

        created_count = 0
        skipped_count = 0

        self.stdout.write(f'Found {users.count()} users with subscriptions to migrate\n')

        for user in users:
            # Check if user already has an ActiveSubscription
            existing = ActiveSubscription.objects.filter(user=user).exists()
            if existing:
                self.stdout.write(f'  ⏭ Skipping {user.username} - already has ActiveSubscription')
                skipped_count += 1
                continue

            # Get any StripeSubscription for this user
            stripe_sub = StripeSubscription.objects.filter(user=user).order_by('-id').first()
            stripe_sub_id = stripe_sub.subscription_id if stripe_sub else None

            # Get plan periods from history
            plan_periods = self.get_plan_periods(user)
            
            if plan_periods:
                # Create ActiveSubscription for each plan period
                self.stdout.write(f'  📊 {user.username} has {len(plan_periods)} plan period(s)')
                
                for i, (plan, start_date, end_date) in enumerate(plan_periods):
                    is_last = (i == len(plan_periods) - 1)
                    
                    # Only attach stripe_sub_id to the current/last subscription
                    sub_stripe_id = stripe_sub_id if is_last else None
                    
                    # Use ad_free_until as end_date for the last period if not set
                    if is_last and end_date is None:
                        end_date = user.ad_free_until
                    
                    self.stdout.write(
                        f'    {"[DRY]" if dry_run else "✓"} {plan}: '
                        f'{start_date.strftime("%Y-%m-%d")} to {end_date.strftime("%Y-%m-%d") if end_date else "ongoing"}'
                        f'{" (stripe: " + sub_stripe_id + ")" if sub_stripe_id else ""}'
                    )
                    
                    if not dry_run:
                        ActiveSubscription.objects.create(
                            user=user,
                            stripe_subscription_id=sub_stripe_id,
                            start_date=start_date,
                            end_date=end_date,
                            plan=plan,
                            is_trial=False  # Not a trial if they paid
                        )
                    
                    created_count += 1
            else:
                # No history, create single subscription based on current state
                start_date = timezone.now()
                end_date = user.ad_free_until
                plan = user.sub_plan if user.sub_plan != 'free' else 'basic'
                
                # Only way to get trial is had_pro_trial flag
                is_trial = user.had_pro_trial and not stripe_sub
                
                if stripe_sub:
                    # Convert DateField to datetime
                    if stripe_sub.start_date:
                        start_date = timezone.make_aware(
                            datetime.combine(stripe_sub.start_date, time.min)
                        )
                    if stripe_sub.end_date:
                        end_date = timezone.make_aware(
                            datetime.combine(stripe_sub.end_date, time.min)
                        )
                elif user.join_date:
                    # Use user's join_date as start if no stripe data
                    start_date = user.join_date

                self.stdout.write(
                    f'  {"[DRY]" if dry_run else "✓"} {user.username}: '
                    f'plan={plan}, end={end_date}, stripe_id={stripe_sub_id}, trial={is_trial}'
                )

                if not dry_run:
                    ActiveSubscription.objects.create(
                        user=user,
                        stripe_subscription_id=stripe_sub_id,
                        start_date=start_date,
                        end_date=end_date,
                        plan=plan,
                        is_trial=is_trial
                    )
                
                created_count += 1

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS(f'Created: {created_count} ActiveSubscription records'))
        self.stdout.write(self.style.WARNING(f'Skipped: {skipped_count} (already had ActiveSubscription)'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nThis was a dry run. Run without --dry-run to create records.'))
