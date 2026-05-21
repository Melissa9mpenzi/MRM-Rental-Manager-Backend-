"""Invitation-only provisioning for government portal officers."""
from __future__ import annotations

import enum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base
from app.models.user import UserRole


class InvitationStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


class GovernmentInvitation(Base):
    __tablename__ = "government_invitations"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=True)
    agency = Column(String(24), nullable=False)  # nira | kcca | ura | platform
    role = Column(Enum(UserRole), nullable=False)
    work_id = Column(String(64), nullable=False)
    token = Column(String(128), nullable=False, unique=True, index=True)
    status = Column(Enum(InvitationStatus), default=InvitationStatus.pending, nullable=False)
    invited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
