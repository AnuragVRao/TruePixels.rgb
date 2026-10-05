"""The scratch-database guard (Phase 6-pre): CREATE DATABASE / schema resets
happen ONLY for names ending in _test or _regression - never the development
database. Checked before any connection is opened (the URLs below point at a
port nothing listens on, and create_engine is booby-trapped)."""

from __future__ import annotations

import importlib.util
import os

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url

from app.shared import db as database

BASE = "postgresql+psycopg://someone:not-a-real-password@127.0.0.1:1"
REFUSED = ["truepixels", "postgres", "truepixels_prod", "truepixels_test_backup",
           "regression", "truepixels_regression_old", "TRUEPIXELS_TEST"]


def _load_regression_check():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "evaluation", "regression_check.py")
    spec = importlib.util.spec_from_file_location("regression_check_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_connections(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a connection was attempted for a refused name")
    monkeypatch.setattr(sqlalchemy, "create_engine", refuse)


@pytest.mark.parametrize("name", REFUSED)
def test_create_database_is_refused_without_the_scratch_suffix(name, no_connections):
    with pytest.raises(RuntimeError, match="not a scratch database|lower-case"):
        database.ensure_scratch_database_exists(make_url(f"{BASE}/{name}"))


@pytest.mark.parametrize("name", REFUSED)
def test_regression_check_refuses_the_name_before_touching_anything(name, no_connections, monkeypatch):
    before = {k: os.environ.get(k) for k in ("DATABASE_URL", "STORAGE_DIR")}
    regression_check = _load_regression_check()
    with pytest.raises(SystemExit, match="scratch database"):
        regression_check.run(f"{BASE}/{name}")
    assert {k: os.environ.get(k) for k in before} == before  # nothing re-pointed


def test_the_development_database_name_is_refused_by_both():
    """The name in backend/.env.example (and compose) is plain 'truepixels'."""
    assert "truepixels" in REFUSED


@pytest.mark.parametrize("name", ["truepixels_test", "truepixels_regression", "x_regression"])
def test_scratch_names_pass_the_guard(name):
    database.refuse_unless_scratch(make_url(f"{BASE}/{name}"))  # no exception
