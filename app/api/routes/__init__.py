"""API routes package."""
from app.api.routes.health import router as health_router
from app.api.routes.trade import router as trade_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.status import router as status_router
from app.api.routes.risk import router as risk_router
from app.api.routes.classification import router as classification_router

__all__ = [
    "health_router",
    "trade_router",
    "ingestion_router",
    "status_router",
    "risk_router",
    "classification_router",
]
