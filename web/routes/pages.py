"""Thin HTML routes; business operations live in the existing services."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.today import choose_intensity, save_rating, sync_label, today_context

router = APIRouter()


def _today(request: Request) -> dict:
    settings = request.app.state.settings
    day = datetime.now(ZoneInfo(settings.local_timezone)).date()
    return today_context(settings, day=day, llm=request.app.state.llm)


@router.get("/", response_class=HTMLResponse)
def today(request: Request):
    context = _today(request)
    return request.app.state.templates.TemplateResponse(request, "today.html", context)


@router.post("/today/choice", response_class=HTMLResponse)
def override(request: Request, choice: str = Form(...)):
    if choice not in ("rest", "easy", "hard", "clear"):
        raise HTTPException(400, "Invalid intensity")
    data = _today(request)
    choose_intensity(request.app.state.settings, data["day"], None if choice == "clear" else choice)
    if request.headers.get("HX-Request") == "true":
        return request.app.state.templates.TemplateResponse(request, "components/coach_card.html", _today(request))
    return RedirectResponse("/", status_code=303)


@router.post("/today/rate", response_class=HTMLResponse)
def rate(request: Request, activity_id: int = Form(...), rpe: int = Form(...)):
    try:
        save_rating(request.app.state.settings, activity_id, rpe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if request.headers.get("HX-Request") == "true":
        return request.app.state.templates.TemplateResponse(request, "components/rating.html", _today(request))
    return RedirectResponse("/", status_code=303)


@router.get("/{section}", response_class=HTMLResponse)
def placeholder(request: Request, section: str):
    if section not in {"activities", "trends", "coach", "plan"}:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(request, "placeholder.html", {"section": section,
        "milestone": "5b" if section == "activities" else "5c",
        "sync": sync_label(request.app.state.settings,
                           datetime.now(ZoneInfo(request.app.state.settings.local_timezone)).date())})


@router.get("/activities/{activity_id}", response_class=HTMLResponse)
def activity_placeholder(request: Request, activity_id: int):
    return request.app.state.templates.TemplateResponse(request, "placeholder.html",
        {"section": "Activity detail", "milestone": "5b",
         "sync": sync_label(request.app.state.settings,
                            datetime.now(ZoneInfo(request.app.state.settings.local_timezone)).date())})
