from pydantic import BaseModel, Field
from typing import Optional


class LinkWalletBody(BaseModel):
    sui_address: str = Field(..., min_length=10, max_length=80)
    wallet_name: Optional[str] = Field(None, max_length=64)


class ConfirmSuiTxBody(BaseModel):
    tx_digest: str = Field(..., min_length=20, max_length=128)
    wallet_address: Optional[str] = Field(None, max_length=80)


class ReleaseEscrowBody(BaseModel):
    release_tx_digest: Optional[str] = Field(None, max_length=128)
