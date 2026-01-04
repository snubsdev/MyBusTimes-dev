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

    def get_plan_history(self, user):
        """Get the user's subscription plan history from Simple History"""
        history = user.history.all().order_by('history_date')
        plans = []
        for record in history:
            if record.sub_plan and record.sub_plan not in [p[0] for p in plans]:
                plans.append((record.sub_plan, record.history_date))
        return plans

    def had_basic_before_pro(self, user):
        """Check if user had basic plan before pro plan"""
        history = user.history.all().order_by('history_date')
        had_basic = False
        for record in history:
            if record.sub_plan == 'basic':
                had_basic = True
            elif record.sub_plan == 'pro' and had_basic:
                return True
        return False

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
            
            # Determine subscription details
            stripe_sub_id = None
            start_date = timezone.now()
            end_date = user.ad_free_until
            plan = user.sub_plan if user.sub_plan != 'free' else 'basic'
            is_trial = False

            # Check history for plan progression (basic -> pro)
            had_basic = self.had_basic_before_pro(user)
            if had_basic and plan == 'pro':
                self.stdout.write(f'    📊 {user.username} upgraded from basic to pro')

            if stripe_sub:
                stripe_sub_id = stripe_sub.subscription_id
                # Convert DateField to datetime
                if stripe_sub.start_date:
                    start_date = timezone.make_aware(
                        datetime.combine(stripe_sub.start_date, time.min)
                    )
                if stripe_sub.end_date:
                    end_date = timezone.make_aware(
                        datetime.combine(stripe_sub.end_date, time.min)
                    )

            # Check if this is a trial:
            # 1. No stripe subscription but has ad_free_until and had_pro_trial flag
            # 2. OR subscription duration is 7 days or less (trial max is 1 week)
            if not stripe_sub and user.ad_free_until and user.had_pro_trial:
                is_trial = True
            elif start_date and end_date:
                # Check if duration is <= 7 days (trial)
                if isinstance(end_date, datetime):
                    duration = end_date - start_date
                    if duration <= timedelta(days=7):
                        is_trial = True

            # Use user's join_date as start if no better option
            if not stripe_sub and user.join_date:
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
