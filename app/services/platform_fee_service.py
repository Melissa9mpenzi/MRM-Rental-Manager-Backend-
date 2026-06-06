"""Platform fee calculation and landlord balance ledger."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.config import settings
from app.models.landlord_ledger import LandlordLedgerEntry, LedgerEntryType
from app.models.payment import PaymentMethod
from app.models.property import Property, Unit, UnitStatus
from app.models.user import User

logger = logging.getLogger(__name__)

_ONLINE_METHODS = {
    PaymentMethod.mtn_momo.value,
    PaymentMethod.airtel.value,
    PaymentMethod.sui.value,
    PaymentMethod.pesapal.value,
    PaymentMethod.card.value,
    PaymentMethod.other.value,
}


def fee_config_public() -> dict:
    """Published fee table for landlords and marketing."""
    pct = float(settings.platform_rent_fee_percent or 0)
    flat = float(settings.platform_rent_fee_flat_ugx or 0)
    unit = float(settings.platform_unit_fee_monthly_ugx or 0)
    min_fee = float(settings.platform_rent_fee_min_ugx or 0)
    return {
        "currency": "UGX",
        "online_rent_fee_percent": pct,
        "online_rent_fee_flat_ugx": flat,
        "online_rent_fee_min_ugx": min_fee,
        "unit_fee_monthly_ugx": unit,
        "fee_on_manual_bank_recordings": False,
        "example": {
            "rent_ugx": 3_000_000,
            "estimated_fee_ugx": float(
                calculate_online_rent_fee(Decimal("3000000"))
            ),
            "landlord_net_ugx": float(
                Decimal("3000000") - calculate_online_rent_fee(Decimal("3000000"))
            ),
            "active_units": 5,
            "estimated_monthly_unit_fees_ugx": unit * 5,
        },
        "notes": [
            "Online rent (MTN, Airtel, Pesapal, Sui) is collected on the platform merchant account.",
            f"Platform keeps {pct}% (+ UGX {flat:,.0f} flat when configured, min UGX {min_fee:,.0f}).",
            f"Each occupied unit billed UGX {unit:,.0f}/month for landlord tools.",
            "Manual bank recordings by the landlord are not charged a collection fee.",
            "MoMo/Pesapal gateway charges are separate and may apply on top.",
        ],
    }


def is_online_payment_method(method: str | PaymentMethod) -> bool:
    if hasattr(method, "value"):
        method = method.value
    return str(method or "").lower() in _ONLINE_METHODS


def calculate_online_rent_fee(gross_ugx: Decimal) -> Decimal:
    """1.5% + optional flat, with minimum fee."""
    gross = Decimal(str(gross_ugx))
    pct = Decimal(str(settings.platform_rent_fee_percent or 0)) / Decimal("100")
    flat = Decimal(str(settings.platform_rent_fee_flat_ugx or 0))
    minimum = Decimal(str(settings.platform_rent_fee_min_ugx or 0))
    fee = (gross * pct + flat).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if minimum > 0 and fee < minimum:
        fee = minimum
    if fee > gross:
        fee = gross
    return fee


def _current_balance(db: Session, owner_id: int) -> Decimal:
    rows = (
        db.query(LandlordLedgerEntry.amount_ugx)
        .filter(LandlordLedgerEntry.owner_id == owner_id)
        .order_by(LandlordLedgerEntry.id.asc())
        .all()
    )
    return sum((Decimal(str(r[0] or 0)) for r in rows), Decimal("0"))


def _append_ledger(
    db: Session,
    *,
    owner_id: int,
    entry_type: LedgerEntryType,
    amount_ugx: Decimal,
    description: str,
    payment_id: int | None = None,
    unit_id: int | None = None,
    reference: str | None = None,
    period_month: int | None = None,
    period_year: int | None = None,
) -> LandlordLedgerEntry:
    balance = _current_balance(db, owner_id) + amount_ugx
    row = LandlordLedgerEntry(
        owner_id=owner_id,
        payment_id=payment_id,
        unit_id=unit_id,
        entry_type=entry_type,
        amount_ugx=amount_ugx,
        balance_after_ugx=balance,
        description=description,
        reference=reference,
        period_month=period_month,
        period_year=period_year,
    )
    db.add(row)
    db.flush()
    return row


def record_online_rent_settlement(
    db: Session,
    *,
    owner_id: int,
    payment_id: int,
    gross_ugx: Decimal,
    payment_method: str,
    reference: str | None = None,
) -> dict:
    """
  After gateway settlement: credit landlord net, record platform fee.
  Idempotent per payment_id.
  """
    existing = (
        db.query(LandlordLedgerEntry)
        .filter(
            LandlordLedgerEntry.payment_id == payment_id,
            LandlordLedgerEntry.entry_type == LedgerEntryType.rent_credit,
        )
        .first()
    )
    if existing:
        fee_row = (
            db.query(LandlordLedgerEntry)
            .filter(
                LandlordLedgerEntry.payment_id == payment_id,
                LandlordLedgerEntry.entry_type == LedgerEntryType.platform_fee,
            )
            .first()
        )
        return {
            "gross_ugx": float(gross_ugx),
            "platform_fee_ugx": float(abs(fee_row.amount_ugx)) if fee_row else 0.0,
            "net_to_landlord_ugx": float(existing.amount_ugx),
            "already_recorded": True,
        }

    gross = Decimal(str(gross_ugx))
    if not is_online_payment_method(payment_method):
        fee = Decimal("0")
    else:
        fee = calculate_online_rent_fee(gross)
    net = gross - fee

    _append_ledger(
        db,
        owner_id=owner_id,
        payment_id=payment_id,
        entry_type=LedgerEntryType.rent_credit,
        amount_ugx=net,
        description=f"Rent collected (net after platform fee) — ref {reference or payment_id}",
        reference=reference,
    )
    if fee > 0:
        _append_ledger(
            db,
            owner_id=owner_id,
            payment_id=payment_id,
            entry_type=LedgerEntryType.platform_fee,
            amount_ugx=-fee,
            description=f"Platform collection fee ({settings.platform_rent_fee_percent}%)",
            reference=reference,
        )

    return {
        "gross_ugx": float(gross),
        "platform_fee_ugx": float(fee),
        "net_to_landlord_ugx": float(net),
        "already_recorded": False,
    }


def count_billable_units(db: Session, owner_id: int) -> int:
    properties = (
        db.query(Property)
        .filter(Property.owner_id == owner_id, Property.is_active == True)  # noqa: E712
        .all()
    )
    occupied = UnitStatus.occupied.value
    count = 0
    for prop in properties:
        for unit in prop.units or []:
            st = unit.status.value if hasattr(unit.status, "value") else str(unit.status)
            if st == occupied:
                count += 1
    return count


def accrue_monthly_unit_fees(
    db: Session,
    *,
    owner_id: int,
    period_month: int | None = None,
    period_year: int | None = None,
) -> dict:
    """Charge per occupied unit for the month (idempotent)."""
    today = date.today()
    month = period_month or today.month
    year = period_year or today.year
    unit_fee = Decimal(str(settings.platform_unit_fee_monthly_ugx or 0))
    if unit_fee <= 0:
        return {"units_billed": 0, "total_ugx": 0.0, "skipped": True}

    ref = f"unit-fee-{owner_id}-{year:04d}-{month:02d}"
    existing = (
        db.query(LandlordLedgerEntry)
        .filter(
            LandlordLedgerEntry.owner_id == owner_id,
            LandlordLedgerEntry.reference == ref,
        )
        .first()
    )
    if existing:
        return {"units_billed": 0, "total_ugx": 0.0, "already_accrued": True, "reference": ref}

    units = count_billable_units(db, owner_id)
    if units == 0:
        return {"units_billed": 0, "total_ugx": 0.0, "reference": ref}

    total = unit_fee * units
    _append_ledger(
        db,
        owner_id=owner_id,
        entry_type=LedgerEntryType.unit_subscription,
        amount_ugx=-total,
        description=f"Platform subscription — {units} active unit(s) @ UGX {unit_fee:,.0f}",
        reference=ref,
        period_month=month,
        period_year=year,
    )
    return {"units_billed": units, "total_ugx": float(total), "reference": ref}


def landlord_balance_summary(db: Session, owner_id: int) -> dict:
    entries = (
        db.query(LandlordLedgerEntry)
        .filter(LandlordLedgerEntry.owner_id == owner_id)
        .order_by(LandlordLedgerEntry.id.desc())
        .limit(500)
        .all()
    )
    available = _current_balance(db, owner_id)
    fees_paid = sum(
        abs(Decimal(str(e.amount_ugx)))
        for e in entries
        if e.entry_type == LedgerEntryType.platform_fee
    )
    unit_fees = sum(
        abs(Decimal(str(e.amount_ugx)))
        for e in entries
        if e.entry_type == LedgerEntryType.unit_subscription
    )
    credits = sum(
        Decimal(str(e.amount_ugx))
        for e in entries
        if e.entry_type == LedgerEntryType.rent_credit
    )
    payouts = sum(
        abs(Decimal(str(e.amount_ugx)))
        for e in entries
        if e.entry_type == LedgerEntryType.payout
    )
    units = count_billable_units(db, owner_id)
    unit_fee = float(settings.platform_unit_fee_monthly_ugx or 0)
    return {
        "available_balance_ugx": float(available),
        "lifetime_rent_credited_ugx": float(credits),
        "lifetime_platform_fees_ugx": float(fees_paid),
        "lifetime_unit_fees_ugx": float(unit_fees),
        "lifetime_paid_out_ugx": float(payouts),
        "active_units": units,
        "estimated_monthly_unit_fees_ugx": round(units * unit_fee, 2),
        "fee_config": fee_config_public(),
        "recent_ledger": [_ledger_dict(e) for e in entries[:20]],
    }


def platform_revenue_summary(db: Session) -> dict:
    rows = db.query(LandlordLedgerEntry).all()
    fee_total = Decimal("0")
    unit_total = Decimal("0")
    rent_net = Decimal("0")
    by_landlord: dict[int, Decimal] = {}
    for row in rows:
        amt = Decimal(str(row.amount_ugx or 0))
        if row.entry_type == LedgerEntryType.platform_fee:
            fee_total += abs(amt)
            by_landlord[row.owner_id] = by_landlord.get(row.owner_id, Decimal("0")) + abs(amt)
        elif row.entry_type == LedgerEntryType.unit_subscription:
            unit_total += abs(amt)
        elif row.entry_type == LedgerEntryType.rent_credit:
            rent_net += amt
    return {
        "platform_rent_fees_ugx": float(fee_total),
        "platform_unit_fees_ugx": float(unit_total),
        "total_platform_revenue_ugx": float(fee_total + unit_total),
        "landlord_net_rent_credited_ugx": float(rent_net),
        "landlords_with_fees": len(by_landlord),
        "fee_config": fee_config_public(),
    }


def list_ledger(
    db: Session,
    owner_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    rows = (
        db.query(LandlordLedgerEntry)
        .filter(LandlordLedgerEntry.owner_id == owner_id)
        .order_by(LandlordLedgerEntry.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_ledger_dict(r) for r in rows]


def _ledger_dict(row: LandlordLedgerEntry) -> dict:
    et = row.entry_type.value if hasattr(row.entry_type, "value") else str(row.entry_type)
    return {
        "id": row.id,
        "entry_type": et,
        "amount_ugx": float(row.amount_ugx or 0),
        "balance_after_ugx": float(row.balance_after_ugx) if row.balance_after_ugx is not None else None,
        "description": row.description,
        "reference": row.reference,
        "payment_id": row.payment_id,
        "period_month": row.period_month,
        "period_year": row.period_year,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
