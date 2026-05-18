from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class SavedUnit(Base):
    """Tenant (or any user) bookmark for a marketplace unit."""

    __tablename__ = "saved_units"
    __table_args__ = (UniqueConstraint("user_id", "unit_id", name="uq_saved_unit_user_unit"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())
