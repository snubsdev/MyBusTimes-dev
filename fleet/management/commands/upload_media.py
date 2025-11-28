from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files.storage import default_storage
from django.contrib.staticfiles.storage import staticfiles_storage
import os


class Command(BaseCommand):
    help = "Upload folders to S3-compatible storage.\n\n" \
           "Usage:\n" \
           "  python manage.py upload static <folder>\n" \
           "  python manage.py upload media <folder>"

    def add_arguments(self, parser):
        parser.add_argument("type", choices=["static", "media"], help="Type of upload")
        parser.add_argument("folder", help="Folder to upload")

    def upload_folder(self, folder_path, storage, label):
        if not os.path.isdir(folder_path):
            self.stdout.write(self.style.ERROR(f"{folder_path} does not exist."))
            return

        self.stdout.write(self.style.SUCCESS(f"\nUploading {label} from: {folder_path}\n"))

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, folder_path)

                self.stdout.write(f"Uploading {label}: {relative_path}...")

                with open(local_path, "rb") as f:
                    storage.save(relative_path, f)

    def handle(self, *args, **options):
        upload_type = options["type"]
        folder = options["folder"]

        if upload_type == "media":
            storage = default_storage
            label = "MEDIA"
        else:
            storage = staticfiles_storage
            label = "STATIC"

        self.upload_folder(folder, storage, label)

        self.stdout.write(self.style.SUCCESS(f"\n{label} upload completed!"))
