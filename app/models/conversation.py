import enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ThreadType(str, enum.Enum):
    inquiry = "inquiry"
    contract = "contract"
    support = "support"
    compliance = "compliance"
    escrow = "escrow"


class MessageKind(str, enum.Enum):
    user = "user"
    system = "system"
    ai = "ai"


class MessageThread(Base):
    __tablename__ = "message_threads"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    thread_type = Column(Enum(ThreadType), default=ThreadType.inquiry, nullable=False, index=True)
    subject = Column(String(255), nullable=True)
    listing_title = Column(String(255), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    participants = relationship(
        "ThreadParticipant",
        back_populates="thread",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class ThreadParticipant(Base):
    __tablename__ = "thread_participants"

    thread_id = Column(Integer, ForeignKey("message_threads.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_read_at = Column(DateTime, nullable=True)

    thread = relationship("MessageThread", back_populates="participants")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    message_kind = Column(Enum(MessageKind), default=MessageKind.user, nullable=False)
    body = Column(Text, nullable=False)
    event_code = Column(String(64), nullable=True)
    attachment_url = Column(String(500), nullable=True)
    attachment_name = Column(String(255), nullable=True)
    attachment_mime = Column(String(128), nullable=True)
    blockchain_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    thread = relationship("MessageThread", back_populates="messages")
