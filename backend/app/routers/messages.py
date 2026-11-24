"""HTTP routes for live messaging: `/messages/...`.

Layer: routers (FastAPI). Thin handlers over `app.services.messages`.

Open to every signed-in role. Access is by membership, not role: a caller who
is not in a chat gets 404 from every route that names it (the service raises
`ConversationNotFoundError`), never 403, so a chat id is not a probe for
existence. The one role rule is group creation (Team Lead and up), enforced
in the service.

Realtime and push are emitted here, after the service has committed, and are
best-effort. Neither carries message text: the socket frame names the chat,
the push names only the sender.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user
from app.database import get_db
from app.domain import messages as messages_policy
from app.domain.errors import DomainError
from app.models import User
from app.routers import _message_events
from app.routers._errors import to_http
from app.schemas.messages import (
    BroadcastRequest,
    CreateGroupRequest,
    MarkReadRequest,
    OpenDirectRequest,
    SendMessageRequest,
)
from app.services import messages as messages_service
from app.services import messages_broadcast
from app.services import notifications as notifications_service

router = APIRouter(prefix="/messages", tags=["messages"])


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


@router.get("/conversations")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's chats plus the distinct-people unread count.

    The only retention-sweep trigger (no lifespan hook): `maybe_sweep` runs at
    most once per 24 h per process, so most calls pay nothing.
    """
    try:
        messages_service.maybe_sweep(db, datetime.now(timezone.utc))
        return messages_service.list_conversations(db, user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    before: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One chat with its newest page of messages; `before` pages backwards."""
    if before is not None and before < 1:
        raise _bad("before must be a positive message id.")
    try:
        return messages_service.get_conversation(db, user, conversation_id, before=before)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        message, member_ids = messages_service.send_message(
            db, user, conversation_id, payload.body
        )
    except DomainError as exc:
        raise to_http(exc)
    _message_events.emit_message_changed(str(conversation_id), member_ids)
    notifications_service.notify_chat_message(
        background,
        recipient_ids=[m for m in member_ids if str(m) != str(user.id)],
        sender_name=user.full_name,
        conversation_id=str(conversation_id),
    )
    return message


@router.post("/broadcast", status_code=201)
def broadcast(
    payload: BroadcastRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin+: one text as a separate direct message to each person."""
    try:
        pairs = messages_broadcast.broadcast(db, user, payload.user_ids, payload.body)
    except DomainError as exc:
        raise to_http(exc)
    # ponytail: one push task per recipient; batch into one task if lists grow past ~100.
    for conversation_id, recipient_id in pairs:
        _message_events.emit_message_changed(str(conversation_id), [user.id, recipient_id])
        notifications_service.notify_chat_message(
            background,
            recipient_ids=[recipient_id],
            sender_name=user.full_name,
            conversation_id=str(conversation_id),
        )
    return {"sent": len(pairs)}


@router.post("/conversations/{conversation_id}/read")
def mark_read(
    conversation_id: uuid.UUID,
    payload: MarkReadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Advance the caller's read mark.

    Emits only when the mark moved, so two people with the same chat open
    settle after one round instead of re-reading each other forever.
    """
    if payload.up_to < 1:
        raise _bad("up_to must be a positive message id.")
    try:
        member_ids = messages_service.mark_read(db, user, conversation_id, payload.up_to)
        # The service caps `up_to` at the newest message, so report the stored mark.
        # ponytail: loads a page to read one value; add a service read_mark() if it shows in timings.
        my_read = messages_service.get_conversation(db, user, conversation_id)[
            "my_read_message_id"
        ]
    except DomainError as exc:
        raise to_http(exc)
    if member_ids:
        _message_events.emit_message_changed(str(conversation_id), member_ids)
    return {"my_read_message_id": my_read}


@router.post("/direct")
def open_direct(
    payload: OpenDirectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Find or create the one direct chat with another person."""
    try:
        conversation = messages_service.get_or_create_direct(db, user, payload.user_id)
    except DomainError as exc:
        raise to_http(exc)
    return {"id": conversation.id}


@router.post("/groups")
def create_group(
    payload: CreateGroupRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        conversation, member_ids = messages_service.create_group(
            db, user, payload.name, payload.member_ids
        )
    except DomainError as exc:
        raise to_http(exc)
    _message_events.emit_message_changed(str(conversation.id), member_ids)
    return {"id": conversation.id}


@router.delete("/groups/{conversation_id}", status_code=204)
def end_group(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        member_ids = messages_service.end_group(db, user, conversation_id)
    except DomainError as exc:
        raise to_http(exc)
    _message_events.emit_message_changed(str(conversation_id), member_ids)
    return Response(status_code=204)


@router.get("/search")
def search(
    q: str = Query(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = q.strip()
    if len(q) < messages_policy.SEARCH_MIN_CHARS:
        raise _bad(f"Type at least {messages_policy.SEARCH_MIN_CHARS} characters to search.")
    try:
        return messages_service.search(db, user, q)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/people")
def list_people(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Everyone the caller can start a chat with (active users but themselves)."""
    return {"people": messages_service.list_people(db, user)}
