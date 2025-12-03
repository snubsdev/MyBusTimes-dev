from django.core.management.base import BaseCommand
from fleet.models import fleet
from fleet.models import MBTOperator
from django.conf import settings

import requests
from datetime import datetime


def send_service_to_discord(count):
    embed = {
        "title": "🚗 Deduplicated UC",
        "description": f"**Deleted {count} Vehicles**",
        "color": 0x0000FF,  # DeepSkyBlue
        "fields": [
            {
                "name": "🕒 Time",
                "value": datetime.now().strftime('%Y-%m-%d %H:%M'),
                "inline": True
            }
        ],
        "footer": {
            "text": "UC Fleet Report Manager"
        },
        "timestamp": datetime.utcnow().isoformat()
    }

    payload = {
        "channel_id": 1445566402957283378,
        "content": "<@281084640440090627>",
        "embeds": [embed]
    }

    response = requests.post(
        f"{settings.DISCORD_BOT_API_URL}/send-embed",
        json=payload
    )

    try:
        response.raise_for_status()
    except Exception as e:
        print(f"Discord notification failed: {e}")


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
        removed = deduplicate_queryset(queryset)

        # Send embed to Discord
        send_service_to_discord(removed)

        self.stdout.write(
            self.style.SUCCESS(f"Removed {removed} duplicate vehicles for UC.")
        )
