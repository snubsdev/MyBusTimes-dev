import re
import requests
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from fleet.models import MBTOperator, fleet, liverie, vehicleType
from routes.models import route, routeStop, stop

User = get_user_model()


class Command(BaseCommand):
    help = 'Full BusTimes importer (fleet + routes + stops)'

    # ==============================
    # ARGUMENTS
    # ==============================
    def add_arguments(self, parser):
        parser.add_argument('--url', required=True)
        parser.add_argument('--owner', required=True)
        parser.add_argument('--import_into')
        parser.add_argument('--routes-only', action='store_true')
        parser.add_argument('--fleet-only', action='store_true')

    # ==============================
    # HELPERS
    # ==============================
    def format_reg(self, reg):
        if not reg:
            return reg
        reg = reg.replace(' ', '').upper()
        return f"{reg[:-3]} {reg[-3:]}" if len(reg) >= 4 else reg

    def parse_route_description(self, description):
        if not description:
            return None, None

        if ' - ' in description:
            a, b = description.split(' - ', 1)
            return a.strip(), b.strip()

        if ' to ' in description.lower():
            parts = re.split(r'\s+to\s+', description, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()

        return description, None

    def find_existing_stop(self, cache, name, lat, lon, tol=0.0005):
        for s in cache:
            if s.stop_name == name:
                if abs(s.latitude - lat) < tol and abs(s.longitude - lon) < tol:
                    return s
        return None

    # ==============================
    # VEHICLE HELPERS
    # ==============================
    def get_or_create_mbt_type(self, bt_type, owner):
        if not bt_type:
            return None

        name = bt_type.get('name')
        if not name:
            return None

        obj = vehicleType.objects.filter(type_name=name).first()
        if obj:
            return obj

        return vehicleType.objects.create(
            type_name=name,
            active=True,
            hidden=False,
            double_decker=bt_type.get('double_decker', False),
            type=bt_type.get('style', 'Bus') or 'Bus',
            fuel=(bt_type.get('fuel') or 'Diesel').capitalize(),
            added_by=owner,
        )

    def get_or_create_mbt_livery(self, bt_livery, owner):
        if not bt_livery:
            return None, ''

        name = bt_livery.get('name')
        left = bt_livery.get('left', '')
        right = bt_livery.get('right', '')

        if not name:
            return None, left or ''

        obj = liverie.objects.filter(
            name=name,
            left_css=left,
            right_css=right
        ).first()

        if obj:
            return obj, ''

        return liverie.objects.create(
            name=name,
            colour=bt_livery.get('colour') or '#FFFFFF',
            left_css=left,
            right_css=right,
            text_colour='black',
            published=False,
            added_by=owner
        ), ''

    # ==============================
    # ROUTE + STOP IMPORT
    # ==============================
    def import_routes(self, mbt_operator, operator_noc):
        self.stdout.write(self.style.SUCCESS("\n=== Importing Routes + Stops ==="))

        services_url = f"https://bustimes.org/api/services/?operator={operator_noc}"
        services = []

        while services_url:
            r = requests.get(services_url)
            r.raise_for_status()
            data = r.json()
            services += data.get('results', [])
            services_url = data.get('next')

        stop_cache = list(stop.objects.all())

        for s in services:
            line = s.get('line_name', '')
            desc = s.get('description', '')
            sid = s.get('id')

            inbound, outbound = self.parse_route_description(desc)

            route_obj, _ = route.objects.get_or_create(
                route_num=line,
                inbound_destination=inbound,
                outbound_destination=outbound,
            )
            route_obj.route_operators.add(mbt_operator)

            self.stdout.write(f"\nRoute {line}")

            # fetch journeys
            url = f"https://bustimes.org/api/journeys/?service={sid}"
            journeys = []

            while url:
                r = requests.get(url)
                r.raise_for_status()
                d = r.json()
                journeys += d.get('results', [])
                url = d.get('next')

            # group by direction
            grouped = {}
            for j in journeys:
                grouped.setdefault(j.get("direction", "outbound"), []).append(j)

            for direction, jlist in grouped.items():
                best = max(jlist, key=lambda j: len(j.get('stops') or []))
                stops_data = best.get('stops') or []

                stop_list = []

                for st in stops_data:
                    name = st.get('name')
                    lat = st.get('lat')
                    lon = st.get('lon')

                    if not name or lat is None or lon is None:
                        continue

                    obj = self.find_existing_stop(stop_cache, name, lat, lon)

                    if not obj:
                        obj = stop.objects.create(
                            stop_name=name,
                            latitude=lat,
                            longitude=lon,
                            source="bustimes"
                        )
                        stop_cache.append(obj)
                    else:
                        if obj.latitude != lat or obj.longitude != lon:
                            obj.latitude = lat
                            obj.longitude = lon
                            obj.save()

                    stop_list.append({
                        "id": obj.id,
                        "name": obj.stop_name,
                        "lat": obj.latitude,
                        "lon": obj.longitude
                    })

                inbound_flag = direction.lower() == "inbound"

                rs, created = routeStop.objects.get_or_create(
                    route=route_obj,
                    inbound=inbound_flag,
                    defaults={"stops": stop_list}
                )

                if not created and rs.stops != stop_list:
                    rs.stops = stop_list
                    rs.save()

    # ==============================
    # FLEET IMPORT
    # ==============================
    def import_fleet(self, mbt_operator, operator_noc, owner):
        self.stdout.write(self.style.SUCCESS("\n=== Importing Fleet ==="))

        url = f"https://bustimes.org/api/vehicles/?operator={operator_noc}"
        vehicles = []

        while url:
            r = requests.get(url)
            r.raise_for_status()
            d = r.json()
            vehicles += d.get('results', [])
            url = d.get('next')

        grouped = {}
        for v in vehicles:
            reg = v.get('reg')
            if reg:
                grouped.setdefault(reg, []).append(v)

        for reg, items in grouped.items():
            items.sort(key=lambda x: x.get('withdrawn', False))
            v = items[0]

            reg = self.format_reg(reg)

            vt = self.get_or_create_mbt_type(v.get('vehicle_type'), owner)
            lv, colour = self.get_or_create_mbt_livery(v.get('livery'), owner)

            obj, created = fleet.objects.get_or_create(
                operator=mbt_operator,
                reg=reg,
                defaults={
                    "fleet_number": v.get('fleet_code'),
                    "vehicleType": vt,
                    "livery": lv,
                    "colour": colour,
                    "in_service": not v.get('withdrawn', False),
                    "branding": v.get('branding'),
                    "name": v.get('name'),
                    "notes": v.get('notes'),
                    "features": v.get('special_features') or [],
                    "last_modified_by": owner,
                }
            )

            if not created:
                if not obj.in_service and not v.get('withdrawn'):
                    obj.in_service = True
                    obj.save()

    # ==============================
    # MAIN
    # ==============================
    def handle(self, *args, **opts):
        url = opts['url']
        owner = User.objects.get(username=opts['owner'])

        slug = re.search(r'/operators/([^/]+)', url).group(1)

        data = requests.get(f"https://bustimes.org/api/operators/?slug={slug}").json()['results'][0]

        mbt_operator, _ = MBTOperator.objects.get_or_create(
            operator_code=data['noc'],
            defaults={
                "operator_name": data.get('name'),
                "operator_slug": slug,
                "owner": owner
            }
        )

        if not opts.get('routes_only'):
            self.import_fleet(mbt_operator, data['noc'], owner)

        if not opts.get('fleet_only'):
            self.import_routes(mbt_operator, data['noc'])
