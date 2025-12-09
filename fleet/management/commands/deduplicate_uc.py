from django.core.management.base import BaseCommand
from fleet.models import fleet, MBTOperator
from django.conf import settings
import requests
from datetime import datetime


def send_service_to_discord(removed, before_count, after_count):
    # Determine color based on number of deleted vehicles
    if removed <= 50:
        color = 0x00FF00  # Green
    elif removed <= 150:
        color = 0xFFA500  # Orange
    elif removed <= 300:
        color = 0xFF0000  # Red
    else:
        color = 0xFF69B4  # Pink

    embed = {
        "title": "🚗 UC Fleet Deduplication",
        "description": (
            f"**Before:** {before_count} vehicles\n"
            f"**After:** {after_count} vehicles\n"
            f"**Deleted:** {removed} duplicates"
        ),
        "color": color,
        "fields": [
            {
                "name": "🕒 Time",
                "value": datetime.now().strftime('%Y-%m-%d %H:%M'),
                "inline": True
            }
        ],
        "footer": {"text": "UC Fleet Report Manager"},
        "timestamp": datetime.utcnow().isoformat()
    }

    payload = {
        "channel_id": 1445566402957283378,             # Discord channel ID
        "content": "<@281084640440090627>",           # Mention user
        "allowed_mentions": {"users": [281084640440090627]},  # Allow ping
        "embed": embed
    }

    try:
        response = requests.post(f"{settings.DISCORD_BOT_API_URL}/send-embed", json=payload)
        response.raise_for_status()
        print("Discord embed sent successfully")
    except Exception as e:
        print(f"Discord notification failed: {e}")
        if response is not None:
            print("Response:", getattr(response, "text", ""))


def deduplicate_queryset(queryset):
    seen = {}
    duplicates = []

    for obj in queryset:
        key = (obj.reg.strip().upper(), obj.fleet_number.strip().upper())
        if key in seen:
            duplicates.append(obj)
        else:
            seen[key] = obj

    for dup in duplicates:
        dup.delete()

    return len(duplicates)


class Command(BaseCommand):
    help = "Deduplicates operator UC's fleet once per run"

    def handle(self, *args, **options):
        try:
            operator = MBTOperator.objects.get(operator_code="UC")
        except MBTOperator.DoesNotExist:
            self.stdout.write(self.style.ERROR("Operator UC not found"))
            return

        queryset = fleet.objects.filter(operator=operator)
        before_count = queryset.count()
        removed = deduplicate_queryset(queryset)
        after_count = fleet.objects.filter(operator=operator).count()

        # Send embed to Discord
        send_service_to_discord(removed, before_count, after_count)

        self.stdout.write(
            self.style.SUCCESS(
                f"UC dedupe complete — Before: {before_count}, After: {after_count}, Removed: {removed}"
            )
        )
