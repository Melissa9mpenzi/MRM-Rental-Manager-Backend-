from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models.conversation import Message, MessageKind, MessageThread, ThreadParticipant, ThreadType
from app.models.property import Property, Unit
from app.models.user import User
from app.services.media_storage_service import save_media
from app.services.trust_service import compute_trust_score, peer_profile, user_badges


def _participant_ids(thread: MessageThread) -> set[int]:
    return {p.user_id for p in thread.participants}


def _thread_type_value(t: MessageThread) -> str:
    if t.thread_type is None:
        return ThreadType.inquiry.value
    return t.thread_type.value if hasattr(t.thread_type, "value") else str(t.thread_type)


def find_thread_for_pair_and_unit(db: Session, a: int, b: int, unit_id: Optional[int]) -> Optional[MessageThread]:
    threads = (
        db.query(MessageThread)
        .filter(MessageThread.unit_id == unit_id)
        .options(joinedload(MessageThread.participants))
        .all()
    )
    pair = {a, b}
    for t in threads:
        if _participant_ids(t) == pair:
            return t
    return None


def ensure_thread(
    db: Session,
    user_a: int,
    user_b: int,
    unit_id: Optional[int],
    subject: Optional[str] = None,
    *,
    property_id: Optional[int] = None,
    thread_type: ThreadType = ThreadType.inquiry,
    listing_title: Optional[str] = None,
) -> MessageThread:
    existing = find_thread_for_pair_and_unit(db, user_a, user_b, unit_id)
    if existing:
        return existing
    t = MessageThread(
        unit_id=unit_id,
        property_id=property_id,
        thread_type=thread_type,
        subject=subject,
        listing_title=listing_title,
    )
    db.add(t)
    db.flush()
    db.add(ThreadParticipant(thread_id=t.id, user_id=user_a))
    db.add(ThreadParticipant(thread_id=t.id, user_id=user_b))
    db.commit()
    db.refresh(t)
    return t


def append_message(
    db: Session,
    thread_id: int,
    sender_id: Optional[int],
    body: str,
    *,
    message_kind: MessageKind = MessageKind.user,
    event_code: Optional[str] = None,
    attachment_url: Optional[str] = None,
    attachment_name: Optional[str] = None,
    attachment_mime: Optional[str] = None,
    blockchain_hash: Optional[str] = None,
) -> Message:
    thread = (
        db.query(MessageThread)
        .options(joinedload(MessageThread.participants))
        .filter(MessageThread.id == thread_id)
        .first()
    )
    if not thread:
        raise ValueError("thread_not_found")
    if message_kind == MessageKind.user:
        if sender_id is None:
            raise ValueError("sender_required")
        if sender_id not in _participant_ids(thread):
            raise ValueError("forbidden")
    m = Message(
        thread_id=thread_id,
        sender_id=sender_id,
        body=body.strip(),
        message_kind=message_kind,
        event_code=event_code,
        attachment_url=attachment_url,
        attachment_name=attachment_name,
        attachment_mime=attachment_mime,
        blockchain_hash=blockchain_hash,
    )
    db.add(m)
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return m


def post_system_message(db: Session, thread_id: int, event_code: str, body: str) -> Message:
    return append_message(
        db,
        thread_id,
        None,
        body,
        message_kind=MessageKind.system,
        event_code=event_code,
    )


def mark_thread_read(db: Session, thread_id: int, user_id: int) -> bool:
    row = (
        db.query(ThreadParticipant)
        .filter(ThreadParticipant.thread_id == thread_id, ThreadParticipant.user_id == user_id)
        .first()
    )
    if not row:
        return False
    row.last_read_at = datetime.utcnow()
    db.commit()
    return True


def _unread_count(thread: MessageThread, user_id: int) -> int:
    part = next((p for p in thread.participants if p.user_id == user_id), None)
    last_read = part.last_read_at if part else None
    count = 0
    for m in thread.messages:
        if m.message_kind != MessageKind.user:
            continue
        if m.sender_id == user_id:
            continue
        if last_read is None or (m.created_at and m.created_at > last_read):
            count += 1
    return count


def _property_context(db: Session, thread: MessageThread) -> dict[str, Any] | None:
    prop: Property | None = None
    unit: Unit | None = None
    if thread.unit_id:
        unit = db.query(Unit).options(joinedload(Unit.parent_property)).filter(Unit.id == thread.unit_id).first()
        prop = unit.parent_property if unit else None
    elif thread.property_id:
        prop = db.query(Property).filter(Property.id == thread.property_id).first()
    if not prop and not unit:
        return None
    return {
        "property_id": prop.id if prop else thread.property_id,
        "unit_id": unit.id if unit else thread.unit_id,
        "title": thread.listing_title or (prop.name if prop else "Property"),
        "address": prop.address if prop else None,
        "district": prop.district if prop else None,
        "photo_url": prop.photo_path if prop else None,
        "gov_verification_status": getattr(prop, "gov_verification_status", None) if prop else None,
        "unit_number": unit.unit_number if unit else None,
    }


def list_threads_for_user(
    db: Session,
    user_id: int,
    *,
    folder: str = "inbox",
    thread_type: Optional[str] = None,
    q: Optional[str] = None,
) -> List[dict[str, Any]]:
    thread_ids = [
        r[0]
        for r in db.query(ThreadParticipant.thread_id)
        .filter(ThreadParticipant.user_id == user_id)
        .distinct()
        .all()
    ]
    if not thread_ids:
        return []
    rows = (
        db.query(MessageThread)
        .filter(MessageThread.id.in_(thread_ids))
        .options(joinedload(MessageThread.participants), joinedload(MessageThread.messages))
        .order_by(MessageThread.updated_at.desc())
        .all()
    )
    out: List[dict[str, Any]] = []
    for t in rows:
        archived = t.archived_at is not None
        tt = _thread_type_value(t)

        if folder == "archived" and not archived:
            continue
        if folder != "archived" and archived:
            continue
        if folder == "property" and tt not in {ThreadType.inquiry.value} and not t.unit_id:
            continue
        if folder == "contracts" and tt != ThreadType.contract.value:
            continue
        if folder == "support" and tt not in {ThreadType.support.value, ThreadType.compliance.value}:
            continue
        if thread_type and tt != thread_type:
            continue

        others = [p.user_id for p in t.participants if p.user_id != user_id]
        other_id = others[0] if others else None
        prop_ctx = _property_context(db, t)
        gov_status = prop_ctx.get("gov_verification_status") if prop_ctx else None
        peer = peer_profile(db, other_id, gov_status) if other_id else {"id": None, "name": "Conversation", "role": None, "trust_score": 0, "badges": []}

        display_title = t.listing_title or t.subject or prop_ctx.get("title") if prop_ctx else None
        if not display_title:
            display_title = peer.get("name") or "Conversation"

        last = ""
        last_time = ""
        last_kind = "user"
        if t.messages:
            lm = max(t.messages, key=lambda m: m.created_at or datetime.min)
            last = (lm.body or "")[:120]
            last_time = lm.created_at.isoformat() if lm.created_at else ""
            last_kind = lm.message_kind.value if hasattr(lm.message_kind, "value") else str(lm.message_kind)

        hay = f"{display_title} {peer.get('name', '')} {last}".lower()
        if q and q.strip().lower() not in hay:
            continue

        me = db.query(User).filter(User.id == user_id).first()
        out.append(
            {
                "id": t.id,
                "unit_id": t.unit_id,
                "property_id": t.property_id,
                "thread_type": tt,
                "subject": t.subject,
                "title": display_title,
                "peer": peer,
                "property": prop_ctx,
                "last_preview": last,
                "last_at": last_time,
                "last_kind": last_kind,
                "unread_count": _unread_count(t, user_id),
                "archived": archived,
                "my_trust_score": compute_trust_score(me),
                "my_badges": user_badges(me),
            }
        )
    return out


def list_messages(db: Session, thread_id: int, user_id: int) -> Optional[List[dict[str, Any]]]:
    thread = (
        db.query(MessageThread)
        .options(joinedload(MessageThread.participants), joinedload(MessageThread.messages))
        .filter(MessageThread.id == thread_id)
        .first()
    )
    if not thread:
        return None
    if user_id not in _participant_ids(thread):
        return None
    mark_thread_read(db, thread_id, user_id)
    msgs = sorted(thread.messages, key=lambda m: m.id)
    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "me": m.sender_id == user_id,
            "text": m.body,
            "message_kind": m.message_kind.value if hasattr(m.message_kind, "value") else str(m.message_kind),
            "event_code": m.event_code,
            "attachment_url": m.attachment_url,
            "attachment_name": m.attachment_name,
            "attachment_mime": m.attachment_mime,
            "blockchain_hash": m.blockchain_hash,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in msgs
    ]


def thread_context(db: Session, thread_id: int, user_id: int) -> Optional[dict[str, Any]]:
    thread = (
        db.query(MessageThread)
        .options(joinedload(MessageThread.participants), joinedload(MessageThread.messages))
        .filter(MessageThread.id == thread_id)
        .first()
    )
    if not thread or user_id not in _participant_ids(thread):
        return None
    others = [p.user_id for p in thread.participants if p.user_id != user_id]
    other_id = others[0] if others else None
    prop_ctx = _property_context(db, thread)
    gov_status = prop_ctx.get("gov_verification_status") if prop_ctx else None
    peer = peer_profile(db, other_id, gov_status) if other_id else None
    me = db.query(User).filter(User.id == user_id).first()
    return {
        "thread_id": thread.id,
        "thread_type": _thread_type_value(thread),
        "title": thread.listing_title or thread.subject or (prop_ctx or {}).get("title"),
        "property": prop_ctx,
        "peer": peer,
        "my_trust_score": compute_trust_score(me),
        "my_badges": user_badges(me),
        "quick_actions": _quick_actions(_thread_type_value(thread), me.role.value if me and hasattr(me.role, "value") else None),
    }


def _quick_actions(thread_type: str, role: str | None) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if role == "tenant":
        actions.extend(
            [
                {"id": "pay_rent", "label": "Pay Rent"},
                {"id": "view_contract", "label": "View Contract"},
                {"id": "book_inspection", "label": "Book Inspection"},
                {"id": "report_issue", "label": "Report Issue"},
            ]
        )
    if role == "landlord":
        actions.extend(
            [
                {"id": "view_property", "label": "View Property"},
                {"id": "view_contract", "label": "View Contract"},
            ]
        )
    if thread_type == ThreadType.escrow.value:
        actions.insert(0, {"id": "escrow_status", "label": "Escrow Status"})
    return actions


def archive_thread(db: Session, thread_id: int, user_id: int, archived: bool = True) -> bool:
    thread = db.query(MessageThread).options(joinedload(MessageThread.participants)).filter(MessageThread.id == thread_id).first()
    if not thread or user_id not in _participant_ids(thread):
        return False
    thread.archived_at = datetime.utcnow() if archived else None
    db.commit()
    return True


def start_from_unit(
    db: Session,
    sender_id: int,
    unit_id: int,
    body: str,
    *,
    thread_type: ThreadType = ThreadType.inquiry,
) -> Tuple[MessageThread, Message]:
    unit = db.query(Unit).options(joinedload(Unit.parent_property)).filter(Unit.id == unit_id).first()
    if not unit:
        raise ValueError("unit_not_found")
    prop = unit.parent_property
    if not prop:
        raise ValueError("property_not_found")
    landlord_id = prop.owner_id
    if landlord_id == sender_id:
        raise ValueError("cannot_message_self")
    title = f"{prop.name} — {unit.unit_number or 'Unit'}"
    is_new = find_thread_for_pair_and_unit(db, sender_id, landlord_id, unit_id) is None
    thread = ensure_thread(
        db,
        sender_id,
        landlord_id,
        unit_id,
        subject=title,
        property_id=prop.id,
        thread_type=thread_type,
        listing_title=prop.name,
    )
    msg = append_message(db, thread.id, sender_id, body)
    if is_new:
        post_system_message(
            db,
            thread.id,
            "thread_opened",
            f"Property chat started for {title}. Messages may be recorded for trust and compliance.",
        )
    return thread, msg


def save_attachment(upload_dir: str, thread_id: int, filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower() or ".bin"
    safe = f"{thread_id}_{uuid.uuid4().hex}{ext}"
    return save_media(
        content=content,
        folder=f"messages/{thread_id}",
        filename=safe,
        upload_dir=upload_dir,
    )
