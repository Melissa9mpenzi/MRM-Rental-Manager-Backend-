"""Agent workspace CRM — leads, clients, schedules, deals, commissions."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class LeadStage(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    viewing = "viewing"
    negotiating = "negotiating"
    closed = "closed"
    lost = "lost"


class ClientType(str, enum.Enum):
    renter = "renter"
    buyer = "buyer"
    landlord = "landlord"


class ScheduleEventType(str, enum.Enum):
    viewing = "viewing"
    callback = "callback"
    handover = "handover"
    other = "other"


class ScheduleStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class DealStatus(str, enum.Enum):
    open = "open"
    won = "won"
    lost = "lost"


class CommissionStatus(str, enum.Enum):
    accrued = "accrued"
    paid = "paid"
    held = "held"


class AgentLead(Base):
    __tablename__ = "agent_leads"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(32), nullable=True)
    email = Column(String(255), nullable=True)
    source = Column(String(64), default="inbound")
    stage = Column(Enum(LeadStage), default=LeadStage.new, nullable=False, index=True)
    listing_title = Column(String(255), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    budget_ugx = Column(Numeric(14, 2), nullable=True)
    notes = Column(Text, nullable=True)
    thread_id = Column(Integer, ForeignKey("message_threads.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", foreign_keys=[owner_id])


class AgentClient(Base):
    __tablename__ = "agent_clients"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(32), nullable=True)
    email = Column(String(255), nullable=True)
    client_type = Column(Enum(ClientType), default=ClientType.renter, nullable=False)
    lead_id = Column(Integer, ForeignKey("agent_leads.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    follow_up_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentScheduleEvent(Base):
    __tablename__ = "agent_schedule_events"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    event_type = Column(Enum(ScheduleEventType), default=ScheduleEventType.viewing, nullable=False)
    status = Column(Enum(ScheduleStatus), default=ScheduleStatus.scheduled, nullable=False)
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=True)
    location = Column(String(255), nullable=True)
    lead_id = Column(Integer, ForeignKey("agent_leads.id", ondelete="SET NULL"), nullable=True)
    client_id = Column(Integer, ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentDeal(Base):
    __tablename__ = "agent_deals"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    status = Column(Enum(DealStatus), default=DealStatus.open, nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("agent_leads.id", ondelete="SET NULL"), nullable=True)
    client_id = Column(Integer, ForeignKey("agent_clients.id", ondelete="SET NULL"), nullable=True)
    offer_amount_ugx = Column(Numeric(14, 2), nullable=True)
    commission_ugx = Column(Numeric(14, 2), nullable=True)
    notes = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentCommission(Base):
    __tablename__ = "agent_commissions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("agent_deals.id", ondelete="SET NULL"), nullable=True)
    description = Column(String(255), nullable=True)
    amount_ugx = Column(Numeric(14, 2), nullable=False)
    status = Column(Enum(CommissionStatus), default=CommissionStatus.accrued, nullable=False, index=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
