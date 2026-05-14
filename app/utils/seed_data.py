"""
Optional database seeding for local development and manual QA.

Creates sample users, properties, and related rows. **Not** part of production deploy:
run `python -m app.utils.init_db` for schema only, then create real accounts via your app.
"""
from datetime import datetime, timedelta, date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.property import Property, Unit, UnitStatus, UnitType
from app.models.tenant import Tenant, TenantStatus
from app.models.lease import Lease, LeaseStatus
from app.models.payment import Payment, PaymentMethod, PaymentType
from app.models.maintenance import MaintenanceRequest
from app.services.auth_service import auth_service


def seed_database():
    """Seed database with comprehensive test data."""
    db = SessionLocal()
    
    try:
        print("🌱 Starting database seeding...")
        
        # Create users (landlords and admin)
        users = create_users(db)
        
        # Create properties
        properties = create_properties(db, users)
        
        # Create units for each property
        units = create_units(db, properties)
        
        # Create tenants
        tenants = create_tenants(db, users, units)
        
        # Create payments
        create_payments(db, tenants, units)
        
        # Create maintenance requests
        create_maintenance_requests(db, units, users)
        
        db.commit()
        print("✅ Database seeding completed successfully!")
        print(f"   - {len(users)} users created")
        print(f"   - {len(properties)} properties created")
        print(f"   - {len(units)} units created")
        print(f"   - {len(tenants)} tenants created")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding database: {e}")
        raise
    finally:
        db.close()


def create_users(db: Session):
    """Create test users with different roles."""
    users = []
    
    user_data = [
        {
            "email": "admin@rentalmgr.com",
            "full_name": "System Administrator",
            "phone": "+256 700 111 111",
            "role": UserRole.admin,
            "password": "admin12"
        },
        {
            "email": "landlord1@gmail.com",
            "full_name": "John Mukasa",
            "phone": "+256 700 222 222",
            "role": UserRole.landlord,
            "password": "land12"
        },
        {
            "email": "landlord2@gmail.com",
            "full_name": "Sarah Nambi",
            "phone": "+256 700 333 333",
            "role": UserRole.landlord,
            "password": "land12"
        },
        {
            "email": "melissasharon685@gmail.com",
            "full_name": "Melissa Sharon",
            "phone": "+256 700 444 444",
            "role": UserRole.landlord,
            "password": "pass12"
        }
    ]
    
    for data in user_data:
        # Check if user exists
        existing = db.query(User).filter(User.email == data["email"]).first()
        if existing:
            print(f"   User {data['email']} already exists, skipping...")
            users.append(existing)
            continue
        
        user = User(
            email=data["email"],
            full_name=data["full_name"],
            phone=data["phone"],
            role=data["role"],
            password_hash=auth_service.hash_password(data["password"]),
            email_verified=True,
            is_active=True
        )
        db.add(user)
        db.flush()
        users.append(user)
        print(f"   Created user: {user.full_name} ({user.role.value})")
    
    return users


def create_properties(db: Session, users):
    """Create sample properties."""
    properties = []
    
    # Get landlord users (not admin)
    landlords = [u for u in users if u.role == UserRole.landlord]
    
    property_data = [
        {
            "name": "Sunrise Apartments",
            "address": "Plot 45, Kampala Road, Nakasero",
            "parish": "Nakasero",
            "district": "Kampala",
            "description": "Modern apartment complex with 24/7 security, parking, and garden",
            "owner_idx": 0
        },
        {
            "name": "Green Valley Estate",
            "address": "Plot 12, Entebbe Road, Kajjansi",
            "parish": "Kajjansi",
            "district": "Wakiso",
            "description": "Spacious family homes in a quiet neighborhood near the airport",
            "owner_idx": 0
        },
        {
            "name": "City View Towers",
            "address": "Plot 89, Jinja Road, Bugolobi",
            "parish": "Bugolobi",
            "district": "Kampala",
            "description": "High-end apartments with city views, gym, and swimming pool",
            "owner_idx": 1
        },
        {
            "name": "Nalya Residential Complex",
            "address": "Plot 23, Nalya Road, Najjera",
            "parish": "Najjera",
            "district": "Wakiso",
            "description": "Affordable housing with good access to public transport",
            "owner_idx": 2
        }
    ]
    
    for i, data in enumerate(property_data):
        existing = db.query(Property).filter(Property.name == data["name"]).first()
        if existing:
            print(f"   Property {data['name']} already exists, skipping...")
            properties.append(existing)
            continue
        
        prop = Property(
            name=data["name"],
            address=data["address"],
            parish=data["parish"],
            district=data["district"],
            description=data["description"],
            owner_id=landlords[data["owner_idx"]].id,
            is_active=True
        )
        db.add(prop)
        db.flush()
        properties.append(prop)
        print(f"   Created property: {prop.name}")
    
    return properties


def create_units(db: Session, properties):
    """Create units for each property."""
    units = []
    
    unit_configs = [
        # Sunrise Apartments
        {"prop_idx": 0, "count": 8, "types": [UnitType.one_bedroom, UnitType.two_bedroom], "rent_range": (500000, 800000)},
        # Green Valley Estate
        {"prop_idx": 1, "count": 6, "types": [UnitType.two_bedroom, UnitType.three_bedroom], "rent_range": (900000, 1500000)},
        # City View Towers
        {"prop_idx": 2, "count": 12, "types": [UnitType.one_bedroom, UnitType.two_bedroom, UnitType.studio], "rent_range": (1200000, 2500000)},
        # Nalya Residential
        {"prop_idx": 3, "count": 10, "types": [UnitType.bedsitter, UnitType.one_bedroom], "rent_range": (300000, 600000)},
    ]
    
    for config in unit_configs:
        prop = properties[config["prop_idx"]]
        
        for i in range(config["count"]):
            unit_type = config["types"][i % len(config["types"])]
            floor = (i // 4) + 1  # 4 units per floor
            
            # Calculate rent based on unit type
            base_rent = config["rent_range"][0]
            max_rent = config["rent_range"][1]
            rent = base_rent + ((max_rent - base_rent) // config["count"]) * i
            
            unit_number = f"{floor}0{(i % 4) + 1}"
            
            unit = Unit(
                property_id=prop.id,
                unit_number=unit_number,
                floor_number=floor,
                unit_type=unit_type,
                rent_amount=Decimal(rent),
                status=UnitStatus.vacant,
                amenities={"water": True, "electricity": True, "wifi": unit_type != UnitType.bedsitter},
                description=f"Clean {unit_type.value.replace('_', ' ')} unit with good lighting"
            )
            db.add(unit)
            db.flush()
            units.append(unit)
        
        print(f"   Created {config['count']} units for {prop.name}")
    
    return units


def create_tenants(db: Session, users, units):
    """Create tenants and assign them to units."""
    tenants = []
    
    # Get vacant units
    vacant_units = [u for u in units if u.status == UnitStatus.vacant]
    
    # Get landlords
    landlords = [u for u in users if u.role == UserRole.landlord]
    
    tenant_names = [
        ("Robert Okello", "+256 711 111 111", "robert.okello@email.com"),
        ("Grace Auma", "+256 722 222 222", "grace.auma@email.com"),
        ("Peter Mugisha", "+256 733 333 333", "peter.mugisha@email.com"),
        ("Mary Namara", "+256 744 444 444", "mary.namara@email.com"),
        ("James Otim", "+256 755 555 555", "james.otim@email.com"),
        ("Alice Akello", "+256 766 666 666", "alice.akello@email.com"),
        ("David Opio", "+256 777 777 777", "david.opio@email.com"),
        ("Patricia Laker", "+256 788 888 888", "patricia.laker@email.com"),
        ("Henry Kalule", "+256 799 999 999", "henry.kalule@email.com"),
        ("Jane Nalwoga", "+256 700 000 001", "jane.nalwoga@email.com"),
    ]
    
    lease_start_date = date(2024, 1, 1)
    
    for i, (name, phone, email) in enumerate(tenant_names):
        if i >= len(vacant_units):
            break
        
        unit = vacant_units[i]
        landlord = landlords[i % len(landlords)]
        
        # Determine lease dates
        start_date = lease_start_date + timedelta(days=i * 10)
        end_date = start_date + timedelta(days=365)  # 1 year lease
        
        tenant = Tenant(
            owner_id=landlord.id,
            user_id=None,
            full_name=name,
            phone=phone,
            email=email,
            national_id=f"CM{i+10000000}PE",
            emergency_contact_name=f"Emergency Contact {i+1}",
            emergency_contact_phone=f"+256 71{i} 000 000",
            status=TenantStatus.active,
        )
        db.add(tenant)
        db.flush()

        lease = Lease(
            tenant_id=tenant.id,
            unit_id=unit.id,
            owner_id=landlord.id,
            start_date=start_date,
            end_date=end_date,
            monthly_rent=unit.rent_amount,
            deposit_amount=unit.rent_amount,
            deposit_paid=i % 3 != 0,
            status=LeaseStatus.active,
        )
        db.add(lease)
        db.flush()

        tenants.append(tenant)
        
        # Update unit status to occupied
        unit.status = UnitStatus.occupied
        
        print(f"   Created tenant: {name} in unit {unit.unit_number}")
    
    return tenants


def create_payments(db: Session, tenants, units):
    """Create payment records for tenants."""
    payments = []
    
    today = date.today()
    
    for tenant in tenants:
        lease = (
            db.query(Lease)
            .filter(Lease.tenant_id == tenant.id, Lease.status == LeaseStatus.active)
            .first()
        )
        if not lease:
            continue

        for month_offset in range(3, 0, -1):
            payment_date = today - timedelta(days=month_offset * 30)

            if month_offset == 1 and tenant.id % 10 == 0:
                continue

            payment = Payment(
                tenant_id=tenant.id,
                lease_id=lease.id,
                unit_id=lease.unit_id,
                owner_id=lease.owner_id,
                amount=lease.monthly_rent,
                payment_type=PaymentType.rent,
                payment_method=PaymentMethod.mtn_momo
                if payment_date.day % 2 == 0
                else PaymentMethod.cash,
                reference=f"TXN{tenant.id}{payment_date.strftime('%Y%m%d')}",
                period_month=payment_date.month,
                period_year=payment_date.year,
                payment_date=payment_date,
            )
            db.add(payment)
            payments.append(payment)
    
    print(f"   Created {len(payments)} payment records")
    return payments


def create_maintenance_requests(db: Session, units, users):
    """Create maintenance requests."""
    requests = []
    
    # Get occupied units
    occupied_units = db.query(Unit).filter(Unit.status == UnitStatus.occupied).all()
    
    # Sample maintenance issues
    issues = [
        ("Leaking faucet", "The kitchen sink tap is dripping water constantly", "medium"),
        ("Broken window", "Window glass cracked in bedroom", "high"),
        ("Paint peeling", "Wall paint coming off in the living room", "low"),
        ("AC not working", "Air conditioner blowing hot air", "high"),
        ("Door lock jammed", "Main door lock difficult to turn", "medium"),
    ]
    
    for i, unit in enumerate(occupied_units[:5]):  # Only for first 5 occupied units
        title, desc, priority = issues[i]
        
        maint = MaintenanceRequest(
            unit_id=unit.id,
            title=title,
            description=desc,
            priority=priority,
            status="open" if i % 2 == 0 else "in_progress",
            reported_by=None  # Tenant reported
        )
        db.add(maint)
        requests.append(maint)
    
    print(f"   Created {len(requests)} maintenance requests")
    return requests


if __name__ == "__main__":
    seed_database()
