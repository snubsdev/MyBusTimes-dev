from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage
from django.contrib.staticfiles.storage import staticfiles_storage
import os


class Command(BaseCommand):
    help = "Upload MEDIA_ROOT and STATIC_ROOT folders to S3-compatible storage."

    def upload_folder(self, root_path, storage, label):
        if not os.path.isdir(root_path):
            self.stdout.write(self.style.WARNING(f"{label} does not exist — skipping."))
            return

        self.stdout.write(self.style.SUCCESS(f"\nUploading {label} from: {root_path}\n"))

        for root, dirs, files in os.walk(root_path):
            for file in files:
                local_path = os.path.join(root, file)

                relative_path = os.path.relpath(local_path, root_path)

                self.stdout.write(f"Uploading {label}: {relative_path}...")

                with open(local_path, "rb") as f:
                    storage.save(relative_path, f)

    def handle(self, *args, **options):
        # --- Upload media ---
        self.upload_folder(
            settings.MEDIA_ROOT,
            default_storage,
            "MEDIA",
        )

        # --- Upload static ---
        static_root = settings.STATIC_ROOT
        self.upload_folder(
            static_root,
            staticfiles_storage,
            "STATIC",
        )

        self.stdout.write(self.style.SUCCESS("\nAll media and static files uploaded successfully!"))
