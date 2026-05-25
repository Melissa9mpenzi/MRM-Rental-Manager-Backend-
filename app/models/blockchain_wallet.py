"""Linked Sui wallet addresses (Slush, Nightly, Suiet, etc.)."""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class BlockchainWallet(Base):
    __tablename__ = "blockchain_wallets"
    __table_args__ = (UniqueConstraint("user_id", "sui_address", name="uq_wallet_user_address"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sui_address = Column(String(80), nullable=False, index=True)
    wallet_name = Column(String(64), nullable=True)
    is_primary = Column(Boolean, default=True, nullable=False)
    linked_at = Column(DateTime, default=func.now(), server_default=func.now())

    user = relationship("User", backref="blockchain_wallets")
