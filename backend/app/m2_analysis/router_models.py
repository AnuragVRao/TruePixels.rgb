"""Contract C4 - model management (Phase 4, F.19). Admin only.

    GET  /api/v1/models                    every D3 row, with the ACTIVE configuration marked
    POST /api/v1/models                    register an artefact (multipart) - inactive
    POST /api/v1/models/{id}/activate      canary + quality gate + atomic switch
    POST /api/v1/models/rollback           return a type to its previous active model
    GET  /api/v1/models/activations        the activation history (audit trail)

Every call is audit-logged (D6 administrative-action). Artefact files are
never served by any route. M3's admin "activate" delegates here.
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.m2_analysis import model_artifacts, registry
from app.m2_analysis.models import ModelActivation, ModelRegistry
from app.m2_analysis.registry import RegistryError
from app.shared.db import get_db
from app.shared.deps import require_role
from app.shared.logging import emit
from app.shared.schemas import SessionContext

router = APIRouter(prefix="/models", tags=["Model Management (F.19)"])


def _error(exc: RegistryError) -> JSONResponse:
    body = {"error": {"code": exc.code, "message": exc.message, "request_id": None}}
    body.update(exc.detail)
    return JSONResponse(status_code=exc.status, content=body)


def _row(m: ModelRegistry) -> dict:
    h = m.hyperparameters or {}
    head = h.get("head")
    return {
        "model_id": m.model_id, "model_type": m.model_type, "model_name": m.model_name,
        "model_version": m.model_version, "is_active": m.is_active,
        "artifact_sha256": m.artifact_sha256, "artifact_ref": m.artifact_ref,
        "training_reference": m.training_reference,
        "configuration": {k: v for k, v in h.items() if k != "head"},
        "head": {"sha256": head["sha256"], "id2label": head.get("id2label")} if head else None,
        "registered_at": m.registered_at.isoformat() if m.registered_at else None,
        "registered_by": m.registered_by,
    }


@router.get("")
def list_models(session: SessionContext = Depends(require_role("Admin")),
                db: Session = Depends(get_db)) -> dict:
    """All D3 rows. ``active`` is the configuration predictions run with now -
    quote metrics only together with it (training_reference names the
    configuration a published figure describes)."""
    registry.active(db)  # bootstrap the baseline if D3 is empty
    rows = db.query(ModelRegistry).order_by(ModelRegistry.model_id.desc()).all()
    return {"active": {r.model_type: _row(r) for r in rows if r.is_active},
            "models": [_row(r) for r in rows]}


@router.post("", status_code=201)
async def register_model(
    model_type: Literal["semantic-classifier", "frequency-artifact-classifier", "fusion-configuration"] = Form(...),
    name: str = Form(...),
    version: str = Form(...),
    training_reference: str = Form(...),
    id2label: Optional[str] = Form(None, description='semantic heads: JSON, e.g. {"0": "Real", "1": "AI"}'),
    ai_is_positive: Optional[bool] = Form(None, description="frequency heads: does a positive logit mean AI?"),
    file: UploadFile = File(...),
    session: SessionContext = Depends(require_role("Admin")),
    db: Session = Depends(get_db),
):
    limit = model_artifacts.MAX_BYTES.get(model_type, 0)
    data = await file.read(limit + 1)  # never read more than the limit + 1 byte
    try:
        labels = json.loads(id2label) if id2label else None
    except json.JSONDecodeError:
        return _error(RegistryError("MDL_INVALID_ARTIFACT", "id2label is not valid JSON", 422))
    try:
        row = model_artifacts.register(db, model_type=model_type, name=name, version=version,
                                       training_reference=training_reference, data=data,
                                       actor_id=session.user_id, id2label=labels,
                                       ai_is_positive=ai_is_positive)
    except RegistryError as exc:
        db.rollback()
        emit("administrative-action", f"Model upload refused ({exc.code}): {name} {version} "
             f"({model_type}): {exc.message}", severity="warning", user_id=session.user_id)
        return _error(exc)
    return _row(row)


class ActivateBody(BaseModel):
    force: bool = False
    reason: Optional[str] = None


def _activation_response(result: registry.ActivationResult) -> dict:
    return {"status": "success", "activated_model_id": result.model_id, "model_type": result.model_type,
            "previous_model_id": result.previous_model_id, "action": result.action,
            "forced": result.forced, "canary": result.canary, "gate": result.gate, "is_active": True}


def _audit(session, verb: str, result=None, exc: RegistryError | None = None, target: str = "") -> None:
    if exc is not None:
        emit("administrative-action", f"Model {verb} refused ({exc.code}) {target}: {exc.message}",
             severity="warning", user_id=session.user_id)
        return
    gate = result.gate or {}
    summary = (f"gate passed={gate.get('passed')} candidate={gate.get('candidate')} "
               f"labels_changed={gate.get('labels_changed')}")
    if result.forced:
        emit("administrative-action", f"Model {verb} FORCED past a refusing gate: #{result.model_id} "
             f"({result.model_type}), previous #{result.previous_model_id}; {summary}",
             severity="warning", user_id=session.user_id)
    else:
        emit("administrative-action", f"Model {verb}: #{result.model_id} ({result.model_type}), "
             f"previous #{result.previous_model_id}; {summary}", severity="info", user_id=session.user_id)


def activate_for(db: Session, session: SessionContext, model_id: int, force: bool = False,
                 reason: Optional[str] = None):
    """Shared by this router and M3's admin endpoint."""
    try:
        result = registry.activate(db, model_id, actor_id=session.user_id, force=force, reason=reason)
    except RegistryError as exc:
        db.rollback()
        _audit(session, "activation", exc=exc, target=f"#{model_id}")
        return _error(exc)
    _audit(session, "activation", result)
    return _activation_response(result)


@router.post("/{model_id}/activate")
def activate_model(model_id: int, body: ActivateBody = ActivateBody(),
                   session: SessionContext = Depends(require_role("Admin")),
                   db: Session = Depends(get_db)):
    return activate_for(db, session, model_id, body.force, body.reason)


class RollbackBody(BaseModel):
    model_type: Literal["semantic-classifier", "frequency-artifact-classifier", "fusion-configuration"]
    force: bool = False
    reason: Optional[str] = None


@router.post("/rollback")
def rollback_model(body: RollbackBody, session: SessionContext = Depends(require_role("Admin")),
                   db: Session = Depends(get_db)):
    try:
        result = registry.rollback(db, body.model_type, actor_id=session.user_id,
                                   force=body.force, reason=body.reason)
    except RegistryError as exc:
        db.rollback()
        _audit(session, "rollback", exc=exc, target=body.model_type)
        return _error(exc)
    _audit(session, "rollback", result)
    return _activation_response(result)


@router.get("/activations")
def list_activations(session: SessionContext = Depends(require_role("Admin")),
                     db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ModelActivation).order_by(ModelActivation.activation_id.desc()).limit(200).all()
    return [{"activation_id": a.activation_id, "model_type": a.model_type, "model_id": a.model_id,
             "previous_model_id": a.previous_model_id, "activated_by": a.activated_by,
             "activated_at": a.activated_at.isoformat(), "action": a.action, "forced": a.forced,
             "reason": a.reason, "gate": a.gate} for a in rows]
