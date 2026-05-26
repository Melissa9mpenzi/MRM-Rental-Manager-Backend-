"""CRUD and analytics for agent (staff) workspace."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_crm import (
    AgentClient,
    AgentCommission,
    AgentDeal,
    AgentLead,
    AgentScheduleEvent,
    ClientType,
    CommissionStatus,
    DealStatus,
    LeadStage,
    ScheduleEventType,
    ScheduleStatus,
)
from app.models.payment import Payment, PaymentType
from app.schemas.agent_crm import (
    ClientCreate,
    ClientUpdate,
    CommissionCreate,
    CommissionUpdate,
    DealCreate,
    DealUpdate,
    LeadCreate,
    LeadUpdate,
    ScheduleCreate,
    ScheduleUpdate,
)

STAGE_LABELS = {
    LeadStage.new: "New leads",
    LeadStage.contacted: "Contacted",
    LeadStage.viewing: "Viewing",
    LeadStage.negotiating: "Negotiating",
    LeadStage.closed: "Closed",
    LeadStage.lost: "Lost",
}


def _enum_val(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _money(v) -> float:
    if v is None:
        return 0.0
    return float(v)


def _dt_iso(v: Optional[datetime]) -> Optional[str]:
    if not v:
        return None
    return v.isoformat()


def _serialize_lead(row: AgentLead) -> dict[str, Any]:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "phone": row.phone,
        "email": row.email,
        "source": row.source,
        "stage": _enum_val(row.stage),
        "stage_label": STAGE_LABELS.get(row.stage, _enum_val(row.stage)),
        "listing_title": row.listing_title,
        "property_id": row.property_id,
        "unit_id": row.unit_id,
        "budget_ugx": _money(row.budget_ugx),
        "notes": row.notes,
        "thread_id": row.thread_id,
        "created_at": _dt_iso(row.created_at),
        "updated_at": _dt_iso(row.updated_at),
    }


def _serialize_client(row: AgentClient) -> dict[str, Any]:
    return {
        "id": row.id,
        "full_name": row.full_name,
        "phone": row.phone,
        "email": row.email,
        "client_type": _enum_val(row.client_type),
        "lead_id": row.lead_id,
        "notes": row.notes,
        "follow_up_at": _dt_iso(row.follow_up_at),
        "created_at": _dt_iso(row.created_at),
        "updated_at": _dt_iso(row.updated_at),
    }


def _serialize_schedule(row: AgentScheduleEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "event_type": _enum_val(row.event_type),
        "status": _enum_val(row.status),
        "starts_at": _dt_iso(row.starts_at),
        "ends_at": _dt_iso(row.ends_at),
        "location": row.location,
        "lead_id": row.lead_id,
        "client_id": row.client_id,
        "property_id": row.property_id,
        "unit_id": row.unit_id,
        "notes": row.notes,
        "created_at": _dt_iso(row.created_at),
    }


def _serialize_deal(row: AgentDeal) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "status": _enum_val(row.status),
        "lead_id": row.lead_id,
        "client_id": row.client_id,
        "offer_amount_ugx": _money(row.offer_amount_ugx),
        "commission_ugx": _money(row.commission_ugx),
        "notes": row.notes,
        "closed_at": _dt_iso(row.closed_at),
        "created_at": _dt_iso(row.created_at),
        "updated_at": _dt_iso(row.updated_at),
    }


def _serialize_commission(row: AgentCommission) -> dict[str, Any]:
    return {
        "id": row.id,
        "deal_id": row.deal_id,
        "description": row.description,
        "amount_ugx": _money(row.amount_ugx),
        "status": _enum_val(row.status),
        "paid_at": _dt_iso(row.paid_at),
        "created_at": _dt_iso(row.created_at),
    }


def _load_lead(db: Session, lead_id: int, owner_id: int) -> AgentLead:
    row = db.query(AgentLead).filter(AgentLead.id == lead_id, AgentLead.owner_id == owner_id).first()
    if not row:
        raise HTTPException(404, "Lead not found")
    return row


# ── Leads ─────────────────────────────────────────────────────────

def list_leads(db: Session, owner_id: int, stage: Optional[str] = None, q: Optional[str] = None) -> list[dict]:
    query = db.query(AgentLead).filter(AgentLead.owner_id == owner_id)
    if stage:
        try:
            query = query.filter(AgentLead.stage == LeadStage(stage))
        except ValueError:
            pass
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (AgentLead.full_name.ilike(like))
            | (AgentLead.phone.ilike(like))
            | (AgentLead.email.ilike(like))
            | (AgentLead.listing_title.ilike(like))
        )
    rows = query.order_by(AgentLead.updated_at.desc()).limit(200).all()
    return [_serialize_lead(r) for r in rows]


def create_lead(db: Session, owner_id: int, data: LeadCreate) -> dict:
    try:
        st = LeadStage(data.stage)
    except ValueError:
        st = LeadStage.new
    row = AgentLead(
        owner_id=owner_id,
        full_name=data.full_name.strip(),
        phone=data.phone,
        email=data.email,
        source=data.source or "inbound",
        stage=st,
        listing_title=data.listing_title,
        property_id=data.property_id,
        unit_id=data.unit_id,
        budget_ugx=data.budget_ugx,
        notes=data.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_lead(row)


def update_lead(db: Session, owner_id: int, lead_id: int, data: LeadUpdate) -> dict:
    row = _load_lead(db, lead_id, owner_id)
    payload = data.model_dump(exclude_none=True)
    if "stage" in payload:
        try:
            row.stage = LeadStage(payload.pop("stage"))
        except ValueError:
            pass
    for k, v in payload.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize_lead(row)


def delete_lead(db: Session, owner_id: int, lead_id: int) -> None:
    row = _load_lead(db, lead_id, owner_id)
    db.delete(row)
    db.commit()


# ── Clients ─────────────────────────────────────────────────────────

def list_clients(db: Session, owner_id: int, q: Optional[str] = None) -> list[dict]:
    query = db.query(AgentClient).filter(AgentClient.owner_id == owner_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (AgentClient.full_name.ilike(like))
            | (AgentClient.phone.ilike(like))
            | (AgentClient.email.ilike(like))
        )
    rows = query.order_by(AgentClient.updated_at.desc()).limit(200).all()
    return [_serialize_client(r) for r in rows]


def create_client(db: Session, owner_id: int, data: ClientCreate) -> dict:
    try:
        ct = ClientType(data.client_type)
    except ValueError:
        ct = ClientType.renter
    row = AgentClient(
        owner_id=owner_id,
        full_name=data.full_name.strip(),
        phone=data.phone,
        email=data.email,
        client_type=ct,
        lead_id=data.lead_id,
        notes=data.notes,
        follow_up_at=data.follow_up_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_client(row)


def update_client(db: Session, owner_id: int, client_id: int, data: ClientUpdate) -> dict:
    row = (
        db.query(AgentClient)
        .filter(AgentClient.id == client_id, AgentClient.owner_id == owner_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Client not found")
    payload = data.model_dump(exclude_none=True)
    if "client_type" in payload:
        try:
            row.client_type = ClientType(payload.pop("client_type"))
        except ValueError:
            pass
    for k, v in payload.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize_client(row)


# ── Schedules ───────────────────────────────────────────────────────

def list_schedules(
    db: Session, owner_id: int, from_dt: Optional[datetime] = None, to_dt: Optional[datetime] = None
) -> list[dict]:
    query = db.query(AgentScheduleEvent).filter(AgentScheduleEvent.owner_id == owner_id)
    if from_dt:
        query = query.filter(AgentScheduleEvent.starts_at >= from_dt)
    if to_dt:
        query = query.filter(AgentScheduleEvent.starts_at <= to_dt)
    rows = query.order_by(AgentScheduleEvent.starts_at.asc()).limit(300).all()
    return [_serialize_schedule(r) for r in rows]


def create_schedule(db: Session, owner_id: int, data: ScheduleCreate) -> dict:
    try:
        et = ScheduleEventType(data.event_type)
    except ValueError:
        et = ScheduleEventType.viewing
    row = AgentScheduleEvent(
        owner_id=owner_id,
        title=data.title.strip(),
        event_type=et,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        location=data.location,
        lead_id=data.lead_id,
        client_id=data.client_id,
        property_id=data.property_id,
        unit_id=data.unit_id,
        notes=data.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_schedule(row)


def update_schedule(db: Session, owner_id: int, event_id: int, data: ScheduleUpdate) -> dict:
    row = (
        db.query(AgentScheduleEvent)
        .filter(AgentScheduleEvent.id == event_id, AgentScheduleEvent.owner_id == owner_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Schedule event not found")
    payload = data.model_dump(exclude_none=True)
    if "event_type" in payload:
        try:
            row.event_type = ScheduleEventType(payload.pop("event_type"))
        except ValueError:
            pass
    if "status" in payload:
        try:
            row.status = ScheduleStatus(payload.pop("status"))
        except ValueError:
            pass
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _serialize_schedule(row)


# ── Deals ───────────────────────────────────────────────────────────

def list_deals(db: Session, owner_id: int, status: Optional[str] = None) -> list[dict]:
    query = db.query(AgentDeal).filter(AgentDeal.owner_id == owner_id)
    if status:
        try:
            query = query.filter(AgentDeal.status == DealStatus(status))
        except ValueError:
            pass
    rows = query.order_by(AgentDeal.updated_at.desc()).limit(200).all()
    return [_serialize_deal(r) for r in rows]


def create_deal(db: Session, owner_id: int, data: DealCreate) -> dict:
    row = AgentDeal(
        owner_id=owner_id,
        title=data.title.strip(),
        lead_id=data.lead_id,
        client_id=data.client_id,
        offer_amount_ugx=data.offer_amount_ugx,
        commission_ugx=data.commission_ugx,
        notes=data.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_deal(row)


def update_deal(db: Session, owner_id: int, deal_id: int, data: DealUpdate) -> dict:
    row = (
        db.query(AgentDeal)
        .filter(AgentDeal.id == deal_id, AgentDeal.owner_id == owner_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Deal not found")
    payload = data.model_dump(exclude_none=True)
    if "status" in payload:
        try:
            new_status = DealStatus(payload.pop("status"))
            row.status = new_status
            if new_status in (DealStatus.won, DealStatus.lost) and not row.closed_at:
                row.closed_at = datetime.now(timezone.utc)
            if new_status == DealStatus.won and row.commission_ugx and row.commission_ugx > 0:
                existing = (
                    db.query(AgentCommission)
                    .filter(AgentCommission.deal_id == row.id, AgentCommission.owner_id == owner_id)
                    .first()
                )
                if not existing:
                    db.add(
                        AgentCommission(
                            owner_id=owner_id,
                            deal_id=row.id,
                            amount_ugx=row.commission_ugx,
                            description=f"Commission — {row.title}",
                            status=CommissionStatus.accrued,
                        )
                    )
        except ValueError:
            pass
    for k, v in payload.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _serialize_deal(row)


# ── Commissions ─────────────────────────────────────────────────────

def list_commissions(db: Session, owner_id: int, status: Optional[str] = None) -> list[dict]:
    query = db.query(AgentCommission).filter(AgentCommission.owner_id == owner_id)
    if status:
        try:
            query = query.filter(AgentCommission.status == CommissionStatus(status))
        except ValueError:
            pass
    rows = query.order_by(AgentCommission.created_at.desc()).limit(200).all()
    return [_serialize_commission(r) for r in rows]


def create_commission(db: Session, owner_id: int, data: CommissionCreate) -> dict:
    try:
        st = CommissionStatus(data.status)
    except ValueError:
        st = CommissionStatus.accrued
    row = AgentCommission(
        owner_id=owner_id,
        deal_id=data.deal_id,
        amount_ugx=data.amount_ugx,
        description=data.description,
        status=st,
        paid_at=datetime.now(timezone.utc) if st == CommissionStatus.paid else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_commission(row)


def update_commission(db: Session, owner_id: int, comm_id: int, data: CommissionUpdate) -> dict:
    row = (
        db.query(AgentCommission)
        .filter(AgentCommission.id == comm_id, AgentCommission.owner_id == owner_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "Commission not found")
    if data.status:
        try:
            row.status = CommissionStatus(data.status)
            if row.status == CommissionStatus.paid and not row.paid_at:
                row.paid_at = datetime.now(timezone.utc)
        except ValueError:
            pass
    if data.description is not None:
        row.description = data.description
    db.commit()
    db.refresh(row)
    return _serialize_commission(row)


# ── Analytics & dashboard aggregates ────────────────────────────────

def pipeline_counts(db: Session, owner_id: int) -> list[dict]:
    counts = {s: 0 for s in LeadStage}
    rows = (
        db.query(AgentLead.stage, func.count(AgentLead.id))
        .filter(AgentLead.owner_id == owner_id)
        .group_by(AgentLead.stage)
        .all()
    )
    for st, cnt in rows:
        if st in counts:
            counts[st] = int(cnt)
    order = [
        LeadStage.new,
        LeadStage.contacted,
        LeadStage.viewing,
        LeadStage.negotiating,
        LeadStage.closed,
    ]
    return [{"stage": STAGE_LABELS[s], "count": counts[s]} for s in order]


def recent_leads_for_dashboard(db: Session, owner_id: int, limit: int = 8) -> list[dict]:
    rows = (
        db.query(AgentLead)
        .filter(AgentLead.owner_id == owner_id)
        .order_by(AgentLead.updated_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for r in rows:
        budget = _money(r.budget_ugx)
        out.append(
            {
                "id": r.id,
                "client": r.full_name,
                "phone": r.phone or "—",
                "listing": r.listing_title or "—",
                "stage": STAGE_LABELS.get(r.stage, _enum_val(r.stage)),
                "budget": f"UGX {budget:,.0f}" if budget else "—",
                "updated": r.updated_at.strftime("%d %b") if r.updated_at else "—",
            }
        )
    return out


def commission_trend(db: Session, owner_id: int, months: int = 6) -> list[dict]:
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    today = date.today()
    buckets: dict[tuple[int, int], float] = {}
    rows = (
        db.query(AgentCommission)
        .filter(
            AgentCommission.owner_id == owner_id,
            AgentCommission.status.in_([CommissionStatus.accrued, CommissionStatus.paid, CommissionStatus.held]),
        )
        .all()
    )
    for c in rows:
        if not c.created_at:
            continue
        key = (c.created_at.year, c.created_at.month)
        buckets[key] = buckets.get(key, 0.0) + _money(c.amount_ugx)

    trend = []
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        v = buckets.get((y, m), 0.0) / 1_000_000
        trend.append({"m": MONTHS[m - 1], "v": round(v, 2)})
    return trend


def staff_kpis(db: Session, owner_id: int) -> dict[str, Any]:
    total_leads = db.query(func.count(AgentLead.id)).filter(AgentLead.owner_id == owner_id).scalar() or 0
    open_deals = (
        db.query(func.count(AgentDeal.id))
        .filter(AgentDeal.owner_id == owner_id, AgentDeal.status == DealStatus.open)
        .scalar()
        or 0
    )
    today = date.today()
    ytd_start = datetime(today.year, 1, 1, tzinfo=timezone.utc)
    commissions_ytd = (
        db.query(func.coalesce(func.sum(AgentCommission.amount_ugx), 0))
        .filter(
            AgentCommission.owner_id == owner_id,
            AgentCommission.created_at >= ytd_start,
        )
        .scalar()
        or 0
    )
    pending_payout = (
        db.query(func.coalesce(func.sum(AgentCommission.amount_ugx), 0))
        .filter(
            AgentCommission.owner_id == owner_id,
            AgentCommission.status.in_([CommissionStatus.accrued, CommissionStatus.held]),
        )
        .scalar()
        or 0
    )
    return {
        "total_leads": int(total_leads),
        "active_deals": int(open_deals),
        "commissions_ytd_ugx": _money(commissions_ytd),
        "pending_payout_ugx": _money(pending_payout),
    }


def analytics(db: Session, owner_id: int) -> dict[str, Any]:
    total = db.query(func.count(AgentLead.id)).filter(AgentLead.owner_id == owner_id).scalar() or 0
    closed = (
        db.query(func.count(AgentLead.id))
        .filter(AgentLead.owner_id == owner_id, AgentLead.stage == LeadStage.closed)
        .scalar()
        or 0
    )
    viewing = (
        db.query(func.count(AgentLead.id))
        .filter(AgentLead.owner_id == owner_id, AgentLead.stage == LeadStage.viewing)
        .scalar()
        or 0
    )
    won_deals = (
        db.query(func.count(AgentDeal.id))
        .filter(AgentDeal.owner_id == owner_id, AgentDeal.status == DealStatus.won)
        .scalar()
        or 0
    )
    conversion = round(100 * closed / total, 1) if total else 0.0
    funnel = pipeline_counts(db, owner_id)
    return {
        "kpis": {
            "total_leads": int(total),
            "active_viewings": int(viewing),
            "closed_leads": int(closed),
            "won_deals": int(won_deals),
            "conversion_pct": conversion,
        },
        "funnel": funnel,
        "commission_trend": commission_trend(db, owner_id),
        "deals_by_status": [
            {
                "status": s.value,
                "count": int(
                    db.query(func.count(AgentDeal.id))
                    .filter(AgentDeal.owner_id == owner_id, AgentDeal.status == s)
                    .scalar()
                    or 0
                ),
            }
            for s in DealStatus
        ],
    }
