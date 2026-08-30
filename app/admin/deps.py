from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, true
from jose import JWTError
from app.db.session import get_db
from app.db.models import AdminUser
from app.admin.auth import decode_access_token


async def get_current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> AdminUser:
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return user


async def require_superadmin(current_user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin required")
    return current_user


def scope_clause(user: AdminUser, model):
    """WHERE clause restricting `model` rows to the user's country.
    Superadmin (country is None) sees everything."""
    if user.country is None:
        return true()
    return model.country == user.country


def assert_visible(user: AdminUser, obj) -> None:
    """404 if `obj` is outside the user's country scope."""
    if user.country is None:
        return
    if getattr(obj, "country", None) != user.country:
        raise HTTPException(status_code=404, detail="Not found")
