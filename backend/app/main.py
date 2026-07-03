from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.core.config import get_settings
from app.db.seed import seed_database
from app.db.session import create_db_and_tables, engine
from app.services.media_uploads import ensure_media_directories
from sqlmodel import Session

settings = get_settings()
media_root = ensure_media_directories(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    if settings.seed_on_startup:
        with Session(engine) as session:
            seed_database(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.frontend_origin)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router, prefix=settings.api_prefix)
app.mount("/media", StaticFiles(directory=media_root), name="media")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
