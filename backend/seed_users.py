"""
seed_users.py — Creates default users for all roles
Run: python seed_users.py
"""
import asyncio
import sys
from database.db import engine
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

# Force stdout/stderr to use UTF-8 to prevent UnicodeEncodeError with emojis on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from models.user import User, UserRole
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

USERS = [
    {
        "username":  "admin",
        "email":     "admin@fraudguard.com",
        "full_name": "Admin User",
        "password":  "Admin1234",
        "role":      UserRole.admin,
    },
    {
        "username":  "analyst",
        "email":     "analyst@fraudguard.com",
        "full_name": "Fraud Analyst",
        "password":  "Analyst1234",
        "role":      UserRole.analyst,
    },
    {
        "username":  "fraud_analyst",
        "email":     "fraudanalyst@fraudguard.com",
        "full_name": "Senior Fraud Analyst",
        "password":  "Fraud@1234",
        "role":      UserRole.fraud_analyst,
    },
    {
        "username":  "customer",
        "email":     "customer@fraudguard.com",
        "full_name": "John Customer",
        "password":  "Customer1234",
        "role":      UserRole.customer,
    },
    {
        "username":  "staff",
        "email":     "staff@fraudguard.com",
        "full_name": "Bank Staff",
        "password":  "Staff@1234",
        "role":      UserRole.staff,
    },
]

async def seed():
    async with AsyncSession(engine) as db:
        for u in USERS:
            result = await db.execute(select(User).where(User.username == u["username"]))
            existing = result.scalar_one_or_none()
            if existing:
                # Update password to known value
                existing.hashed_password = pwd_context.hash(u["password"])
                print(f"🔄 Updated  : {u['username']} / {u['password']} [{u['role'].value}]")
            else:
                new_user = User(
                    username       = u["username"],
                    email          = u["email"],
                    full_name      = u["full_name"],
                    hashed_password= pwd_context.hash(u["password"]),
                    role           = u["role"],
                    is_active      = True,
                )
                db.add(new_user)
                print(f"✅ Created  : {u['username']} / {u['password']} [{u['role'].value}]")
        await db.commit()

    print("\n🎉 All users ready!")
    print("─" * 45)
    print(f"{'Role':<18} {'Username':<16} {'Password'}")
    print("─" * 45)
    for u in USERS:
        print(f"{u['role'].value:<18} {u['username']:<16} {u['password']}")
    print("─" * 45)

asyncio.run(seed())
