from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage
import os

class Command(BaseCommand):
    help = "Upload the entire MEDIA_ROOT folder to your S3-compatible storage"

    def handle(self, *args, **options):
        media_root = settings.MEDIA_ROOT

        if not os.path.isdir(media_root):
            self.stdout.write(self.style.ERROR("MEDIA_ROOT does not exist."))
            return

        self.stdout.write(self.style.SUCCESS(f"Uploading media from: {media_root}"))

        for root, dirs, files in os.walk(media_root):
            for file in files:
                local_path = os.path.join(root, file)

                # Relative path inside the bucket
                relative_path = os.path.relpath(local_path, media_root)

                self.stdout.write(f"Uploading {relative_path}...")

                with open(local_path, "rb") as f:
                    default_storage.save(relative_path, f)

        self.stdout.write(self.style.SUCCESS("All media files uploaded successfully!"))
