"""HTTP routes for tutorial progress: `/tutorials/progress/...`.

Layer: routers (FastAPI). Thin handlers over `app.services.tutorials`.

Who may call what:

- `GET /progress/me` and `PUT /progress/{key}` are open to any signed-in
  user. Writes always target the caller (`user.id`); no route takes a
  user id, so nobody can write another person's row.
- `GET /progress/users` is Team Lead and above, the same gate as
  `GET /users`: it feeds the "N of M tutorials" counts on the Users page.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.tutorials import ProgressEntry, ProgressEventRequest
from app.services import tutorials as tutorials_service

router = APIRouter(prefix="/tutorials", tags=["tutorials"])


@router.get("/progress/me", response_model=list[ProgressEntry])
def my_tutorial_progress(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's own progress rows."""
    return [
        ProgressEntry(key=r.script_key, seen_at=r.seen_at, completed_at=r.completed_at)
        for r in tutorials_service.list_mine(db, user.id)
    ]


@router.get(
    "/progress/users",
    response_model=dict[str, list[str]],
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
    responses={403: {"description": f"Requires the {roles.label(roles.ROLE_SUPERVISOR)} role."}},
)
def tutorial_progress_users(db: Session = Depends(get_db)):
    """`{user_id: [completed keys]}` for active users."""
    return tutorials_service.completed_by_user(db)


@router.put("/progress/{key}", status_code=204)
def record_tutorial_progress(
    key: str,
    payload: ProgressEventRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Idempotent first-write-wins record of `seen` or `completed`."""
    try:
        tutorials_service.record(db, user.id, key, payload.event)
    except DomainError as exc:
        raise to_http(exc)
    return Response(status_code=204)
