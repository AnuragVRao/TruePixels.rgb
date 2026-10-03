"""Script to seed an initial Admin account into the database.

The password comes from the SEED_ADMIN_PASSWORD environment variable. When it
is unset, a random one is generated and printed once - it is never stored in
source, so nothing in git is a working credential.
"""
import os
import secrets

from sqlalchemy import func

from app.m1_access.models import User
from app.m1_access.security import hash_password, validate_password_strength
from app.shared.db import SessionLocal, init_db

init_db()  # refuses to run unless the schema is current: cd backend && alembic upgrade head
db = SessionLocal()

admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@truepixels.rgb").strip().lower()
admin_pwd = os.getenv("SEED_ADMIN_PASSWORD")
generated = admin_pwd is None
if generated:
    # token_urlsafe(18) is 24 chars; the suffix guarantees M1's letter + digit rule.
    admin_pwd = secrets.token_urlsafe(18) + "a1"
validate_password_strength(admin_pwd)

existing = db.query(User).filter(func.lower(User.email) == admin_email).first()
if not existing:
    admin = User(
        full_name="System Administrator",
        email=admin_email,
        password_hash=hash_password(admin_pwd),
        role="Admin",
        account_status="active",
        is_email_verified=True,
    )
    db.add(admin)
    db.commit()
    print("Admin account created successfully!")
    print(f"Email:    {admin_email}")
    if generated:
        print(f"Password: {admin_pwd}")
        print("(generated - shown once; set SEED_ADMIN_PASSWORD to choose your own)")
    else:
        print("Password: the value of SEED_ADMIN_PASSWORD")
else:
    print(f"Admin account already exists: {admin_email}")

db.close()
