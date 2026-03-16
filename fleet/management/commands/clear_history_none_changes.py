from django.apps import apps
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Clear noisy simple-history records for a selected model. "
        "Model must be app_label.ModelName. "
        "If the history model has a changes field: remove rows where changes is NULL. "
        "Otherwise: remove no-op update rows (history_type='~' with no actual data change)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "model",
            type=str,
            help="Target model in app_label.ModelName format (example: main.CustomUser)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without deleting anything",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=1000,
            help="Rows per scan query (default: 1000)",
        )
        parser.add_argument(
            "--delete-batch-size",
            type=int,
            default=1000,
            help="IDs per delete query (default: 1000)",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=50000,
            help="Print progress every N scanned rows (default: 50000)",
        )

    def handle(self, *args, **options):
        model_label = options["model"]
        dry_run = options["dry_run"]
        chunk_size = max(1, options["chunk_size"])
        delete_batch_size = max(1, options["delete_batch_size"])
        progress_every = max(1, options["progress_every"])

        model = self._get_model(model_label)
        history_model = self._get_history_model(model, model_label)

        history_fields = {field.name for field in history_model._meta.fields}
        item_name = model_label

        if "changes" in history_fields:
            self._clear_changes_null_mode(
                history_model=history_model,
                item_name=item_name,
                dry_run=dry_run,
                chunk_size=chunk_size,
                delete_batch_size=delete_batch_size,
                progress_every=progress_every,
            )
            return

        self._clear_noop_updates_mode(
            model=model,
            history_model=history_model,
            item_name=item_name,
            dry_run=dry_run,
            chunk_size=chunk_size,
            delete_batch_size=delete_batch_size,
            progress_every=progress_every,
        )

    def _clear_changes_null_mode(
        self,
        history_model,
        item_name,
        dry_run,
        chunk_size,
        delete_batch_size,
        progress_every,
    ):
        mode = "changes=NULL"
        history_pk_name = history_model._meta.pk.name

        self.stdout.write(f"Started clearing logs on {item_name} ({mode}).")

        scanned = 0
        matched = 0
        deleted = 0
        pending_delete_ids = []
        last_history_pk = None

        while True:
            batch_qs = history_model.objects.order_by(history_pk_name)
            if last_history_pk is not None:
                batch_qs = batch_qs.filter(**{f"{history_pk_name}__gt": last_history_pk})

            rows = list(batch_qs.values_list(history_pk_name, "changes")[:chunk_size])
            if not rows:
                break

            for history_pk, changes in rows:
                scanned += 1
                last_history_pk = history_pk

                if changes is None:
                    matched += 1
                    if not dry_run:
                        pending_delete_ids.append(history_pk)

                if scanned % progress_every == 0:
                    self.stdout.write(
                        f"Scanned {scanned} history rows for {item_name}; "
                        f"matched {matched} so far."
                    )

                if not dry_run and len(pending_delete_ids) >= delete_batch_size:
                    deleted += self._delete_ids_chunk(
                        history_model=history_model,
                        history_pk_name=history_pk_name,
                        delete_ids=pending_delete_ids,
                    )
                    pending_delete_ids = []

            if not dry_run and pending_delete_ids:
                deleted += self._delete_ids_chunk(
                    history_model=history_model,
                    history_pk_name=history_pk_name,
                    delete_ids=pending_delete_ids,
                )
                pending_delete_ids = []

        self.stdout.write(f"Finished scanning {scanned} history rows for {item_name}.")
        self.stdout.write(f"Found {matched} matching logs on {item_name}.")

        if matched == 0:
            self.stdout.write(self.style.SUCCESS(f"No matching {mode} history records found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would remove {matched} items from {item_name}."))
            return

        self.stdout.write(f"Removing {matched} items from {item_name}...")
        self.stdout.write(self.style.SUCCESS(f"Removed {deleted} items from {item_name}."))

    def _clear_noop_updates_mode(
        self,
        model,
        history_model,
        item_name,
        dry_run,
        chunk_size,
        delete_batch_size,
        progress_every,
    ):
        mode = "no-op updates"
        history_pk_name = history_model._meta.pk.name
        tracked_pk_name = model._meta.pk.attname

        self.stdout.write(f"Started clearing logs on {item_name} ({mode}).")

        ignored_fields = {
            history_pk_name,
            "history_id",
            "history_date",
            "history_change_reason",
            "history_type",
            "history_user",
            "history_user_id",
            tracked_pk_name,
        }

        value_field_names = [
            field.attname
            for field in history_model._meta.fields
            if field.attname not in ignored_fields and field.name not in ignored_fields
        ]

        scanned = 0
        matched = 0
        deleted = 0
        pending_delete_ids = []

        last_snapshot_by_object_id = {}
        last_history_pk = None
        fields = [history_pk_name, tracked_pk_name, "history_type", *value_field_names]

        while True:
            batch_qs = history_model.objects.order_by(history_pk_name)
            if last_history_pk is not None:
                batch_qs = batch_qs.filter(**{f"{history_pk_name}__gt": last_history_pk})

            rows = list(batch_qs.values_list(*fields)[:chunk_size])
            if not rows:
                break

            for row in rows:
                scanned += 1
                history_pk = row[0]
                object_id = row[1]
                history_type = row[2]
                snapshot = tuple(row[3:])
                previous_snapshot = last_snapshot_by_object_id.get(object_id)

                if history_type == "~" and previous_snapshot is not None and snapshot == previous_snapshot:
                    matched += 1
                    if not dry_run:
                        pending_delete_ids.append(history_pk)

                last_snapshot_by_object_id[object_id] = snapshot
                last_history_pk = history_pk

                if scanned % progress_every == 0:
                    self.stdout.write(
                        f"Scanned {scanned} history rows for {item_name}; "
                        f"matched {matched} so far."
                    )

                if not dry_run and len(pending_delete_ids) >= delete_batch_size:
                    deleted += self._delete_ids_chunk(
                        history_model=history_model,
                        history_pk_name=history_pk_name,
                        delete_ids=pending_delete_ids,
                    )
                    pending_delete_ids = []

            if not dry_run and pending_delete_ids:
                deleted += self._delete_ids_chunk(
                    history_model=history_model,
                    history_pk_name=history_pk_name,
                    delete_ids=pending_delete_ids,
                )
                pending_delete_ids = []

        self.stdout.write(f"Finished scanning {scanned} history rows for {item_name}.")
        self.stdout.write(f"Found {matched} matching logs on {item_name}.")

        if matched == 0:
            self.stdout.write(self.style.SUCCESS(f"No matching {mode} history records found."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would remove {matched} items from {item_name}."))
            return

        self.stdout.write(f"Removing {matched} items from {item_name}...")
        self.stdout.write(self.style.SUCCESS(f"Removed {deleted} items from {item_name}."))

    def _delete_ids_chunk(self, history_model, history_pk_name, delete_ids):
        deleted_count, _ = history_model.objects.filter(**{f"{history_pk_name}__in": delete_ids}).delete()
        return deleted_count

    def _get_model(self, model_label):
        try:
            model = apps.get_model(model_label)
        except (LookupError, ValueError) as exc:
            raise CommandError(
                "Invalid model. Use app_label.ModelName, for example: main.CustomUser"
            ) from exc

        if model is None:
            raise CommandError(f"Could not find model '{model_label}'.")

        return model

    def _get_history_model(self, model, model_label):
        history_descriptor = getattr(model, "history", None)
        history_model = getattr(history_descriptor, "model", None)

        if history_model is None:
            raise CommandError(
                f"Model '{model_label}' is not tracked by django-simple-history."
            )

        return history_model