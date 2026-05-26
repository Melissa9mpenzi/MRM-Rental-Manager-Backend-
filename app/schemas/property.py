from pydantic import BaseModel, field_validator
from typing import Optional, List
from decimal import Decimal
from datetime import datetime


# ── UNIT SCHEMAS ──────────────────────────────────────────────────

class UnitCreate(BaseModel):
    unit_number:  str
    floor_number: Optional[int] = 0
    unit_type:    Optional[str] = "one_bedroom"
    listing_category: Optional[str] = None
    bedrooms:     Optional[int] = None
    bathrooms:    Optional[int] = 1
    area_sqm:     Optional[Decimal] = None
    rent_amount:  Decimal
    status:       Optional[str] = "vacant"  # vacant | occupied | maintenance
    amenities:    Optional[List[str]] = []
    description:  Optional[str] = None

    @field_validator("rent_amount")
    @classmethod
    def rent_positive(cls, v):
        if v <= 0:
            raise ValueError("Rent amount must be greater than zero")
        return v

    @field_validator("unit_number")
    @classmethod
    def unit_number_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Unit number is required")
        return v.strip()


class UnitUpdate(BaseModel):
    unit_number:  Optional[str] = None
    floor_number: Optional[int] = None
    unit_type:    Optional[str] = None
    listing_category: Optional[str] = None
    bedrooms:     Optional[int] = None
    bathrooms:    Optional[int] = None
    area_sqm:     Optional[Decimal] = None
    rent_amount:  Optional[Decimal] = None
    amenities:    Optional[List[str]] = None
    description:  Optional[str] = None


class UnitStatusUpdate(BaseModel):
    status: str


class UnitOut(BaseModel):
    id:           int
    property_id:  int
    unit_number:  str
    floor_number: int
    unit_type:    str
    listing_category: Optional[str] = None
    bedrooms:     Optional[int] = None
    bathrooms:    Optional[int] = None
    area_sqm:     Optional[Decimal] = None
    rent_amount:  Decimal
    status:       str
    amenities:    Optional[List[str]] = []
    description:  Optional[str] = None
    created_at:   Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── PROPERTY SCHEMAS ──────────────────────────────────────────────

class PropertyCreate(BaseModel):
    name:        str
    address:     str
    parish:      Optional[str] = None
    district:    Optional[str] = "Kampala"
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Property name is required")
        return v.strip()

    @field_validator("address")
    @classmethod
    def address_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Address is required")
        return v.strip()


class PropertyUpdate(BaseModel):
    name:        Optional[str] = None
    address:     Optional[str] = None
    parish:      Optional[str] = None
    district:    Optional[str] = None
    description: Optional[str] = None
    photo_path:  Optional[str] = None
    video_path:  Optional[str] = None


class PropertyOut(BaseModel):
    id:                    int
    owner_id:              int
    name:                  str
    address:               str
    parish:                Optional[str] = None
    district:              Optional[str] = None
    description:           Optional[str] = None
    photo_path:            Optional[str] = None
    video_path:            Optional[str] = None
    is_active:             bool
    gov_verification_status: str = "pending"
    total_units:           int
    occupied_units:        int
    vacant_units:          int
    maintenance_units:     int
    occupancy_rate:        float
    expected_monthly_rent: Decimal
    created_at:            Optional[datetime] = None
    units:                 List[UnitOut] = []

    model_config = {"from_attributes": True}


class PropertySummary(BaseModel):
    id:                    int
    name:                  str
    address:               str
    parish:                Optional[str] = None
    district:              Optional[str] = None
    photo_path:            Optional[str] = None
    video_path:            Optional[str] = None
    is_active:             bool
    gov_verification_status: str = "pending"
    total_units:           int
    occupied_units:        int
    vacant_units:          int
    maintenance_units:     int
    occupancy_rate:        float
    expected_monthly_rent: Decimal
    created_at:            Optional[datetime] = None

    model_config = {"from_attributes": True}