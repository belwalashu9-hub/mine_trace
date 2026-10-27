"""Main FastAPI application entrypoint for MineTrace."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import get_settings
from app.core.logging import logger
from app.database.connection import init_db
from app.api.routes.health import router as health_router
from app.api.routes.trade import router as trade_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.status import router as status_router
from app.api.routes.risk import router as risk_router
from app.api.routes.classification import router as classification_router
from app.api.routes.ranking import router as ranking_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.audit import router as audit_router
from app.api.routes.ai import router as ai_router
from app.api.routes.reports import router as reports_router
from app.api.routes.live import router as live_router


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    logger.info("Initializing MineTrace SQLite database schema...")
    init_db()
    logger.info("MineTrace Phase 1 Backend initialized successfully.")
    from app.geopolitical.scheduler import Model2MonitoringScheduler
    Model2MonitoringScheduler.start()
    try:
        yield
    finally:
        Model2MonitoringScheduler.stop()
    logger.info("Shutting down MineTrace Backend...")


app = FastAPI(
    title="MineTrace API",
    description=(
        "Critical Mineral Trade Integrity, Supply Chain Provenance, "
        "and Sanctions Verification Platform (Phase 1: Ingestion & Storage)."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for frontend and dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(trade_router)
app.include_router(ingestion_router)
app.include_router(status_router)
app.include_router(risk_router)
app.include_router(classification_router)
app.include_router(ranking_router)
app.include_router(evidence_router)
app.include_router(audit_router)
app.include_router(ai_router)
app.include_router(reports_router)
app.include_router(live_router)
from app.api.routes.model2_tools import router as model2_tools_router
app.include_router(model2_tools_router)



@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global catch-all exception handler providing clean, standardized error responses."""
    logger.error(f"Unhandled error processing {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred while processing the request.",
            "detail": str(exc),
            "path": request.url.path,
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
