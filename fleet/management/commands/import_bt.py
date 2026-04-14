import re
import requests
from urllib.parse import quote_plus
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from fleet.models import MBTOperator, fleet, liverie, vehicleType
from routes.models import route

User = get_user_model()

class Command(BaseCommand):
	help = 'Import vehicle data from bustimes.org API'

	def add_arguments(self, parser):
		parser.add_argument('--url', help='URL to search for (e.g. https://bustimes.org/operators/midland-classic/vehicles)')
		parser.add_argument('--owner', help='Username of the owner for the new operator', required=True)
		parser.add_argument('--import_into', help='Operator code of an existing MBT operator to import vehicles and routes into (skips creating new operator)')
		parser.add_argument('--routes-only', action='store_true', help='Only import routes/services, skip vehicles')
		parser.add_argument('--fleet-only', action='store_true', help='Only import fleet/vehicles, skip routes')

	def format_reg(self, reg):
		"""Format registration plate with space before last 3 characters (e.g., WN74XVJ -> WN74 XVJ)"""
		if not reg:
			return reg
		# Remove any existing spaces and uppercase
		reg = reg.replace(' ', '').upper()
		# Insert space before last 3 characters if reg is long enough
		if len(reg) >= 4:
			return f"{reg[:-3]} {reg[-3:]}"
		return reg

	def get_or_create_mbt_type(self, bt_type, owner):
		"""Match BusTimes vehicle type to MBT type by exact name, or create if not found"""
		if not bt_type:
			return None
		
		type_name = bt_type.get('name')
		if not type_name:
			return None
		
		# Use filter().first() to handle potential duplicates
		existing_type = vehicleType.objects.filter(type_name=type_name).first()
		if existing_type:
			return existing_type
		
		# Create new type from BusTimes data
		new_type = vehicleType.objects.create(
			type_name=type_name,
			active=True,
			hidden=False,
			double_decker=bt_type.get('double_decker', False),
			type=bt_type.get('style', 'Bus') or 'Bus',
			fuel=bt_type.get('fuel', 'Diesel').capitalize() if bt_type.get('fuel') else 'Diesel',
			added_by=owner,
		)
		self.stdout.write(self.style.SUCCESS(f"    Created new vehicle type: {type_name} (ID: {new_type.id})"))
		return new_type

	def get_or_create_mbt_livery(self, bt_livery, owner):
		"""Match BusTimes livery to MBT livery by exact name and CSS, or create if not found.
		Returns tuple (livery, colour) - if name is null, returns (None, left_css_colour)"""
		if not bt_livery:
			return None, ''
		
		bt_left = bt_livery.get('left', '')
		bt_right = bt_livery.get('right', '')
		livery_name = bt_livery.get('name', '')
		
		# If livery name is null/empty, return the left CSS as the colour instead
		if not livery_name:
			return None, bt_left or ''
		
		# Match by exact name AND exact CSS (left and right)
		existing_livery = liverie.objects.filter(
			name=livery_name,
			left_css=bt_left,
			right_css=bt_right
		).first()
		
		if existing_livery:
			return existing_livery, ''
		
		# Create new livery from BusTimes data
		new_livery = liverie.objects.create(
			name=livery_name,
			colour=bt_livery.get('colour', '#FFFFFF') or '#FFFFFF',
			left_css=bt_left,
			right_css=bt_right,
			text_colour='black',
			stroke_colour='',
			published=False,  # Needs approval
			added_by=owner,
		)
		self.stdout.write(self.style.SUCCESS(f"    Created new livery: {livery_name} (ID: {new_livery.id})"))
		return new_livery, ''

	def parse_route_description(self, description):
		"""Parse BusTimes description into inbound/outbound destinations"""
		if not description:
			return None, None
		
		# Common separators: " - ", " to ", " via "
		# Try splitting by " - " first
		if ' - ' in description:
			parts = description.split(' - ', 1)
			if len(parts) == 2:
				return parts[0].strip(), parts[1].strip()
		
		# Try " to "
		if ' to ' in description.lower():
			parts = re.split(r'\s+to\s+', description, maxsplit=1, flags=re.IGNORECASE)
			if len(parts) == 2:
				return parts[0].strip(), parts[1].strip()
		
		# No clear split, use description as route name
		return description, None

	def import_services(self, mbt_operator, operator_noc):
		"""Import services/routes from BusTimes API"""
		self.stdout.write(self.style.SUCCESS(f"\n=== Importing Services ==="))
		
		services_url = f"https://bustimes.org/api/services/?operator={operator_noc}"
		all_services = []
		page = 1
		
		while services_url:
			self.stdout.write(f"Fetching services page {page}: {services_url}")
			
			response = requests.get(services_url)
			response.raise_for_status()
			data = response.json()
			
			results = data.get('results', [])
			all_services.extend(results)
			
			services_url = data.get('next')
			page += 1
		
		self.stdout.write(self.style.SUCCESS(f"Total services fetched: {len(all_services)}"))
		
		created_routes = 0
		skipped_routes = 0
		
		for service in all_services:
			line_name = service.get('line_name', '')
			description = service.get('description', '')
			
			# Parse description into destinations
			inbound_dest, outbound_dest = self.parse_route_description(description)
			
			# Check if route already exists for this operator with same route number
			existing_route = route.objects.filter(
			    route_operators=mbt_operator,
			    inbound_destination=inbound_dest,
			    outbound_destination=outbound_dest,
			).first()
			
			if existing_route:
				self.stdout.write(f"  - SKIPPED (exists): {line_name} - {description}")
				skipped_routes += 1
				continue
			
			# Create new route
			new_route = route.objects.create(
				route_num=line_name,
				inbound_destination=inbound_dest,
				outbound_destination=outbound_dest,
			)
			# Add operator to the ManyToMany field
			new_route.route_operators.add(mbt_operator)
			
			self.stdout.write(self.style.SUCCESS(f"  - CREATED: {line_name} - {description}"))
			created_routes += 1
		
		self.stdout.write(self.style.SUCCESS(f"\n=== Services Import Complete ==="))
		self.stdout.write(self.style.SUCCESS(f"Routes created: {created_routes}"))
		self.stdout.write(f"Routes skipped (existing): {skipped_routes}")

	def handle(self, *args, **options):
		urlArg = options.get('url')
		owner_username = options.get('owner')
		import_into_code = options.get('import_into')
		routes_only = options.get('routes_only', False)
		fleet_only = options.get('fleet_only', False)
		
		if routes_only and fleet_only:
			raise CommandError("Cannot use both --routes-only and --fleet-only at the same time.")
		
		if not urlArg:
			raise CommandError("You must provide a --url argument.")
		
		if not owner_username:
			raise CommandError("You must provide an --owner argument.")
		
		# Get owner user
		try:
			owner = User.objects.get(username=owner_username)
		except User.DoesNotExist:
			raise CommandError(f"User '{owner_username}' not found.")
		
		self.stdout.write(self.style.SUCCESS(f"Owner: {owner.username}"))
		
		# Extract slug from URL like https://bustimes.org/operators/midland-classic/vehicles
		match = re.search(r'/operators/([^/]+)', urlArg)
		if not match:
			raise CommandError("Could not extract operator slug from URL. Expected format: https://bustimes.org/operators/<slug>/vehicles")
		
		slug = match.group(1)
		self.stdout.write(self.style.SUCCESS(f"Extracted slug: {slug}"))
		
		# Get operator info from API
		operator_url = f"https://bustimes.org/api/operators/?slug={slug}"
		self.stdout.write(f"Fetching operator data from: {operator_url}")
		
		response = requests.get(operator_url)
		response.raise_for_status()
		operator_data = response.json()
		
		if not operator_data.get('results'):
			raise CommandError(f"No operator found with slug: {slug}")
		
		bt_operator = operator_data['results'][0]
		operator_noc = bt_operator['noc']
		operator_name = bt_operator.get('name', 'Unknown')
		
		self.stdout.write(self.style.SUCCESS(f"Found operator: {operator_name} (NOC: {operator_noc})"))
		
		# If --import_into is provided, use existing MBT operator
		if import_into_code:
			try:
				mbt_operator = MBTOperator.objects.get(operator_code=import_into_code)
				self.stdout.write(self.style.SUCCESS(f"Importing into existing MBT Operator: {mbt_operator.operator_name} (ID: {mbt_operator.id}, Code: {import_into_code})"))
			except MBTOperator.DoesNotExist:
				raise CommandError(f"MBT Operator with code '{import_into_code}' not found.")
		else:
			# Create or get MBT Operator based on BusTimes NOC
			mbt_operator, created = MBTOperator.objects.get_or_create(
				operator_code=operator_noc,
				defaults={
					'operator_name': operator_name,
					'operator_slug': slug,
					'owner': owner,
					'operator_details': {
						'website': bt_operator.get('url', ''),
						'twitter': bt_operator.get('twitter', ''),
						'game': 'OMSI2',
						'type': 'real-company',
						'transit_authorities': '',
					}
				}
			)
			
			if created:
				self.stdout.write(self.style.SUCCESS(f"Created new MBT Operator: {mbt_operator.operator_name} (ID: {mbt_operator.id})"))
			else:
				self.stdout.write(self.style.WARNING(f"MBT Operator already exists: {mbt_operator.operator_name} (ID: {mbt_operator.id})"))
		
		# Import fleet/vehicles (skip if --routes-only)
		if not routes_only:
			# First pass: collect all vehicles and group by reg to handle duplicates
			all_vehicles = []
			vehicles_url = f"https://bustimes.org/api/vehicles/?operator={operator_noc}"
			page = 1
			
			while vehicles_url:
				self.stdout.write(f"Fetching page {page}: {vehicles_url}")
				
				response = requests.get(vehicles_url)
				response.raise_for_status()
				data = response.json()
				
				results = data.get('results', [])
				all_vehicles.extend(results)
				
				vehicles_url = data.get('next')
				page += 1
			
			self.stdout.write(self.style.SUCCESS(f"\nTotal vehicles fetched: {len(all_vehicles)}"))
			
			# Group vehicles by reg to find duplicates
			vehicles_by_reg = {}
			for vehicle in all_vehicles:
				reg = vehicle.get('reg', '')
				if reg:
					if reg not in vehicles_by_reg:
						vehicles_by_reg[reg] = []
					vehicles_by_reg[reg].append(vehicle)
			
			# Process vehicles, merging duplicates
			total_vehicles = 0
			created_vehicles = 0
			updated_vehicles = 0
			merged_vehicles = 0
			
			for reg, vehicles in vehicles_by_reg.items():
				# If there are duplicates, prefer the non-withdrawn one
				if len(vehicles) > 1:
					# Sort: non-withdrawn first
					vehicles.sort(key=lambda v: v.get('withdrawn', False))
					primary_vehicle = vehicles[0]
					self.stdout.write(self.style.WARNING(f"  - MERGED {len(vehicles)} duplicates for reg {reg}, using {'active' if not primary_vehicle.get('withdrawn') else 'withdrawn'} as primary"))
					merged_vehicles += len(vehicles) - 1
				else:
					primary_vehicle = vehicles[0]
				
				bt_type = primary_vehicle.get('vehicle_type', {})
				bt_type_name = bt_type.get('name', None) if bt_type else None
				bt_livery = primary_vehicle.get('livery', {})
				bt_livery_name = bt_livery.get('name', 'N/A') if bt_livery else 'N/A'
				
				fleet_code = primary_vehicle.get('fleet_code', '')
				withdrawn = primary_vehicle.get('withdrawn', False)
				branding = primary_vehicle.get('branding', '')
				name = primary_vehicle.get('name', '')
				notes = primary_vehicle.get('notes', '')
				special_features = sorted(primary_vehicle.get('special_features', []) or [])
				
				# Format registration plate
				reg = self.format_reg(reg)
				
				# Get or create MBT type
				mbt_type = self.get_or_create_mbt_type(bt_type, owner) if bt_type else None
				mbt_type_str = f"MBT Type ID: {mbt_type.id} ({mbt_type.type_name})" if mbt_type else "No type"
				
				# Get or create MBT livery (returns tuple of livery, colour)
				if bt_livery:
					mbt_livery, fallback_colour = self.get_or_create_mbt_livery(bt_livery, owner)
				else:
					mbt_livery, fallback_colour = None, ''
				mbt_livery_str = f"MBT Livery ID: {mbt_livery.id} ({mbt_livery.name})" if mbt_livery else "No livery"
				
				# Check if vehicle already exists (by reg and operator)
				existing_vehicle = fleet.objects.filter(
					operator=mbt_operator,
					reg=reg
				).first()
				
				if existing_vehicle:
					# Update existing vehicle if incoming is not withdrawn and existing is withdrawn
					if existing_vehicle.in_service == False and not withdrawn:
						existing_vehicle.in_service = True
						existing_vehicle.fleet_number = fleet_code or existing_vehicle.fleet_number
						existing_vehicle.livery = mbt_livery or existing_vehicle.livery
						existing_vehicle.vehicleType = mbt_type or existing_vehicle.vehicleType
						existing_vehicle.branding = branding or existing_vehicle.branding
						existing_vehicle.name = name or existing_vehicle.name
						existing_vehicle.notes = notes or existing_vehicle.notes
						existing_vehicle.features = special_features or existing_vehicle.features
						existing_vehicle.colour = fallback_colour or existing_vehicle.colour
						existing_vehicle.last_modified_by = owner
						existing_vehicle.save()
						self.stdout.write(self.style.SUCCESS(f"  - UPDATED (was withdrawn, now active): Fleet: {fleet_code}, Reg: {reg}"))
						updated_vehicles += 1
					else:
						self.stdout.write(f"  - SKIPPED (exists): Fleet: {fleet_code}, Reg: {reg}")
				else:
					# Create the fleet entry
					new_vehicle = fleet.objects.create(
						operator=mbt_operator,
						fleet_number=fleet_code,
						reg=reg,
						livery=mbt_livery,
						vehicleType=mbt_type,
						in_service=not withdrawn,
						branding=branding,
						name=name,
						notes=notes,
						last_modified_by=owner,
						features=special_features,
						colour=fallback_colour,
					)
					self.stdout.write(self.style.SUCCESS(f"  - CREATED: ID: {new_vehicle.id}, Fleet: {fleet_code}, Reg: {reg}"))
					self.stdout.write(f"    BT Type: {bt_type_name} -> {mbt_type_str}")
					self.stdout.write(f"    BT Livery: {bt_livery_name} -> {mbt_livery_str}")
					created_vehicles += 1
				
				total_vehicles += 1
			
			self.stdout.write(self.style.SUCCESS(f"\n=== Fleet Import Complete ==="))
			self.stdout.write(self.style.SUCCESS(f"Operator: {mbt_operator.operator_name} (ID: {mbt_operator.id})"))
			self.stdout.write(self.style.SUCCESS(f"Unique vehicles processed: {total_vehicles}"))
			self.stdout.write(self.style.SUCCESS(f"Vehicles created: {created_vehicles}"))
			self.stdout.write(self.style.SUCCESS(f"Vehicles updated: {updated_vehicles}"))
			self.stdout.write(self.style.WARNING(f"Duplicate entries merged: {merged_vehicles}"))
		
		# Import services/routes (skip if --fleet-only)
		if not fleet_only:
			self.import_services(mbt_operator, operator_noc)
