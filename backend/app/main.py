"""FastAPI application entry point for TruePixels.rgb - M1, M2 and M3 together.

Run from the ``backend/`` directory, so that ``app`` is the top-level package:

    cd backend
    python -m uvicorn app.main:app --reload

then open http://127.0.0.1:8000/ (M3's dashboard) or http://127.0.0.1:8000/docs.

M1 and M3 each shipped their own main.py; this file merges the two with M2's.
Every router, middleware and handler they registered is registered here, with
the differences recorded in changes.md.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.m1_access.router_auth import router as auth_router
from app.m1_access.router_images import router as images_router
from app.m1_access.router_users import router as users_router
from app.m2_analysis.router_predict import router as predictions_router
from app.m3_results.router_admin import router as admin_router
from app.m3_results.router_history import router as history_router
from app.m3_results.router_reports import router as reports_router
from app.m3_results.router_results import router as results_router
from app.shared import config
from app.shared.db import init_db
from app.shared.errors import (
    AppException,
    app_exception_handler,
    global_exception_handler,
)

# M3's dashboard (a static page) lives in the repository's frontend/ tree.
M3_DASHBOARD_DIR = config.REPO_ROOT / "frontend" / "m3_dashboard"

# The static mount below needs its directory to exist at import time.
config.ensure_storage_dirs()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: storage layout (M2) and database tables D1-D6 (M1, M3)
    config.ensure_storage_dirs()
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="TruePixels.rgb API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    description=(
        "AI-generated image detection.\n\n"
        "- **Accounts and uploads** - `/api/v1/auth`, `/api/v1/images`, "
        "`/api/v1/users`.\n"
        "- **Prediction** - `POST /api/v1/predictions` with an `image_id` "
        "from `/api/v1/images`.\n"
        "- **Results and administration** - `/api/v1/results`, "
        "`/api/v1/history`, `/api/v1/reports`, `/api/v1/admin`.\n\n"
        "Predictions fuse two independently pretrained branches that read "
        "different kinds of evidence:\n\n"
        f"- **Semantic** - `{config.DETECTOR_PRIMARY}`, a fine-tune of "
        "`google/siglip2-base-patch16-224` for binary AI-vs-real "
        "classification (Apache-2.0).\n"
        f"- **Frequency-domain** - {config.DETECTOR_FREQUENCY_NAME}, "
        "*Any-Resolution AI-Generated Image Detection by Spectral Learning* "
        "(CVPR 2025): FFT low/high-pass decomposition, spectral reconstruction "
        "similarity in a frequency-pretrained ViT-B/16, attention over "
        "native-resolution patches (Apache-2.0, code and weights).\n\n"
        "**This project trains nothing.** Both models are used as published. "
        "No accuracy figure is claimed for this system: we have run no "
        "benchmark on a labelled test set, and the upstream self-reported "
        "numbers were measured on the authors' own splits.\n\n"
        "Note that `confidence_score` is confidence in the *predicted class*, "
        "not P(AI Generated). A `fusion_score` of 0.08 means **Real** at 0.92 "
        "confidence."
    ),
)

# CORS for M1's React dev server. M3's dashboard is same-origin and needs
# none. INTEGRATION (2026-09-30): this was allow_origins=["*"] WITH
# allow_credentials=True - see the note in shared/config.py for why that
# combination hands any website a signed-in user's session.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_timing_middleware(request: Request, call_next):
    """Assigns unique request_id and measures server latency (M1)."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
    return response


# Register exception handlers for contract compliance (M1; M3's were equivalent)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Shared storage (uploads, explainability panels), read-only. M3 mounted
# ./uploads at /static/uploads; see app/m3_results/urls.py.
app.mount("/static", StaticFiles(directory=str(config.STORAGE_ROOT)), name="storage")

# M1 routers under /api/v1
app.include_router(auth_router, prefix="/api/v1")
app.include_router(images_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")

# M2 router (declares its own /api/v1 prefix)
app.include_router(predictions_router)

# M3 routers under /api/v1
app.include_router(results_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def serve_frontend_dashboard():
    """Serves the interactive Module M3 web application."""
    index_path = M3_DASHBOARD_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "TruePixels.rgb API is live. See /docs."}


@app.get("/api-tester", include_in_schema=False)
@app.get("/developer", include_in_schema=False)
@app.get("/playground", include_in_schema=False)
def serve_api_tester_console():
    """Serves M3's Developer & API Seam Testing Console."""
    tester_path = M3_DASHBOARD_DIR / "api_tester.html"
    if tester_path.exists():
        return FileResponse(tester_path)
    return {"message": "API Tester Console not found."}


@app.get("/api/v1/health", tags=["Health"])
def api_health_check():
    """M3's liveness route, kept for its dashboard's diagnostics panel."""
    return {"status": "ok", "service": "TruePixels.rgb API", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health() -> dict:
    """Liveness check: device, and which pretrained models are in use.

    ``loaded`` is false until the first prediction, because both branches load
    lazily. ``ai_index`` is the output index resolved from the primary's own
    id2label; the frequency detector has no labels, so what it reports instead
    is the documented sign convention it is running under.
    """
    from app.m2_analysis import detectors, frequency_detector

    spectral = frequency_detector.frequency
    return {
        "status": "ok",
        "service": "TruePixels.rgb API",
        "version": "1.0.0",
        "device": config.DEVICE,
        "trains_models": False,
        "detectors": {
            "primary": {
                "checkpoint": detectors.primary.checkpoint,
                "loaded": detectors.primary.is_loaded,
                "ai_index": detectors.primary.ai_index,
            },
            "frequency": {
                "name": spectral.name,
                "filename": spectral.filename,
                "enabled": config.DETECTOR_FREQUENCY_ENABLED,
                "present_on_disk": spectral.present_on_disk,
                "loaded": spectral.is_loaded,
                "ai_is_positive": spectral.ai_is_positive,
                "resize_to": spectral.resize_to,
                "feature_batch": spectral.feature_batch,
            },
        },
    }
