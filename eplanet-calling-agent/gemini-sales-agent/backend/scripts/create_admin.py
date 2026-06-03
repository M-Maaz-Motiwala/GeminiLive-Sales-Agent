"""Creates the first admin user. Run once after DB is initialized."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import select
from backend.db.database import AsyncSessionLocal, init_db
from backend.db.models import User, UserRole
from backend.auth.service import hash_password


async def create_admin(email: str, password: str, full_name: str = "Admin"):
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            print(f"User {email} already exists.")
            return
        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"Admin user {email} created.")


if __name__ == "__main__":
    email = os.getenv("ADMIN_EMAIL", "admin@aura.ai")
    password = os.getenv("ADMIN_PASSWORD", "changeme123")
    full_name = os.getenv("ADMIN_NAME", "Admin")
    asyncio.run(create_admin(email, password, full_name))
