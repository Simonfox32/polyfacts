import os

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes import auth, claims, clips, comments, media, search, sessions, user_features

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
)
log = structlog.get_logger()

app = FastAPI(
    title="Polyfacts API",
    description="Political literacy fact-check overlay",
    version="0.1.0",
)

cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(clips.router)
app.include_router(auth.router)
app.include_router(claims.router)
app.include_router(sessions.router)
app.include_router(media.router)
app.include_router(comments.router)
app.include_router(search.router)
app.include_router(user_features.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": settings.app_name, "version": "0.1.0"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
