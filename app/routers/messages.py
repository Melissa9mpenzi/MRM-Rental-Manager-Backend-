import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.conversation import ThreadType
from app.models.user import User
from app.runtime import upload_root
from app.services import conversation_service
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/messages", tags=["Rental Hub"])


class StartThreadBody(BaseModel):
    unit_id: int = Field(..., ge=1)
    body: str = Field(..., min_length=1, max_length=8000)
    thread_type: Optional[str] = Field(default="inquiry")


class PostMessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


class ArchiveBody(BaseModel):
    archived: bool = True


class BookInspectionBody(BaseModel):
    preferred_date: str = Field(..., min_length=4, max_length=32)
    preferred_time: str = Field(..., min_length=2, max_length=32)
    notes: Optional[str] = Field(default=None, max_length=2000)


ALLOWED_ATTACH = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx"}


@router.get("/threads")
def list_threads(
    folder: str = Query(default="inbox"),
    thread_type: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = conversation_service.list_threads_for_user(
        db,
        current_user.id,
        folder=folder,
        thread_type=thread_type,
        q=q,
    )
    return success_response(data=data)


@router.get("/threads/{thread_id}/context")
def thread_context(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = conversation_service.thread_context(db, thread_id, current_user.id)
    if data is None:
        raise error_response("Thread not found or access denied.", status_code=404)
    return success_response(data=data)


@router.get("/threads/{thread_id}/messages")
def thread_messages(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = conversation_service.list_messages(db, thread_id, current_user.id)
    if data is None:
        raise error_response("Thread not found or access denied.", status_code=404)
    return success_response(data=data)


@router.post("/threads/{thread_id}/read")
def mark_read(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = conversation_service.mark_thread_read(db, thread_id, current_user.id)
    if not ok:
        raise error_response("Thread not found.", status_code=404)
    return success_response(data={"read": True})


@router.post("/threads/{thread_id}/archive")
def archive_thread(
    thread_id: int,
    body: ArchiveBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = conversation_service.archive_thread(db, thread_id, current_user.id, body.archived)
    if not ok:
        raise error_response("Thread not found.", status_code=404)
    return success_response(data={"archived": body.archived})


@router.post("/threads/{thread_id}/messages", status_code=201)
def post_to_thread(
    thread_id: int,
    body: PostMessageBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        msg = conversation_service.append_message(db, thread_id, current_user.id, body.body)
    except ValueError as e:
        code = str(e)
        if code == "thread_not_found":
            raise error_response("Thread not found.", status_code=404)
        raise error_response("Access denied.", status_code=403)
    return success_response(data={"id": msg.id})


@router.post("/threads/{thread_id}/attachments", status_code=201)
async def upload_attachment(
    thread_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_ATTACH:
        raise error_response("File type not allowed. Use images or PDF.", status_code=400)
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise error_response("File too large (max 8MB).", status_code=400)
    try:
        url = conversation_service.save_attachment(upload_root(), thread_id, file.filename or "file", content)
        body = (caption or "").strip() or f"Shared {file.filename or 'attachment'}"
        msg = conversation_service.append_message(
            db,
            thread_id,
            current_user.id,
            body,
            attachment_url=url,
            attachment_name=file.filename,
            attachment_mime=file.content_type,
        )
    except ValueError as e:
        if str(e) == "thread_not_found":
            raise error_response("Thread not found.", status_code=404)
        raise error_response("Access denied.", status_code=403)
    return success_response(data={"id": msg.id, "attachment_url": url})


@router.post("/threads/{thread_id}/book-inspection", status_code=201)
def book_inspection(
    thread_id: int,
    body: BookInspectionBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    text = (
        f"📅 Inspection request\nPreferred: {body.preferred_date} at {body.preferred_time}"
        + (f"\nNotes: {body.notes}" if body.notes else "")
    )
    try:
        msg = conversation_service.append_message(db, thread_id, current_user.id, text)
        conversation_service.post_system_message(
            db,
            thread_id,
            "inspection_requested",
            "Inspection request logged. The landlord or agent will confirm a slot.",
        )
    except ValueError:
        raise error_response("Thread not found or access denied.", status_code=404)
    return success_response(data={"id": msg.id})


@router.post("/start", status_code=201)
def start_thread(
    body: StartThreadBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tt = ThreadType.inquiry
    if body.thread_type:
        try:
            tt = ThreadType(body.thread_type)
        except ValueError:
            tt = ThreadType.inquiry
    try:
        thread, msg = conversation_service.start_from_unit(
            db, current_user.id, body.unit_id, body.body, thread_type=tt
        )
    except ValueError as e:
        code = str(e)
        if code == "unit_not_found":
            raise error_response("Listing not found.", status_code=404)
        if code == "property_not_found":
            raise error_response("Property not found.", status_code=404)
        if code == "cannot_message_self":
            raise error_response("You cannot message your own listing.", status_code=400)
        raise error_response("Could not start conversation.", status_code=400)
    return success_response(data={"thread_id": thread.id, "message_id": msg.id})
