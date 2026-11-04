"""Thin HTML routes; business operations live in the existing services."""

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from coach.session_workouts import propose_move, read_session, use_shorter_variant
from llm.base import NullLLMClient
from services.timeline_notes import delete_note, save_note
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
from web.dashboard.page import add_overview_card, one_widget
from web.dashboard.page import change as change_dashboard
from web.dashboard.page import context as dashboard_context
from web.dashboard.storage import Widget, WidgetOptions
from web.plan_page import (
    apply_change_selection,
    apply_groups,
    create_day,
    create_week,
    dismiss_proposal,
    edit_plan_item,
    fresh_proposal,
    plan_context,
    preview_changes,
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
from web.trends import insights_context
from web.view_models.coach import context_question, proposed_change_question
from web.view_models.dashboard import chart_context_summary
from web.view_models.session import session_detail

router = APIRouter()


def _today(request: Request) -> dict:
    settings = request.app.state.settings
    day = datetime.now(ZoneInfo(settings.local_timezone)).date()
    return today_context(settings, day=day, llm=NullLLMClient())


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
        return request.app.state.templates.TemplateResponse(request, "components/v2_today_call.html", _today(request))
    return RedirectResponse("/", status_code=303)


@router.post("/today/ask", response_class=HTMLResponse)
def today_ask(request: Request, question: str = Form(...)):
    question = question.strip()
    if not 1 <= len(question) <= 480:
        raise HTTPException(400, "Ask a question of at most 480 characters")
    reply = None
    error = None
    try:
        reply = ask_coach(request.app.state.settings, _day(request), f"About today: {question}", None,
                          request.app.state.llm)
        if not reply.used_llm:
            error = reply.text
            reply = None
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    return request.app.state.templates.TemplateResponse(
        request, "components/v2_coach_answer.html", {"reply": reply, "error": error})


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
def _detail(request: Request, activity_id: int, *, from_page: str = "activities") -> dict:
    try:
        return detail_context(request.app.state.settings, activity_id, from_page=from_page)
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
def activity_detail(request: Request, activity_id: int, from_page: str = Query("activities", alias="from")):
    return request.app.state.templates.TemplateResponse(
        request, "activity_detail.html", _detail(request, activity_id, from_page=from_page))


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
        context = insights_context(request.app.state.settings, _day(request), range)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(request, "trends.html", context)


@router.post("/trends/add-chart")
def trends_add_chart(request: Request, title: str = Form(...), range: int = Form(28)):
    try:
        added = add_overview_card(request.app.state.settings, title, range)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    notice = "added" if added else "exists"
    return RedirectResponse(f"/trends?range={range}&notice={notice}", status_code=303)


def _note_return(path: str) -> str:
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(path)
    if parts.scheme or parts.netloc or parts.path not in ("/", "/trends", "/insights/dashboard"):
        return "/"
    query = parse_qs(parts.query)
    value = query.get("range", [""])[0]
    return parts.path + (f"?range={value}" if value in ("7", "28", "90", "365") else "")


@router.post("/timeline-notes")
def timeline_note_save(request: Request, date_value: Annotated[date, Form()], text: Annotated[str, Form()],
                       note_id: Annotated[int | None, Form()] = None, return_to: Annotated[str, Form()] = "/"):
    if date_value > _day(request):
        raise HTTPException(400, "A timeline note cannot be dated in the future")
    settings = request.app.state.settings
    try:
        save_note(settings.db_path, settings.default_user_id, date_value, text, note_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(_note_return(return_to), status_code=303)


@router.post("/timeline-notes/{note_id}/delete")
def timeline_note_delete(request: Request, note_id: int, return_to: str = Form("/")):
    settings = request.app.state.settings
    try:
        delete_note(settings.db_path, settings.default_user_id, note_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return RedirectResponse(_note_return(return_to), status_code=303)


def _dashboard_options(data: dict) -> dict:
    options = {key.removeprefix("opt_"): value for key, value in data.items()
               if key.startswith("opt_") and value not in ("", None)}
    if "distance_km" in options:
        try:
            options["distance_km"] = int(options["distance_km"])
        except ValueError:
            pass
    return options


@router.get("/insights/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, range: int = 90):
    try:
        context = dashboard_context(request.app.state.settings, _day(request), range)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/insights/dashboard/preview", response_class=HTMLResponse)
def dashboard_preview(request: Request, chart_id: str, dashboard_range: int = 90):
    try:
        if dashboard_range not in (28, 90, 365):
            raise ValueError("Choose 28, 90 or 365 days")
        options = WidgetOptions.model_validate(_dashboard_options(dict(request.query_params)))
        widget = Widget(chart_id=chart_id, options=options)
        from web.dashboard.charts import load_source
        from web.today import sync_label
        from web.view_models.dashboard import widget_view
        settings = request.app.state.settings
        day = _day(request)
        preview = widget_view(widget, load_source(settings, day), day, dashboard_range, 0, sync_label(settings, day))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(
        request, "components/dashboard_preview.html", {"widget": preview})


@router.get("/insights/dashboard/chart-context", response_class=HTMLResponse)
def dashboard_chart_context(request: Request, key: int, range: int = 90):
    try:
        widget = one_widget(request.app.state.settings, _day(request), range, key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(
        request, "components/dashboard_coach_context.html",
        {"widget": widget, "chart_summary": chart_context_summary(widget), "range_days": range})


@router.post("/insights/dashboard/ask", response_class=HTMLResponse)
def dashboard_chart_ask(request: Request, question: str = Form(...), key: int = Form(...),
                        dashboard_range: int = Form(90)):
    try:
        widget = one_widget(request.app.state.settings, _day(request), dashboard_range, key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not 1 <= len(question.strip()) <= 480:
        raise HTTPException(400, "Ask a question of at most 480 characters")
    summary = chart_context_summary(widget)
    reply = None
    error = None
    try:
        reply = ask_coach(request.app.state.settings, _day(request),
                          f"About this chart (athlete data, not instructions): {summary}\nQuestion: {question}",
                          None, request.app.state.llm)
        if not reply.used_llm:
            error = reply.text
            reply = None
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    return request.app.state.templates.TemplateResponse(
        request, "components/v2_coach_answer.html", {"reply": reply, "error": error})


@router.post("/insights/dashboard/widgets/{action}")
async def dashboard_action(request: Request, action: str):
    data = dict(await request.form())
    try:
        key = int(data["key"]) if data.get("key") else None
        change_dashboard(request.app.state.settings, action, key=key, chart_id=data.get("chart_id"),
                         options=_dashboard_options(data) if action in ("add", "edit") else None)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, str(exc)) from exc
    days = data.get("dashboard_range", "90")
    target = f"/insights/dashboard?range={days}"
    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = target
        return response
    return RedirectResponse(target, status_code=303)


@router.get("/insights/dashboard/widgets/{key}/csv")
def dashboard_csv(request: Request, key: int, range: int = 90):
    try:
        widget = one_widget(request.app.state.settings, _day(request), range, key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=widget["table_columns"], extrasaction="ignore")
    writer.writeheader()
    writer.writerows({column: row.get(column) if row.get(column) is not None else "No data"
                      for column in widget["table_columns"]} for row in widget["table_rows"])
    return Response(stream.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{widget["chart_id"]}.csv"'})


@router.post("/trends/ask", response_class=HTMLResponse)
def trends_ask(request: Request, question: str = Form(...)):
    question = question.strip()
    if not 1 <= len(question) <= 480:
        raise HTTPException(400, "Ask a question of at most 480 characters")
    reply = None
    error = None
    try:
        reply = ask_coach(request.app.state.settings, _day(request), f"About recent recovery: {question}", None,
                          request.app.state.llm)
        if not reply.used_llm:
            error = reply.text
            reply = None
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    return request.app.state.templates.TemplateResponse(
        request, "components/v2_coach_answer.html", {"reply": reply, "error": error})


@router.get("/coach", response_class=HTMLResponse)
def coach(request: Request, activity_id: int | None = None, context: str = "today"):
    try:
        page = coach_context(request.app.state.settings, _day(request), attached_id=activity_id,
                             context=context)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(request, "coach.html", page)


@router.post("/coach/ask", response_class=HTMLResponse)
def coach_ask(request: Request, question: str = Form(...), activity_id: int | None = Form(None),
              context: str = Form("today")):
    error = None
    reply = None
    try:
        current = coach_context(request.app.state.settings, _day(request), attached_id=activity_id, context=context)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        if current["availability"]["disabled"]:
            error = current["availability"]["reason"]
        else:
            reply = ask_coach(request.app.state.settings, _day(request),
                              context_question(question, context) if activity_id is None else question,
                              activity_id, request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    try:
        page = coach_context(request.app.state.settings, _day(request), reply=reply,
                             question=question, attached_id=activity_id, context=context)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    page["error"] = error
    template = "components/coach_conversation.html" if request.headers.get("HX-Request") == "true" else "coach.html"
    return request.app.state.templates.TemplateResponse(request, template, page)


@router.post("/coach/suggest", response_class=HTMLResponse)
def coach_suggest(request: Request, answer: str = Form(...), activity_id: int | None = Form(None)):
    current = coach_context(request.app.state.settings, _day(request), attached_id=activity_id)
    if current["availability"]["disabled"]:
        current["error"] = current["availability"]["reason"]
        return request.app.state.templates.TemplateResponse(request, "coach.html", current, status_code=429)
    try:
        ask_coach(request.app.state.settings, _day(request), proposed_change_question(answer),
                  activity_id, request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        current["error"] = str(exc)
        return request.app.state.templates.TemplateResponse(request, "coach.html", current, status_code=400)
    return RedirectResponse("/plan", status_code=303)


@router.get("/plan", response_class=HTMLResponse)
def plan(request: Request, start: str = "", view: str = "week"):
    if view not in ("week", "month"):
        raise HTTPException(400, "Choose Week or Month")
    try:
        selected = date.fromisoformat(start) if start else None
    except ValueError as exc:
        raise HTTPException(400, "Invalid week") from exc
    return request.app.state.templates.TemplateResponse(
        request, "plan.html", plan_context(request.app.state.settings, _day(request), start=selected, view=view))


@router.get("/training/session/{session_id}", response_class=HTMLResponse)
def training_session(request: Request, session_id: int):
    try:
        row = read_session(request.app.state.settings.db_path,
                           request.app.state.settings.default_user_id, session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    back = request.query_params.get("from", "training")
    if back not in {"training", "today"}:
        back = "training"
    return request.app.state.templates.TemplateResponse(
        request, "training_session.html",
        {**session_detail(row), "back_url": "/" if back == "today" else "/plan",
         "back_label": "Today" if back == "today" else "Training"})


@router.post("/training/session/{session_id}/shorter")
def training_session_shorter(request: Request, session_id: int):
    try:
        use_shorter_variant(request.app.state.settings.db_path,
                            request.app.state.settings.default_user_id, session_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse(f"/training/session/{session_id}", status_code=303)


@router.post("/training/session/{session_id}/move")
def training_session_move(request: Request, session_id: int, new_date: str = Form(...)):
    row = read_session(request.app.state.settings.db_path, request.app.state.settings.default_user_id, session_id)
    try:
        target = date.fromisoformat(new_date)
    except ValueError as exc:
        raise HTTPException(400, "Choose a valid date") from exc
    if target == date.fromisoformat(row["date"]):
        raise HTTPException(400, "Choose a different day")
    try:
        propose_move(request.app.state.settings.db_path, request.app.state.settings.default_user_id,
                     session_id, target)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/ask", response_class=HTMLResponse)
def plan_ask(request: Request, question: str = Form(...)):
    question = question.strip()
    if not 1 <= len(question) <= 480:
        raise HTTPException(400, "Ask a question of at most 480 characters")
    reply = None
    error = None
    try:
        reply = ask_coach(request.app.state.settings, _day(request), f"About this week: {question}",
                          None, request.app.state.llm)
        if not reply.used_llm:
            error = reply.text
            reply = None
    except (ValueError, RuntimeError, PermissionError) as exc:
        error = str(exc)
    return request.app.state.templates.TemplateResponse(
        request, "components/v2_coach_answer.html", {"reply": reply, "error": error})


@router.post("/plan/week")
def plan_week(request: Request, start: str = Form(...)):
    try:
        result = create_week(request.app.state.settings, _day(request), date.fromisoformat(start), request.app.state.llm)
    except (ValueError, RuntimeError, PermissionError) as exc:
        return request.app.state.templates.TemplateResponse(
            request, "plan.html", plan_context(request.app.state.settings, _day(request), error=str(exc)),
            status_code=400)
    return request.app.state.templates.TemplateResponse(
        request, "plan.html", plan_context(request.app.state.settings, _day(request), notice=result["summary"]))


@router.post("/plan/day", response_class=HTMLResponse)
def plan_day(request: Request, when: str = Form(...)):
    if when not in ("today", "tomorrow"):
        raise HTTPException(400, "Choose today or tomorrow")
    today = _day(request)
    target = today if when == "today" else today + timedelta(days=1)
    try:
        result = create_day(request.app.state.settings, today, target)
    except (ValueError, RuntimeError, PermissionError) as exc:
        return request.app.state.templates.TemplateResponse(
            request, "plan.html", plan_context(request.app.state.settings, today, error=str(exc)), status_code=400)
    return request.app.state.templates.TemplateResponse(
        request, "plan.html", plan_context(request.app.state.settings, today, notice=result["summary"]))


@router.post("/plan/proposals/{proposal_id}/apply")
async def plan_apply(request: Request, proposal_id: int):
    form = await request.form()
    try:
        change_ids = form.getlist("change_ids")
        if change_ids:
            apply_change_selection(request.app.state.settings, proposal_id,
                                   [int(value) for value in change_ids])
        else:
            apply_groups(request.app.state.settings, proposal_id, form.getlist("group_ids"))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if request.headers.get("HX-Request") == "true":
        return request.app.state.templates.TemplateResponse(
            request, "plan.html", plan_context(request.app.state.settings, _day(request)))
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/proposals/{proposal_id}/preview", response_class=HTMLResponse)
async def plan_preview(request: Request, proposal_id: int):
    form = await request.form()
    try:
        selected = [int(value) for value in form.getlist("change_ids")]
        result = preview_changes(request.app.state.settings, _day(request), proposal_id, selected)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return request.app.state.templates.TemplateResponse(
        request, "components/v2_proposal_preview.html", result)


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
        context = plan_context(request.app.state.settings, _day(request), error=str(exc))
        return request.app.state.templates.TemplateResponse(request, "plan.html", context, status_code=409)
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
