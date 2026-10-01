"""Pytest configuration, test fixtures, and SQLite in-memory test database."""
import io
import os
import shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Force testing configuration
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["EMAIL_BACKEND"] = "console"
os.environ["REQUIRE_2FA"] = "False"

from app.main import app
from app.m1_access.models import User
from app.m1_access.security import hash_password, create_session_token
from app.shared.db import Base, get_db

TEST_STORAGE_DIR = Path("./test_storage")


@pytest.fixture(scope="session", autouse=True)
def setup_test_storage():
    TEST_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if TEST_STORAGE_DIR.exists():
        shutil.rmtree(TEST_STORAGE_DIR)


@pytest.fixture(scope="function")
def db_session():
    """Creates a fresh in-memory SQLite database for each test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """TestClient that overrides the get_db dependency with test db_session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session):
    user = User(
        full_name="Amogh Gowda",
        email="amogh@nitk.edu.in",
        password_hash=hash_password("SecretPassword123"),
        role="User",
        account_status="active",
        is_email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_admin(db_session):
    admin = User(
        full_name="Admin User",
        email="admin@truepixels.rgb",
        password_hash=hash_password("AdminSecurePassword123"),
        role="Admin",
        account_status="active",
        is_email_verified=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def user_auth_headers(sample_user):
    token, _, _ = create_session_token(sample_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(sample_admin):
    token, _, _ = create_session_token(sample_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_jpeg_bytes():
    """Generates a valid 256x256 RGB JPEG image in bytes."""
    img = Image.new("RGB", (256, 256), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def sample_png_bytes():
    """Generates a valid 256x256 RGBA PNG image in bytes."""
    img = Image.new("RGBA", (256, 256), color=(255, 100, 50, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
