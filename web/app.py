"""FastAPI assembly, optional password gate and read-only startup check."""

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import Settings, get_settings
from db.setup import require_current_database
from web.routes.pages import router

WEB_DIR = Path(__file__).resolve().parent


def create_app(settings: Settings | None = None, *, password: str | None = None, llm: object = None) -> FastAPI:
    settings = settings or get_settings()
    password = os.getenv("WEB_PASSWORD", "") if password is None else password

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        require_current_database(settings.db_path)
        yield

    application = FastAPI(title="Pulse Coach", lifespan=lifespan)
    application.state.settings = settings
    application.state.llm = llm
    application.state.sync_state = {"status": "idle", "message": "No sync started"}
    application.state.templates = Jinja2Templates(directory=WEB_DIR / "templates")
    application.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @application.middleware("http")
    async def password_gate(request: Request, call_next):
        if password and not request.url.path.startswith("/static/") and request.url.path != "/login" \
                and not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    application.add_middleware(SessionMiddleware, secret_key=os.getenv("WEB_SESSION_SECRET") or secrets.token_hex(32),
                               same_site="strict", https_only=False)

    @application.get("/login")
    def login_page(request: Request):
        return application.state.templates.TemplateResponse(request, "login.html", {"error": False})

    @application.post("/login")
    def login(request: Request, submitted_password: str = Form(...)):
        if password and secrets.compare_digest(submitted_password, password):
            request.session["authenticated"] = True
            return RedirectResponse("/", status_code=303)
        return application.state.templates.TemplateResponse(request, "login.html", {"error": True}, status_code=401)

    @application.post("/theme")
    def theme(request: Request, theme: str = Form(...)):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("theme", theme if theme in {"night", "day"} else "night", samesite="strict", httponly=True)
        return response

    application.include_router(router)
    return application


app = create_app()
