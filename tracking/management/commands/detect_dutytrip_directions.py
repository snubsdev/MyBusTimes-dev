# yourapp/management/commands/detect_dutytrip_directions.py
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

import re
import json
from math import ceil

# Adjust these imports to match your app names if they're different
from routes.models import dutyTrip, route, routeStop

# ---------- Helpers ----------

def normalize_location(text):
    """
    Normalize free-text stop/destination names for fuzzy matching.
    - lowercases
    - removes punctuation
    - removes common noise words (stand, bay, platform, adjacent, opposite, near)
    - removes parenthetical content and numbers
    - collapses whitespace
    """
    if not text:
        return ""

    # ensure str
    text = str(text)

    # remove parenthetical content like "(Stand 1)"
    text = re.sub(r"\(.*?\)", " ", text)

    # lowercase
    text = text.lower()

    # remove punctuation except for spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # remove noise words and trailing numbers (stand, bay, platform, stop, adjacent, opposite, near)
    noise_pattern = r"\b(stand|bay|platform|stop|adjacent|opposite|near|outside|outside of|next to|by|at|opp|adj)\b"
    text = re.sub(noise_pattern, " ", text)

    # remove standalone numbers
    text = re.sub(r"\b\d+\b", " ", text)

    # collapse multiple spaces
    text = " ".join(text.split())

    return text


def token_overlap_match(a, b, min_common_tokens=1):
    """
    Returns True if tokens overlap enough to consider a match.
    Uses normalized token sets and requires either substring containment
    or at least min_common_tokens tokens in common or at least half of the smaller token set.
    """
    if not a or not b:
        return False

    a_n = normalize_location(a)
    b_n = normalize_location(b)

    if not a_n or not b_n:
        return False

    # substring check (quick high-confidence)
    if a_n in b_n or b_n in a_n:
        return True

    atoks = set(a_n.split())
    btoks = set(b_n.split())

    if not atoks or not btoks:
        return False

    common = atoks.intersection(btoks)
    # require at least 1 token in common and at least half of the smaller set
    threshold = max(min_common_tokens, ceil(min(len(atoks), len(btoks)) / 2))

    return len(common) >= threshold


def fuzzy_match(a, b):
    """
    Unified fuzzy match: combine normalization + token_overlap heuristics.
    """
    return token_overlap_match(a, b, min_common_tokens=1)


def extract_stop_names_from_stops_json(stops_json):
    """
    Given the routeStop.stops JSON (list of dicts), return the list of stop name strings.
    Defensive: accepts JSON string or Python list.
    """
    stops = []
    if not stops_json:
        return stops

    try:
        if isinstance(stops_json, str):
            data = json.loads(stops_json)
        else:
            data = stops_json

        if isinstance(data, list):
            for item in data:
                # item may be dict with key 'stop' or 'name' etc. try common keys
                if isinstance(item, dict):
                    name = item.get("stop") or item.get("name") or item.get("stop_name")
                    if name:
                        stops.append(str(name))
                else:
                    # if item is plain string
                    stops.append(str(item))
    except Exception:
        # fallback: try to coerce to string
        try:
            # crude fallback: find "stop":"..." occurrences
            text = json.dumps(stops_json)
            candidates = re.findall(r'"stop"\s*:\s*"([^"]+)"', text)
            stops.extend(candidates)
        except Exception:
            pass

    return stops


# ---------- Detection logic per dutyTrip ----------

def detect_direction_for_dutytrip(dt):
    """
    Returns:
      True  => inbound
      False => outbound
      None  => ambiguous / not found
    """

    # Skip if no route_link
    if not getattr(dt, "route_link", None):
        return None

    route_obj = dt.route_link

    start_text = dt.start_at or ""
    end_text = dt.end_at or ""

    # 1) Try matching against route destinations
    inbound_dest = route_obj.inbound_destination or ""
    outbound_dest = route_obj.outbound_destination or ""

    # If both start & end are present, check patterns:
    # inbound: starts near outbound_dest and ends near inbound_dest
    inbound_match = False
    outbound_match = False

    try:
        if start_text and end_text and outbound_dest and inbound_dest:
            inbound_match = (fuzzy_match(start_text, outbound_dest) and fuzzy_match(end_text, inbound_dest))
            outbound_match = (fuzzy_match(start_text, inbound_dest) and fuzzy_match(end_text, outbound_dest))

            if inbound_match and not outbound_match:
                return True
            if outbound_match and not inbound_match:
                return False
    except Exception:
        # ignore and continue to next step
        pass

    # 2) Try first and last stop of routeStop entries (inbound and outbound)
    # Fetch routeStop rows for this route; there may be two rows (inbound True/False)
    rstop_qs = routeStop.objects.filter(route=route_obj)

    # helper to get first/last stop names for inbound/outbound
    def first_last_stops_for(direction_bool):
        try:
            rs = rstop_qs.get(inbound=direction_bool)
        except routeStop.DoesNotExist:
            # try fallback: any routeStop with matching 'circular' values or first match
            try:
                rs = rstop_qs.filter(inbound=direction_bool).first()
            except Exception:
                rs = None

        if not rs:
            # try any routeStop for route with that inbound flag missing
            rs = rstop_qs.first()
            if not rs:
                return None, None

        stops = extract_stop_names_from_stops_json(rs.stops)
        if not stops:
            return None, None

        return stops[0], stops[-1]

    # inbound routeStop: inbound=True. For a trip that is inbound,
    # it commonly starts at outbound end (first or last depending on how stops are ordered).
    # We'll treat 'first' as the start-of-journey stop for that routeStop row.
    in_first, in_last = first_last_stops_for(True)
    out_first, out_last = first_last_stops_for(False)

    try:
        # Check whether duty start/end match first/last pair for inbound/outbound
        # We'll consider both (first->last) and (last->first) orderings to tolerate different list orders.
        def matches_first_last(start, end, first, last):
            if not first or not last:
                return False
            # match start ≈ first AND end ≈ last OR start ≈ last AND end ≈ first
            return ((fuzzy_match(start, first) and fuzzy_match(end, last)) or
                    (fuzzy_match(start, last) and fuzzy_match(end, first)))

        if matches_first_last(start_text, end_text, in_first, in_last) and not matches_first_last(start_text, end_text, out_first, out_last):
            return True
        if matches_first_last(start_text, end_text, out_first, out_last) and not matches_first_last(start_text, end_text, in_first, in_last):
            return False
    except Exception:
        pass

    # 3) If still not found: scan all stops for token matches.
    # Count how many matches the start and end texts have within inbound stops vs outbound stops,
    # and pick direction with higher combined matches.

    try:
        inbound_stops = []
        outbound_stops = []
        # collect stops lists from routeStop rows
        for rs in rstop_qs:
            names = extract_stop_names_from_stops_json(rs.stops)
            if rs.inbound:
                inbound_stops.extend(names)
            else:
                outbound_stops.extend(names)

        def count_matches_in_list(text, stop_list):
            if not text or not stop_list:
                return 0
            count = 0
            for s in stop_list:
                if fuzzy_match(text, s):
                    count += 1
            return count

        start_in_matches = count_matches_in_list(start_text, inbound_stops)
        end_in_matches = count_matches_in_list(end_text, inbound_stops)
        start_out_matches = count_matches_in_list(start_text, outbound_stops)
        end_out_matches = count_matches_in_list(end_text, outbound_stops)

        # choose the direction with higher total matches (start+end)
        inbound_total = start_in_matches + end_in_matches
        outbound_total = start_out_matches + end_out_matches

        if inbound_total > outbound_total:
            return True
        if outbound_total > inbound_total:
            return False

    except Exception:
        pass

    # if none of the above returned, ambiguous
    return None


# ---------- Command ----------

class Command(BaseCommand):
    help = "Detect direction (inbound/outbound) for dutyTrip rows and save into dutyTrip.direction"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of dutyTrips processed (useful for testing).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="How many rows to update per DB transaction.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-detection even if direction is already set.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        batch_size = options["batch_size"]
        force = options["force"]

        qs = dutyTrip.objects.all().order_by("id")
        total = qs.count()
        self.stdout.write(f"Found {total} dutyTrip rows total.")

        if limit:
            qs = qs[:limit]
            self.stdout.write(f"Limiting to first {limit} rows.")

        updated = 0
        ambiguous = 0
        skipped = 0
        failed = 0

        buffer = []
        processed = 0

        for dt in qs:
            processed += 1

            # skip if no route_link
            if not getattr(dt, "route_link", None):
                skipped += 1
                continue

            # if already set and not forcing, skip
            if getattr(dt, "direction", None) is not None and not force:
                continue

            try:
                detected = detect_direction_for_dutytrip(dt)
            except Exception as e:
                self.stderr.write(f"Error detecting for dutyTrip id={dt.id}: {e}")
                failed += 1
                continue

            if detected is None:
                ambiguous += 1
                # optionally write null / leave as-is. We'll set to None explicitly.
                try:
                    dt.direction = None
                    buffer.append(dt)
                except Exception:
                    pass
            else:
                dt.inbound = detected
                buffer.append(dt)
                updated += 1

            # batch save
            if len(buffer) >= batch_size:
                try:
                    with transaction.atomic():
                        for b in buffer:
                            # Save only the direction field if possible
                            try:
                                b.save(update_fields=["direction"])
                            except Exception:
                                b.save()
                        buffer = []
                except Exception as e:
                    self.stderr.write(f"Batch save failed: {e}")
                    failed += len(buffer)
                    buffer = []

        # final flush
        if buffer:
            try:
                with transaction.atomic():
                    for b in buffer:
                        try:
                            b.save(update_fields=["direction"])
                        except Exception:
                            b.save()
            except Exception as e:
                self.stderr.write(f"Final batch save failed: {e}")
                failed += len(buffer)

        self.stdout.write("---- Summary ----")
        self.stdout.write(f"Processed: {processed}")
        self.stdout.write(f"Updated  : {updated}")
        self.stdout.write(f"Ambiguous: {ambiguous}")
        self.stdout.write(f"Skipped  : {skipped} (no route_link)")
        self.stdout.write(f"Failed   : {failed}")
        self.stdout.write("Done.")
