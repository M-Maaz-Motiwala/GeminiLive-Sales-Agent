"""User management — approved users list, role changes, and account deletion."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.auth.deps import get_current_user, require_org_head_or_admin, require_admin
from backend.db.database import get_db
from backend.db.models import User, UserRole, Organization

router = APIRouter(prefix="/api/users", tags=["users"])


class RoleUpdateIn(BaseModel):
    role: UserRole


def _user_out(u: User, org_name: Optional[str] = None) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "designation": u.designation,
        "role": u.role.value if u.role else "user",
        "is_active": u.is_active,
        "is_approved": u.is_approved,
        "auth_provider": u.auth_provider,
        "google_picture": u.google_picture,
        "organization_id": u.organization_id,
        "organization_name": org_name,
        "created_at": u.created_at,
    }


@router.get("")
async def list_approved_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_org_head_or_admin),
):
    """List approved users. Admin sees all; org_head sees only their org."""
    q = select(User).where(User.is_approved.is_(True)).order_by(User.created_at.desc())
    if user.role == UserRole.org_head:
        q = q.where(User.organization_id == user.organization_id)
    result = await db.execute(q)
    users = result.scalars().all()

    org_ids = {u.organization_id for u in users if u.organization_id}
    org_names: dict[int, str] = {}
    if org_ids:
        org_result = await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
        org_names = {o.id: o.name for o in org_result.scalars()}

    return [_user_out(u, org_names.get(u.organization_id or -1)) for u in users]


@router.patch("/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: RoleUpdateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only: change a user's role (user | org_head | admin)."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")

    if body.role == target.role:
        return _user_out(target)

    # Promoting to org_head requires the target to have an organization.
    if body.role == UserRole.org_head and not target.organization_id:
        raise HTTPException(
            400, "Cannot promote to org_head without assigning an organization first"
        )

    # Don't allow demoting/removing the last admin.
    if target.role == UserRole.admin and body.role != UserRole.admin:
        count_result = await db.execute(
            select(User).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        active_admins = list(count_result.scalars().all())
        if len(active_admins) <= 1:
            raise HTTPException(400, "Cannot demote the last remaining admin")

    target.role = body.role
    await db.flush()
    await db.commit()

    org_name = None
    if target.organization_id:
        org = await db.get(Organization, target.organization_id)
        org_name = org.name if org else None
    return _user_out(target, org_name)


async def _count_active_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.admin, User.is_active.is_(True)
        )
    )
    return int(result.scalar() or 0)


@router.delete("/me")
async def delete_self(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Permanently delete the calling user's own account.

    Leads, contacts, sessions, campaigns, agents, and notes are preserved
    (their owner_id / created_by_id is set to NULL by the DB).
    Access requests and Google Calendar tokens are removed.
    """
    if user.role == UserRole.admin:
        if await _count_active_admins(db) <= 1:
            raise HTTPException(400, "Cannot delete the last remaining admin")

    await db.delete(user)
    await db.commit()
    return {"detail": "Account deleted"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only: permanently delete another user's account.

    Same cascade rules as self-delete. A non-admin calling user cannot delete
    themselves via this route (use DELETE /api/users/me instead).
    """
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")

    if target.id == admin.id:
        # Admin deleting themselves — enforce last-admin guard.
        if await _count_active_admins(db) <= 1:
            raise HTTPException(400, "Cannot delete the last remaining admin")

    if target.role == UserRole.admin and target.id != admin.id:
        raise HTTPException(400, "Cannot delete another admin; demote them first")

    await db.delete(target)
    await db.commit()
    return {"detail": "User deleted"}