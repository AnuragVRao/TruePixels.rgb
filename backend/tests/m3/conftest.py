"""
Pytest configuration and fixtures for TruePixels.rgb Module M3 test suite.
"""
from __future__ import annotations
import os
import pytest
from datetime import datetime, timezone, timedelta
from fastapi import Depends, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.shared.db import Base, get_db
from app.shared.deps import current_session
from app.shared.errors import AppException
from app.shared.schemas import SessionContext
from app.main import app
from app.m3_results.router_reports import report_session
from app.m3_results.models import LogEntry
from app.stubs.m1_stub import create_dummy_user, create_dummy_image, prepare_model_input
from app.stubs.m2_stub import seed_dummy_models, run_detection


# INTEGRATION: M3's mock session table used to live in app/shared/deps.py and
# served the whole app. The app now authenticates through M1's real JWT
# sessions, so the mock lives here, and only for this suite: the `client`
# fixture below overrides M1's current_session with it. Test files keep their
# "Bearer test-user-token-1" headers unchanged. See changes.md.
ACTIVE_SESSIONS: dict[str, SessionContext] = {
    "test-user-token-1": SessionContext(
        user_id=1,
        email="user1@nitk.edu.in",
        role="User",
        account_status="active",
        session_token="test-user-token-1",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ),
    "test-user-token-2": SessionContext(
        user_id=2,
        email="user2@nitk.edu.in",
        role="User",
        account_status="active",
        session_token="test-user-token-2",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ),
    "test-admin-token-1": SessionContext(
        user_id=999,
        email="admin@nitk.edu.in",
        role="Admin",
        account_status="active",
        session_token="test-admin-token-1",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ),
    "test-disabled-token": SessionContext(
        user_id=3,
        email="disabled@nitk.edu.in",
        role="User",
        account_status="disabled",
        session_token="test-disabled-token",
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ),
}


def _resolve_mock_token(token: str | None) -> SessionContext:
    """M3's original mock current_session logic, unchanged."""
    session = ACTIVE_SESSIONS.get(token) if token else None
    if not session:
        raise AppException(code="AUTH_TOKEN_INVALID", message="Session token is invalid or expired.", status_code=401)
    if session.expires_at < datetime.now(timezone.utc):
        raise AppException(code="AUTH_TOKEN_INVALID", message="Session token has expired.", status_code=401)
    if session.account_status != "active":
        raise AppException(code="AUTH_ACCOUNT_DISABLED", message="Account is disabled or removed.", status_code=403)
    return session


def mock_current_session(authorization: str | None = Header(default=None)) -> SessionContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(code="AUTH_TOKEN_INVALID", message="Missing or malformed Authorization header.", status_code=401)
    return _resolve_mock_token(authorization.split(" ", 1)[1].strip())


def mock_report_session(
    token: str | None = None,
    authorization: str | None = Header(default=None),
) -> SessionContext:
    if authorization and authorization.startswith("Bearer "):
        return _resolve_mock_token(authorization.split(" ", 1)[1].strip())
    return _resolve_mock_token(token)


# Create isolated in-memory SQLite database for test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine_test = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


@pytest.fixture(scope="session", autouse=True)
def setup_test_directories(tmp_path_factory):
    # INTEGRATION: run from a scratch directory, so the relative ./uploads
    # paths below do not land in the repository.
    previous_cwd = os.getcwd()
    os.chdir(tmp_path_factory.mktemp("m3"))
    os.makedirs("./uploads/test_images", exist_ok=True)
    os.makedirs("./uploads/test_xai", exist_ok=True)
    os.makedirs("./uploads/test_tensors", exist_ok=True)
    yield
    os.chdir(previous_cwd)


@pytest.fixture
def db_session():
    """Yields a clean database session for each test."""
    Base.metadata.create_all(bind=engine_test)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine_test)


@pytest.fixture
def seeded_db(db_session):
    """Populates db with User A, User B, Admin, predictions, and initial logs."""
    # Seed users
    user_a = create_dummy_user(db_session, email="user1@nitk.edu.in", role="User")
    user_b = create_dummy_user(db_session, email="user2@nitk.edu.in", role="User")
    admin = create_dummy_user(db_session, email="admin@nitk.edu.in", role="Admin")

    # Sync mock token user IDs
    ACTIVE_SESSIONS["test-user-token-1"].user_id = user_a.user_id
    ACTIVE_SESSIONS["test-user-token-2"].user_id = user_b.user_id
    ACTIVE_SESSIONS["test-admin-token-1"].user_id = admin.user_id

    # Seed model
    seed_dummy_models(db_session)

    session_a = ACTIVE_SESSIONS["test-user-token-1"]
    session_b = ACTIVE_SESSIONS["test-user-token-2"]

    # 3 Predictions for User A
    a_preds = []
    for i in range(1, 4):
        img = create_dummy_image(db_session, user_id=user_a.user_id, width=800, height=600, storage_dir="./uploads/test_images")
        prep = prepare_model_input(img.image_id, session_a, db_session, tensor_dir="./uploads/test_tensors")
        pred_out = run_detection(prep, db_session, xai_requested=True)
        a_preds.append(pred_out)

    # 2 Predictions for User B
    b_preds = []
    for i in range(1, 3):
        img = create_dummy_image(db_session, user_id=user_b.user_id, width=1200, height=800, storage_dir="./uploads/test_images")
        prep = prepare_model_input(img.image_id, session_b, db_session, tensor_dir="./uploads/test_tensors")
        pred_out = run_detection(prep, db_session, xai_requested=True)
        b_preds.append(pred_out)

    # Seed initial logs for test visibility
    init_log = LogEntry(
        user_id=admin.user_id,
        event_type="administrative-action",
        event_detail="Admin initialized system test fixtures",
        severity="info",
        log_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(init_log)
    db_session.commit()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "admin": admin,
        "a_preds": a_preds,
        "b_preds": b_preds,
        "db": db_session,
    }


@pytest.fixture
def client(db_session):
    """TestClient overriding get_db dependency with test database."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[current_session] = mock_current_session
    app.dependency_overrides[report_session] = mock_report_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
