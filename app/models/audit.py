from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    action = Column(String(100), nullable=False)
    table_name = Column(String(50))
    record_id = Column(Integer)
    old_value = Column(Text)  # JSON payload as text
    new_value = Column(Text)  # JSON payload as text
    ip_address = Column(String(45))
    walrus_blob_id = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

