#!/usr/bin/env python
"""Set an admin user's password in whatever DB `DATABASE_URL` points at.

    DATABASE_URL='postgresql://...' python scripts/set_admin_password.py <email> <new_password>

If the user doesn't exist it is created as a superadmin (country NULL).
"""
import asyncio
import sys

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import AdminUser
from app.admin.auth import hash_password


async def main(email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(AdminUser).where(AdminUser.email == email))).scalar_one_or_none()
        if user is None:
            db.add(AdminUser(email=email, password_hash=hash_password(password),
                             role="superadmin", country=None))
            print(f"created superadmin {email}")
        else:
            user.password_hash = hash_password(password)
            print(f"updated password for {email} (role={user.role}, country={user.country})")
        await db.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/set_admin_password.py <email> <new_password>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
