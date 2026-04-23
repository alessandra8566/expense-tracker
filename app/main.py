import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_tables
from app.routers.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO if settings.APP_ENV == "production" else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up — creating DB tables if needed...")
    await create_tables()
    log.info("Ready ✅")
    yield
    log.info("Shutting down.")


app = FastAPI(
    title="LINE Bot 雙人記帳系統",
    description="Two-person shared expense tracker via LINE Bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router, tags=["webhook"])


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "env": settings.APP_ENV}
