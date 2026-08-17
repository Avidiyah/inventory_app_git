"""HTTP routes for the `/tools` resource.

Layer: routers (FastAPI). Thin handlers only -- mirrors
`app/routers/items.py`'s style. Role gates:

- Create / edit / archive / checkout: TechFM OA+ (tools are a TechFM-OA-controlled
  crib; checkout is explicitly TechFM OA+).
- List / lookup / return: any authenticated user (any role can view the
  Tools page and process a return).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError
from app.models import Tool, User
from app.routers._errors import to_http
from app.schemas.tools import (
    ToolAdjustCreate,
    ToolCheckoutCreate,
    ToolCreate,
    ToolCustodyEntry,
    ToolResponse,
    ToolReturnCreate,
    ToolUpdate,
)
from app.services import tools as tools_service

router = APIRouter(prefix="/tools", tags=["tools"])


def _tool_response(db: Session, tool: Tool) -> ToolResponse:
    """Serialise a tool with its current custody breakdown. `custody` is
    computed (not an ORM relationship), so it's set explicitly here --
    mirrors `routers/items.py::_item_response` filling `barcodes` from the
    `alt_barcodes` relationship."""
    resp = ToolResponse.model_validate(tool)
    resp.custody = [
        ToolCustodyEntry(user_id=uid, user_name=name, quantity=qty)
        for uid, name, qty in tools_service.tool_custody(db, tool.id)
    ]
    return resp


@router.post("/", response_model=ToolResponse, status_code=201)
def create_tool(
    payload: ToolCreate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Create a tool. TechFM OA+ only. 400 on a live duplicate barcode."""
    try:
        tool = tools_service.create_tool(
            db, barcode=payload.barcode, name=payload.name, quantity=payload.quantity
        )
        return _tool_response(db, tool)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/", response_model=list[ToolResponse])
def list_tools(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return every live tool, newest first, with current custody. Any
    logged-in user."""
    return [_tool_response(db, tool) for tool in tools_service.list_tools(db)]


@router.get("/{barcode}", response_model=ToolResponse)
def get_tool_by_barcode(
    barcode: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lookup by barcode for the Tools-page scanner. Any logged-in user.
    404 if unknown."""
    try:
        tool = tools_service.get_tool_by_barcode(db, barcode)
        return _tool_response(db, tool)
    except DomainError as exc:
        raise to_http(exc)


@router.patch("/{tool_id}", response_model=ToolResponse)
def update_tool(
    tool_id: uuid.UUID,
    payload: ToolUpdate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Partially edit barcode and/or name. TechFM OA+ only. 404 if unknown;
    400 on a live duplicate barcode."""
    try:
        tool = tools_service.update_tool(
            db, tool_id, **payload.model_dump(exclude_unset=True)
        )
        return _tool_response(db, tool)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{tool_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def delete_tool(tool_id: uuid.UUID, db: Session = Depends(get_db)):
    """Soft-delete a tool. TechFM OA+ only. 404 if unknown; 400 while any
    user has an outstanding custody balance for the tool."""
    try:
        tools_service.delete_tool(db, tool_id)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{tool_id}/checkout", response_model=ToolResponse, status_code=201)
def checkout_tool(
    tool_id: uuid.UUID,
    payload: ToolCheckoutCreate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Check a tool out to an active `assigned_to_id`. TechFM OA+ only. 404 if
    the tool or active target user is unknown; 400 if `quantity` exceeds
    on-hand."""
    try:
        tools_service.checkout_tool(
            db,
            tool_id,
            quantity=payload.quantity,
            assigned_to_id=payload.assigned_to_id,
            performed_by_id=user.id,
            work_order_id=payload.work_order_id,
            work_order_number=payload.work_order_number,
        )
        return _tool_response(db, tools_service.get_tool(db, tool_id))
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{tool_id}/adjust", response_model=ToolResponse, status_code=201)
def adjust_tool(
    tool_id: uuid.UUID,
    payload: ToolAdjustCreate,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """"Correct Count": set the tool's on-hand quantity to an absolute
    value with a required reason. TechFM OA+ only, mirrors
    `POST /transactions/adjust`. 404 if unknown; 400 if `new_quantity`
    equals the current quantity (no-op)."""
    try:
        tools_service.adjust_tool_quantity(
            db,
            tool_id,
            new_quantity=payload.new_quantity,
            reason=payload.reason,
            performed_by_id=user.id,
        )
        return _tool_response(db, tools_service.get_tool(db, tool_id))
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{tool_id}/return", response_model=ToolResponse, status_code=201)
def return_tool(
    tool_id: uuid.UUID,
    payload: ToolReturnCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a tool from `assigned_to_id`'s custody. Any logged-in user.
    404 if unknown; 400 if `quantity` exceeds that user's outstanding
    balance for this tool."""
    try:
        tools_service.return_tool(
            db,
            tool_id,
            quantity=payload.quantity,
            assigned_to_id=payload.assigned_to_id,
            performed_by_id=user.id,
            work_order_id=payload.work_order_id,
            work_order_number=payload.work_order_number,
        )
        return _tool_response(db, tools_service.get_tool(db, tool_id))
    except DomainError as exc:
        raise to_http(exc)
