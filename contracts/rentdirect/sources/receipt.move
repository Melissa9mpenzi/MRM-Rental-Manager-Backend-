module rentdirect::receipt;

use sui::event;

/// Immutable on-chain payment receipt anchor.
public struct PaymentReceipt has key, store {
    id: sui::object::UID,
    platform_ref: vector<u8>,
    amount_ugx: u64,
    payment_method: vector<u8>,
    receipt_hash: vector<u8>,
}

public struct ReceiptAnchored has copy, drop {
    receipt_id: sui::object::ID,
    platform_ref: vector<u8>,
    receipt_hash: vector<u8>,
}

public fun anchor_receipt(
    platform_ref: vector<u8>,
    amount_ugx: u64,
    payment_method: vector<u8>,
    receipt_hash: vector<u8>,
    ctx: &mut sui::tx_context::TxContext,
) {
    let receipt = PaymentReceipt {
        id: sui::object::new(ctx),
        platform_ref,
        amount_ugx,
        payment_method,
        receipt_hash,
    };
    let receipt_id = sui::object::id(&receipt);
    event::emit(ReceiptAnchored {
        receipt_id,
        platform_ref,
        receipt_hash,
    });
    sui::transfer::transfer(receipt, sui::tx_context::sender(ctx));
}
