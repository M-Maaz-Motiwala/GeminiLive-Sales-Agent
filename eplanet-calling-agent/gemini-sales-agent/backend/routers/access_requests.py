"""Access-request CRUD for Google OAuth self-registration approval workflow."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_current_user, require_org_head_or_admin
from backend.db.database import get_db
from backend.db.models import (
    User, UserRole, Organization,
    UserAccessRequest, AccessRequestStatus,
)

router = APIRouter(prefix="/api/access-requests", tags=["access-requests"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class AccessRequestIn(BaseModel):
    organization_id: int
    full_name: str
    designation: str


class AccessRequestOut(BaseModel):
    id: int
    user_id: int
    email: str
    full_name: str
    designation: str
    organization_id: int
    organization_name: str
    status: str
    created_at: datetime | None = None
    reviewed_at: datetime | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _request_out(req: UserAccessRequest) -> dict:
    return {
        "id": req.id,
        "user_id": req.user_id,
        "email": req.user.email if req.user else "",
        "full_name": req.full_name,
        "designation": req.designation,
        "organization_id": req.organization_id,
        "organization_name": req.organization.name if req.organization else "",
        "status": req.status.value if req.status else "pending",
        "created_at": req.created_at,
        "reviewed_at": req.reviewed_at,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("")
async def create_access_request(
    body: AccessRequestIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit an access request (any authenticated but unapproved user)."""
    if user.is_approved:
        raise HTTPException(400, "You are already approved")

    # Validate organization exists
    org = await db.get(Organization, body.organization_id)
    if not org or not org.is_active:
        raise HTTPException(404, "Organization not found or inactive")

    # Check for existing pending request
    existing = await db.execute(
        select(UserAccessRequest).where(
            UserAccessRequest.user_id == user.id,
            UserAccessRequest.status == AccessRequestStatus.pending,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "You already have a pending access request")

    req = UserAccessRequest(
        user_id=user.id,
        organization_id=body.organization_id,
        full_name=body.full_name,
        designation=body.designation,
    )
    db.add(req)

    # Update user profile fields immediately
    user.full_name = body.full_name
    user.designation = body.designation

    await db.flush()
    await db.commit()
    await db.refresh(req, ["user", "organization"])
    return _request_out(req)


@router.get("")
async def list_access_requests(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_org_head_or_admin),
):
    """List access requests. Admin sees all; org_head sees only their org."""
    query = select(UserAccessRequest)

    if user.role == UserRole.org_head:
        query = query.where(UserAccessRequest.organization_id == user.organization_id)

    if status:
        try:
            status_enum = AccessRequestStatus(status)
            query = query.where(UserAccessRequest.status == status_enum)
        except ValueError:
            pass

    query = query.order_by(UserAccessRequest.created_at.desc())
    result = await db.execute(query)
    requests = result.scalars().all()

    # Eagerly load relationships
    for req in requests:
        await db.refresh(req, ["user", "organization"])

    return [_request_out(r) for r in requests]


@router.get("/count")
async def access_request_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_org_head_or_admin),
):
    """Return count of pending requests (for notification badge)."""
    query = select(func.count(UserAccessRequest.id)).where(
        UserAccessRequest.status == AccessRequestStatus.pending,
    )
    if user.role == UserRole.org_head:
        query = query.where(UserAccessRequest.organization_id == user.organization_id)

    result = await db.execute(query)
    return {"count": result.scalar() or 0}


@router.patch("/{request_id}/approve")
async def approve_access_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    reviewer: User = Depends(require_org_head_or_admin),
):
    """Approve an access request. Admin can approve any; org_head their org only."""
    req = await db.get(UserAccessRequest, request_id)
    if not req:
        raise HTTPException(404, "Access request not found")
    if req.status != AccessRequestStatus.pending:
        raise HTTPException(400, f"Request is already {req.status.value}")

    # Org_head can only approve requests for their own org
    if reviewer.role == UserRole.org_head and req.organization_id != reviewer.organization_id:
        raise HTTPException(403, "You can only approve requests for your organization")

    req.status = AccessRequestStatus.approved
    req.reviewed_by_id = reviewer.id
    req.reviewed_at = datetime.now(timezone.utc)

    # Activate the user
    target_user = await db.get(User, req.user_id)
    if target_user:
        target_user.is_approved = True
        target_user.organization_id = req.organization_id
        target_user.designation = req.designation
        target_user.full_name = req.full_name
        if target_user.role == UserRole.user:
            # Keep as user; admin can later promote to org_head
            pass

    await db.flush()
    await db.commit()
    await db.refresh(req, ["user", "organization"])
    return _request_out(req)


@router.patch("/{request_id}/reject")
async def reject_access_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    reviewer: User = Depends(require_org_head_or_admin),
):
    """Reject an access request."""
    req = await db.get(UserAccessRequest, request_id)
    if not req:
        raise HTTPException(404, "Access request not found")
    if req.status != AccessRequestStatus.pending:
        raise HTTPException(400, f"Request is already {req.status.value}")

    if reviewer.role == UserRole.org_head and req.organization_id != reviewer.organization_id:
        raise HTTPException(403, "You can only reject requests for your organization")

    req.status = AccessRequestStatus.rejected
    req.reviewed_by_id = reviewer.id
    req.reviewed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.commit()
    await db.refresh(req, ["user", "organization"])
    return _request_out(req)
