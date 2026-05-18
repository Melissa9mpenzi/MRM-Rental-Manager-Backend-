from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models.conversation import Message, MessageThread, ThreadParticipant
from app.models.property import Unit
from app.models.user import User


def _participant_ids(thread: MessageThread) -> set[int]:
    return {p.user_id for p in thread.participants}


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


def ensure_thread(db: Session, user_a: int, user_b: int, unit_id: Optional[int], subject: Optional[str] = None) -> MessageThread:
    existing = find_thread_for_pair_and_unit(db, user_a, user_b, unit_id)
    if existing:
        return existing
    t = MessageThread(unit_id=unit_id, subject=subject)
    db.add(t)
    db.flush()
    db.add(ThreadParticipant(thread_id=t.id, user_id=user_a))
    db.add(ThreadParticipant(thread_id=t.id, user_id=user_b))
    db.commit()
    db.refresh(t)
    return t


def append_message(db: Session, thread_id: int, sender_id: int, body: str) -> Message:
    thread = (
        db.query(MessageThread)
        .options(joinedload(MessageThread.participants))
        .filter(MessageThread.id == thread_id)
        .first()
    )
    if not thread:
        raise ValueError("thread_not_found")
    part = {p.user_id for p in thread.participants}
    if sender_id not in part:
        raise ValueError("forbidden")
    m = Message(thread_id=thread_id, sender_id=sender_id, body=body.strip())
    db.add(m)
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return m


def list_threads_for_user(db: Session, user_id: int) -> List[dict[str, Any]]:
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
        .options(
            joinedload(MessageThread.participants),
            joinedload(MessageThread.messages),
        )
        .order_by(MessageThread.updated_at.desc())
        .all()
    )
    out: List[dict[str, Any]] = []
    for t in rows:
        others = [p.user_id for p in t.participants if p.user_id != user_id]
        other_name = "Conversation"
        if others:
            u = db.query(User).filter(User.id == others[0]).first()
            other_name = u.full_name if u else other_name
        last = ""
        last_time = ""
        if t.messages:
            lm = max(t.messages, key=lambda m: m.created_at or datetime.min)
            last = (lm.body or "")[:120]
            last_time = lm.created_at.isoformat() if lm.created_at else ""
        out.append(
            {
                "id": t.id,
                "unit_id": t.unit_id,
                "subject": t.subject or other_name,
                "peer_name": other_name,
                "last_preview": last,
                "last_at": last_time,
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
    msgs = sorted(thread.messages, key=lambda m: m.id)
    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "me": m.sender_id == user_id,
            "text": m.body,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in msgs
    ]


def start_from_unit(db: Session, sender_id: int, unit_id: int, body: str) -> Tuple[MessageThread, Message]:
    unit = db.query(Unit).options(joinedload(Unit.parent_property)).filter(Unit.id == unit_id).first()
    if not unit:
        raise ValueError("unit_not_found")
    prop = unit.parent_property
    if not prop:
        raise ValueError("property_not_found")
    landlord_id = prop.owner_id
    if landlord_id == sender_id:
        raise ValueError("cannot_message_self")
    thread = ensure_thread(db, sender_id, landlord_id, unit_id, subject=f"Unit {unit.unit_number} · {prop.name}")
    msg = append_message(db, thread.id, sender_id, body)
    return thread, msg
