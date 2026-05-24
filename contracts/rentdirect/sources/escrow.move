module rentdirect::escrow;

use sui::event;

/// Rent escrow metadata object — fund/release coins via separate treasury integration.
public struct Escrow has key, store {
    id: sui::object::UID,
    lease_ref: vector<u8>,
    tenant: address,
    landlord: address,
    amount_mist: u64,
    released: bool,
}

public struct EscrowCreated has copy, drop {
    escrow_id: sui::object::ID,
    amount_mist: u64,
}

public struct EscrowReleased has copy, drop {
    escrow_id: sui::object::ID,
}

public fun create_escrow(
    lease_ref: vector<u8>,
    landlord: address,
    amount_mist: u64,
    ctx: &mut sui::tx_context::TxContext,
) {
    let escrow = Escrow {
        id: sui::object::new(ctx),
        lease_ref,
        tenant: sui::tx_context::sender(ctx),
        landlord,
        amount_mist,
        released: false,
    };
    event::emit(EscrowCreated {
        escrow_id: sui::object::id(&escrow),
        amount_mist,
    });
    sui::transfer::share_object(escrow);
}

public fun release_escrow(escrow: &mut Escrow, ctx: &mut sui::tx_context::TxContext) {
    assert!(!escrow.released, 0);
    assert!(sui::tx_context::sender(ctx) == escrow.landlord, 1);
    escrow.released = true;
    event::emit(EscrowReleased { escrow_id: sui::object::id(escrow) });
}
