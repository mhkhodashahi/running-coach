"""Thin HTML routes; business operations live in the existing services."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, UploadFile
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
from web.coach_page import ask_coach, coach_context
from web.plan_page import (
    apply_groups,
    create_week,
    dismiss_proposal,
    edit_plan_item,
    fresh_proposal,
    plan_context,
    revise_proposal,
    undo_coach_change,
)
from web.settings_page import (
    MAX_CSV_BYTES,
    change_goal_state,
    import_csv,
    save_goal,
    save_local_config,
    save_messages,
    save_profile,
    settings_context,
    sync_now,
    uploaded_csv,
)
from web.today import choose_intensity, create_week_proposal, save_rating, today_context
from web.trends import trends_context

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


def _day(request: Request) -> date:
    return datetime.now(ZoneInfo(request.app.state.settings.local_timezone)).date()


@router.get("/trends", response_class=HTMLResponse)
def trends(request: Request, range: int = 28):
    try:
        context = trends_context(request.app.state.settings, _day(request), range, request.app.state.llm)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(request, "trends.html", context)


@router.get("/coach", response_class=HTMLResponse)
def coach(request: Request, activity_id: int | None = None):
    try:
        context = coach_context(request.app.state.settings, _day(request), attached_id=activity_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(request, "coach.html", context)


@router.post("/coach/ask", response_class=HTMLResponse)
def coach_ask(request: Request, question: str = Form(...), activity_id: int | None = Form(None)):
    error = None
    reply = None
    try:
        reply = ask_coach(request.app.state.settings, _day(request), question, activity_id,
                          request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    try:
        context = coach_context(request.app.state.settings, _day(request), reply=reply,
                                question=question, attached_id=activity_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    context["error"] = error
    template = "components/coach_thread.html" if request.headers.get("HX-Request") == "true" else "coach.html"
    return request.app.state.templates.TemplateResponse(request, template, context)


@router.get("/plan", response_class=HTMLResponse)
def plan(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "plan.html", plan_context(request.app.state.settings, _day(request)))


@router.post("/plan/week")
def plan_week(request: Request, start: str = Form(...)):
    try:
        create_week(request.app.state.settings, _day(request), date.fromisoformat(start), request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/proposals/{proposal_id}/apply")
async def plan_apply(request: Request, proposal_id: int):
    form = await request.form()
    try:
        apply_groups(request.app.state.settings, proposal_id, form.getlist("group_ids"))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/proposals/{proposal_id}/dismiss")
def plan_dismiss(request: Request, proposal_id: int):
    try:
        dismiss_proposal(request.app.state.settings, proposal_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/proposals/{proposal_id}/revise")
def plan_revise(request: Request, proposal_id: int, revision: str = Form(...)):
    try:
        revise_proposal(request.app.state.settings, _day(request), proposal_id, revision,
                        request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/proposals/{proposal_id}/fresh")
def plan_fresh(request: Request, proposal_id: int):
    try:
        fresh_proposal(request.app.state.settings, _day(request), proposal_id, request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError, IndexError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/undo")
def plan_undo(request: Request, confirm: str = Form(...)):
    if confirm != "yes":
        raise HTTPException(400, "Confirm undo before restoring the plan")
    try:
        undo_coach_change(request.app.state.settings)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/edit/{kind}")
async def plan_edit(request: Request, kind: str):
    form = await request.form()
    try:
        edit_plan_item(request.app.state.settings, kind, dict(form))
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


def _settings(request: Request, *, message: str = "", error: str = ""):
    context = settings_context(request.app.state.settings, request.app.state.sync_state)
    context.update(message=message, error=error)
    return request.app.state.templates.TemplateResponse(request, "settings.html", context)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return _settings(request)


@router.post("/settings/messages", response_class=HTMLResponse)
async def messages_save(request: Request):
    try:
        save_messages(request.app.state.settings, dict(await request.form()))
    except (ValueError, KeyError) as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message="Message settings saved")


@router.post("/settings/profile", response_class=HTMLResponse)
async def profile_save(request: Request):
    try:
        save_profile(request.app.state.settings, dict(await request.form()))
    except (ValueError, KeyError, TypeError) as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message="Profile saved")


@router.post("/settings/config", response_class=HTMLResponse)
async def config_save(request: Request):
    data = dict(await request.form())
    try:
        key = str(data["key"])
        if key == "HR_ZONES":
            value = ("" if data.get("clear") else json.dumps([
                {"name": f"Z{index}", "lower_bpm": int(data[f"zone_{index}_lower"]),
                 "upper_bpm": int(data[f"zone_{index}_upper"]) if data.get(f"zone_{index}_upper") else None}
                for index in range(1, 6)]))
        else:
            value = str(data["value"])
        request.app.state.settings = save_local_config(request.app.state.settings, key, value)
    except (ValueError, OSError, KeyError) as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message="Setting saved")


@router.post("/settings/goals", response_class=HTMLResponse)
async def goal_save(request: Request):
    data = dict(await request.form())
    try:
        identifier = int(data["id"]) if data.get("id") else None
        save_goal(request.app.state.settings, data, identifier)
    except (ValueError, KeyError, TypeError) as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message="Goal saved")


@router.post("/settings/goals/{goal_id}/{action}", response_class=HTMLResponse)
def goal_state(request: Request, goal_id: int, action: str):
    try:
        change_goal_state(request.app.state.settings, goal_id, action)
    except ValueError as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message="Goal updated")


@router.post("/settings/sync", response_class=HTMLResponse)
def start_sync(request: Request, background_tasks: BackgroundTasks):
    settings = request.app.state.settings
    if not settings.garmin_email or not settings.garmin_password:
        return _settings(request, error="Configure Garmin credentials in .env first")
    if request.app.state.sync_state["status"] == "running":
        return _settings(request, error="A Garmin sync is already running")
    request.app.state.sync_state.update(status="running", message="Starting Garmin sync")
    background_tasks.add_task(sync_now, settings, request.app.state.sync_state)
    return _settings(request, message="Garmin sync started")


@router.get("/settings/sync/status", response_class=HTMLResponse)
def sync_status(request: Request):
    return request.app.state.templates.TemplateResponse(
        request, "components/sync_status.html", {"sync_state": request.app.state.sync_state})


@router.post("/settings/import", response_class=HTMLResponse)
async def csv_import(request: Request, activities_file: UploadFile | None = None,
                     health_file: UploadFile | None = None):
    try:
        activities = uploaded_csv(activities_file.filename, await activities_file.read(MAX_CSV_BYTES + 1)) if activities_file else None
        health = uploaded_csv(health_file.filename, await health_file.read(MAX_CSV_BYTES + 1)) if health_file else None
        result = import_csv(request.app.state.settings, activities, health)
    except (ValueError, TypeError) as exc:
        return _settings(request, error=str(exc))
    return _settings(request, message=f"Imported {result.activities_imported} activities and "
                                      f"{result.health_rows_imported} health days")
