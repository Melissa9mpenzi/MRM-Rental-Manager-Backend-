"""Hybrid Web3 API — Sui wallets, receipts, escrow (alongside MoMo/Pesapal)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, require_tenant
from app.models.user import User
from app.schemas.blockchain import ConfirmSuiTxBody, LinkWalletBody, ReleaseEscrowBody
from app.services import payment_gateway_service
from app.services.blockchain import blockchain_service, walrus_anchor_service
from app.services.gateway.config import gateway_public_status
from app.utils.response import success_response

router = APIRouter(tags=["Blockchain"])


@router.get("/blockchain/dashboard")
def blockchain_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success_response(data=blockchain_service.admin_dashboard(db, current_user))


@router.get("/blockchain/receipts/{receipt_id}")
def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return success_response(data=blockchain_service.get_receipt(db, current_user, receipt_id))


@router.get("/blockchain/status")
def blockchain_status(db: Session = Depends(get_db)):
    """Public Sui/Walrus configuration for wallet connect UI."""
    return success_response(
        data={
            **blockchain_service.blockchain_public_status(),
            "fiat_gateway": gateway_public_status(),
            "walrus_inventory": walrus_anchor_service.walrus_inventory(db),
        }
    )


@router.get("/blockchain/walrus/inventory")
def walrus_inventory(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Counts of Walrus-anchored artifacts (KYC, property, audit, receipts, escrow)."""
    return success_response(data=walrus_anchor_service.walrus_inventory(db))


@router.get("/blockchain/wallet/me")
def my_wallet(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return success_response(data=blockchain_service.get_primary_wallet(db, current_user))


@router.post("/blockchain/wallet/link")
def link_wallet(
    body: LinkWalletBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = blockchain_service.link_wallet(db, current_user, body.sui_address, body.wallet_name)
    return success_response(data=data, message="Wallet linked.")


@router.get("/blockchain/receipts")
def list_receipts(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = blockchain_service.list_receipts_for_user(db, current_user, limit=limit)
    return success_response(data=rows)


@router.get("/blockchain/escrow")
def list_escrow(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = blockchain_service.list_escrows_for_user(db, current_user)
    return success_response(data=rows)


@router.post("/blockchain/escrow/lease/{lease_id}")
def create_escrow(
    lease_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hold = blockchain_service.create_escrow_for_lease(db, current_user, lease_id)
    rows = blockchain_service.list_escrows_for_user(db, current_user)
    row = next((r for r in rows if r["id"] == hold.id), None)
    return success_response(data=row or {"id": hold.id}, message="Escrow created.")


@router.post("/blockchain/escrow/{escrow_id}/release")
def release_escrow(
    escrow_id: int,
    body: ReleaseEscrowBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    hold = blockchain_service.release_escrow(
        db, current_user, escrow_id, release_tx_digest=body.release_tx_digest
    )
    rows = blockchain_service.list_escrows_for_user(db, current_user)
    row = next((r for r in rows if r["id"] == hold.id), None)
    return success_response(data=row or {"id": hold.id}, message="Escrow released.")


@router.post("/payments/checkout/{reference}/confirm-sui")
def confirm_sui_tx(
    reference: str,
    body: ConfirmSuiTxBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """After wallet signs SUI transfer, submit tx digest for on-chain verification."""
    data = payment_gateway_service.confirm_sui_checkout(
        db,
        current_user,
        reference,
        tx_digest=body.tx_digest.strip(),
        wallet_address=body.wallet_address,
    )
    return success_response(data=data, message="Sui payment verified and recorded.")
