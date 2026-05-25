from sqlalchemy.orm import Session
from app.models.notification import Notification, NotifType


def get_notifications(db: Session, user_id: int, limit: int = 50) -> list:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def get_unread_count(db: Session, user_id: int) -> int:
    return db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False
    ).count()


def mark_read(db: Session, notification_id: int, user_id: int):
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    ).first()
    if n:
        n.is_read = True
        db.commit()


def mark_all_read(db: Session, user_id: int):
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    notif_type: str | NotifType = "general",
    link: str | None = None,
):
    nt = notif_type
    if isinstance(nt, str):
        try:
            nt = NotifType(nt)
        except ValueError:
            nt = NotifType.general
    n = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notif_type=nt,
        link=link,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n