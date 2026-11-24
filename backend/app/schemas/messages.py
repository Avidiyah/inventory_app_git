"""Live messaging request bodies.

Layer: schemas (Pydantic only). Consumed by `app/routers/messages.py`.

Request bodies only. Responses are the service's plain dicts, returned as-is
(`PersonOut`, `MessageOut`, `ConversationRow`, ... in the live-messaging spec),
so there is no second copy of those shapes to drift out of step.

Length and blank checks on `body` / `name` live in `domain/messages.py`
(`clean_body`, `clean_group_name`), not here, so the rule has one owner.
"""

import uuid

from pydantic import BaseModel


class SendMessageRequest(BaseModel):
    body: str


class MarkReadRequest(BaseModel):
    up_to: int


class OpenDirectRequest(BaseModel):
    user_id: uuid.UUID


class CreateGroupRequest(BaseModel):
    name: str
    member_ids: list[uuid.UUID]
