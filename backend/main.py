"""FastAPI 应用入口。

只负责中间件、异常处理和路由注册，不写业务逻辑。
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# CORS_ORIGINS 在导入期即被读取，因此必须先把 backend/.env 载入进程环境，
# 否则写在 .env 里的白名单不会生效（其它模块都是在函数内延迟 load_dotenv）。
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)

from backend.api import (
    assessment,
    audio,
    chat,
    communication,
    counseling,
    heal_journal,
    history,
    healing,
    profile,
    session,
    teacher,
    tts,
    vision,
)

from backend.audio.transcriber import get_transcription_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_transcription_service()
    await service.start()
    try:
        yield
    finally:
        service.close()
        get_transcription_service.cache_clear()


app = FastAPI(title="多模态心理状态筛查 Demo", version="0.3.0", lifespan=lifespan)

_default_origins = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:5174,http://127.0.0.1:5174"
)
allowed_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        error = detail
    else:
        error = {"code": "HTTP_ERROR", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": error})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request,
                                   exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {
        "code": "VALIDATION_ERROR", "message": "Invalid request data."}})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(session.router)
app.include_router(chat.router)
app.include_router(vision.router)
app.include_router(audio.router)
app.include_router(tts.router)
app.include_router(assessment.router)
app.include_router(history.router)
app.include_router(healing.router)
app.include_router(heal_journal.router)
app.include_router(counseling.router)
app.include_router(counseling.icbt_router)
app.include_router(teacher.router)
app.include_router(communication.router)
app.include_router(profile.router)
app.include_router(profile.contacts_router)
