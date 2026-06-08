module rentdirect::property_identity;

use sui::event;

/// On-chain listing identity — one object per property listing on RentDirect.
public struct PropertyListingIdentity has key, store {
    id: sui::object::UID,
    property_id: u64,
    landlord: address,
    location: vector<u8>,
    listed_at_ms: u64,
}

public struct PropertyListed has copy, drop {
    identity_id: sui::object::ID,
    property_id: u64,
    landlord: address,
}

/// Mint a listing identity NFT and transfer it to the landlord wallet.
public fun mint_listing_identity(
    property_id: u64,
    location: vector<u8>,
    listed_at_ms: u64,
    recipient: address,
    ctx: &mut sui::tx_context::TxContext,
) {
    let identity = PropertyListingIdentity {
        id: sui::object::new(ctx),
        property_id,
        landlord: recipient,
        location,
        listed_at_ms,
    };
    let identity_id = sui::object::id(&identity);
    event::emit(PropertyListed {
        identity_id,
        property_id,
        landlord: recipient,
    });
    sui::transfer::transfer(identity, recipient);
}
