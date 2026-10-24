"""Thin HTML routes; business operations live in the existing services."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web.activities import (
    add_recommendation,
    ask_activity,
    detail_context,
    generate_opinion,
    list_context,
    rate_session,
    set_planned_intent,
)
from web.today import choose_intensity, create_week_proposal, save_rating, sync_label, today_context

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


@router.post("/today/plan")
def plan_today(request: Request):
    settings = request.app.state.settings
    day = datetime.now(ZoneInfo(settings.local_timezone)).date()
    try:
        create_week_proposal(settings, day, request.app.state.llm)
    except (ValueError, PermissionError, RuntimeError) as exc:
        raise HTTPException(503, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


def _detail(request: Request, activity_id: int) -> dict:
    try:
        return detail_context(request.app.state.settings, activity_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/activities", response_class=HTMLResponse)
def activities(request: Request, sport: str = "", start: str = "", end: str = "",
               show_walks: bool = False, page: int = 1):
    try:
        context = list_context(request.app.state.settings, sport=sport or None,
                               start=date.fromisoformat(start) if start else None,
                               end=date.fromisoformat(end) if end else None,
                               show_walks=show_walks, page=page)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    template = "components/activity_weeks.html" if request.headers.get("HX-Request") == "true" else "activities.html"
    return request.app.state.templates.TemplateResponse(request, template, context)


@router.get("/activities/{activity_id}", response_class=HTMLResponse)
def activity_detail(request: Request, activity_id: int):
    return request.app.state.templates.TemplateResponse(request, "activity_detail.html", _detail(request, activity_id))


@router.post("/activities/{activity_id}/intent", response_class=HTMLResponse)
def activity_intent(request: Request, activity_id: int, planned_intent: str = Form("")):
    try:
        set_planned_intent(request.app.state.settings, activity_id, planned_intent or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if request.headers.get("HX-Request") == "true":
        context = _detail(request, activity_id)
        context["plan_changed"] = True
        return request.app.state.templates.TemplateResponse(request, "components/opinion.html", context)
    return RedirectResponse(f"/activities/{activity_id}", status_code=303)


@router.post("/activities/{activity_id}/opinion", response_class=HTMLResponse)
def activity_opinion(request: Request, activity_id: int, regenerate: bool = Form(False)):
    _detail(request, activity_id)
    error = None
    try:
        generate_opinion(request.app.state.settings, activity_id, regenerate=regenerate, llm=request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    context = _detail(request, activity_id)
    context["opinion_error"] = error
    template = "components/opinion.html" if request.headers.get("HX-Request") == "true" else "activity_detail.html"
    return request.app.state.templates.TemplateResponse(request, template, context)


@router.post("/activities/{activity_id}/recommendation/{index}")
def recommendation(request: Request, activity_id: int, index: int):
    try:
        add_recommendation(request.app.state.settings, activity_id, index)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/activities/{activity_id}/rate", response_class=HTMLResponse)
def activity_rate(request: Request, activity_id: int, rpe: int = Form(...)):
    try:
        rate_session(request.app.state.settings, activity_id, rpe)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if request.headers.get("HX-Request") == "true":
        context = _detail(request, activity_id)
        context["rating_saved"] = True
        return request.app.state.templates.TemplateResponse(request, "components/activity_rating.html", context)
    return RedirectResponse(f"/activities/{activity_id}", status_code=303)


@router.post("/activities/{activity_id}/ask", response_class=HTMLResponse)
def activity_ask(request: Request, activity_id: int, question: str = Form(...)):
    if not question.strip() or len(question) > 500:
        raise HTTPException(400, "Ask a question of at most 500 characters")
    try:
        reply = ask_activity(request.app.state.settings, activity_id, question, request.app.state.llm)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    context = {"reply": reply, "activity": {"id": activity_id}}
    if request.headers.get("HX-Request") == "true":
        return request.app.state.templates.TemplateResponse(request, "components/ask_result.html", context)
    context = _detail(request, activity_id) | context
    return request.app.state.templates.TemplateResponse(request, "activity_detail.html", context)


@router.get("/{section}", response_class=HTMLResponse)
def placeholder(request: Request, section: str):
    if section not in {"trends", "coach", "plan"}:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse(request, "placeholder.html", {"section": section,
        "milestone": "5c", "sync": sync_label(request.app.state.settings,
              datetime.now(ZoneInfo(request.app.state.settings.local_timezone)).date())})
