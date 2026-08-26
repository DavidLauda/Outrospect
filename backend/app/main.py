from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.posts import router as posts_router
from app.api.sources import router as sources_router
from app.api.stats import router as stats_router
from app.config import settings

app = FastAPI(title="Outrospect API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(posts_router)
app.include_router(stats_router)
app.include_router(sources_router)
