from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    Numeric, Text, Enum, ForeignKey, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class UnitType(str, enum.Enum):
    bedsitter     = "bedsitter"
    one_bedroom   = "one_bedroom"
    two_bedroom   = "two_bedroom"
    three_bedroom = "three_bedroom"
    studio        = "studio"
    shop          = "shop"
    office        = "office"
    other         = "other"


class UnitStatus(str, enum.Enum):
    vacant      = "vacant"
    occupied    = "occupied"
    maintenance = "maintenance"


class Property(Base):
    __tablename__ = "properties"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    address     = Column(Text, nullable=False)
    parish      = Column(String(100), nullable=True)
    district    = Column(String(100), default="Kampala")
    description = Column(Text, nullable=True)
    photo_path  = Column(String(500), nullable=True)
    is_active   = Column(Boolean, default=True)
    # KCCA / government property verification: none | pending | verified | rejected | inspection | illegal
    gov_verification_status = Column(String(24), nullable=False, default="pending")
    gov_walrus_blob_id = Column(String(256), nullable=True)
    gov_packet_hash = Column(String(64), nullable=True)
    created_at  = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at  = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", backref="properties")
    units = relationship("Unit", back_populates="parent_property", cascade="all, delete-orphan")

    @property
    def total_units(self):
        return len(self.units)

    @property
    def occupied_units(self):
        return sum(1 for u in self.units if u.status == UnitStatus.occupied)

    @property
    def vacant_units(self):
        return sum(1 for u in self.units if u.status == UnitStatus.vacant)

    @property
    def maintenance_units(self):
        return sum(1 for u in self.units if u.status == UnitStatus.maintenance)

    @property
    def occupancy_rate(self):
        if not self.units:
            return 0.0
        return round((self.occupied_units / len(self.units)) * 100, 1)

    @property
    def expected_monthly_rent(self):
        return sum(float(u.rent_amount or 0) for u in self.units if u.status == UnitStatus.occupied)


class Unit(Base):
    __tablename__ = "units"

    id           = Column(Integer, primary_key=True, index=True)
    property_id  = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_number  = Column(String(50), nullable=False)
    floor_number = Column(Integer, default=0)
    unit_type    = Column(Enum(UnitType), default=UnitType.one_bedroom)
    rent_amount  = Column(Numeric(12, 2), nullable=False)
    status       = Column(Enum(UnitStatus), default=UnitStatus.vacant)
    amenities         = Column(JSON, nullable=True)
    listing_category  = Column(String(64), nullable=True, index=True)
    bedrooms          = Column(Integer, nullable=True)
    bathrooms         = Column(Integer, nullable=True, default=1)
    area_sqm          = Column(Numeric(10, 2), nullable=True)
    description  = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=func.now(), server_default=func.now())
    updated_at   = Column(DateTime, default=func.now(), server_default=func.now(), onupdate=func.now())

    parent_property = relationship("Property", back_populates="units")
    leases   = relationship("Lease", back_populates="unit")

    __table_args__ = (
        UniqueConstraint("property_id", "unit_number", name="uq_unit_in_property"),
    )

    @property
    def current_lease(self):
        """Get the active lease for this unit, if any."""
        from app.models.lease import LeaseStatus
        for lease in self.leases:
            if lease.status == LeaseStatus.active:
                return lease
        return None

    @property
    def current_tenant(self):
        """Get the tenant from the current active lease."""
        lease = self.current_lease
        return lease.tenant if lease else None