from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import conversation_service
from app.utils.response import success_response, error_response

router = APIRouter(prefix="/messages", tags=["Messages"])


class StartThreadBody(BaseModel):
    unit_id: int = Field(..., ge=1)
    body: str = Field(..., min_length=1, max_length=8000)


class PostMessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


@router.get("/threads")
def list_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = conversation_service.list_threads_for_user(db, current_user.id)
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
        if code == "forbidden":
            raise error_response("Access denied.", status_code=403)
        raise error_response("Access denied.", status_code=403)
    return success_response(data={"id": msg.id})


@router.post("/start", status_code=201)
def start_thread(
    body: StartThreadBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        thread, msg = conversation_service.start_from_unit(db, current_user.id, body.unit_id, body.body)
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
