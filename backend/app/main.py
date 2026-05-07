from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import figures, laws, mentions, pdf, proposals, sessions, verify, ws
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/api")
app.include_router(laws.router, prefix="/api")
app.include_router(pdf.router, prefix="/api")
app.include_router(mentions.router, prefix="/api")
app.include_router(proposals.router, prefix="/api")
app.include_router(figures.router, prefix="/api")
app.include_router(verify.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"ok": True}
