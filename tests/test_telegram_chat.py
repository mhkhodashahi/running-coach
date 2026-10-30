from __future__ import annotations

from types import SimpleNamespace

from coach.agent import CoachAnswer
from services.telegram_chatbot import TelegramTrainingChatBot
from services.training_chat_service import TrainingChatService


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[tuple[str, str]] = []

    def generate_json(self, system_prompt, user_prompt, response_schema=None):
        self.prompts.append((system_prompt, user_prompt))
        return self.payload


class FakeTelegram:
    def __init__(self):
        self.sent: list[tuple[str, str | None]] = []

    def send_text(self, text, recipient=None):
        self.sent.append((text, recipient))
        return "sent", "ok"


class FakeChat:
    def answer(self, question):
        return SimpleNamespace(text=f"answer: {question}")


def test_training_chat_service_uses_agent_reply_and_evidence(monkeypatch) -> None:
    class FakeAgent:
        def __init__(self, settings, client, user_id):
            assert user_id == settings.default_user_id

        def answer(self, question, activity_id=None, running_memory=""):
            assert question == "How was my run?"
            assert activity_id == 3
            return CoachAnswer("Keep it easy.", ({"id": "PACE", "metric": "Pace", "display": "6:00 /km",
                                                  "source": "activity"},), (3,), ("Ask about recovery",), (), 1)

    monkeypatch.setattr("services.training_chat_service.CoachAgent", FakeAgent)
    monkeypatch.setattr("services.training_chat_service.load_running_memory", lambda: "")
    reply = TrainingChatService(llm_client=FakeLLM({})).answer("How was my run?", activity_id=3)
    assert reply.used_llm
    assert "Pace: 6:00 /km" in reply.text
    assert reply.follow_ups == ("Ask about recovery",)


def test_training_chat_service_reports_limit_clearly(monkeypatch) -> None:
    class LimitedAgent:
        def __init__(self, *args):
            pass

        def answer(self, *args, **kwargs):
            raise RuntimeError("Daily coach LLM call limit reached.")

    monkeypatch.setattr("services.training_chat_service.CoachAgent", LimitedAgent)
    monkeypatch.setattr("services.training_chat_service.load_running_memory", lambda: "")
    reply = TrainingChatService(llm_client=FakeLLM({})).answer("Status")
    assert not reply.used_llm
    assert "limit reached" in reply.text


def test_telegram_chatbot_authorizes_configured_chat_only() -> None:
    telegram = FakeTelegram()
    bot = TelegramTrainingChatBot(
        settings=SimpleNamespace(telegram_chat_id="111", telegram_bot_token="token"),
        telegram_service=telegram,
        chat_service=FakeChat(),
    )

    result = bot.handle_update({"message": {"chat": {"id": 222}, "text": "How am I doing?"}})

    assert result.handled is True
    assert result.authorized is False
    assert telegram.sent == [("This Running Coach bot is private. Your chat id is not authorized.", "222")]


def test_telegram_chatbot_replies_to_authorized_question() -> None:
    telegram = FakeTelegram()
    bot = TelegramTrainingChatBot(
        settings=SimpleNamespace(telegram_chat_id="111", telegram_bot_token="token"),
        telegram_service=telegram,
        chat_service=FakeChat(),
    )

    result = bot.handle_update({"message": {"chat": {"id": 111}, "text": "How is my recovery?"}})

    assert result.handled is True
    assert result.authorized is True
    assert telegram.sent == [("answer: How is my recovery?", "111")]


def test_today_command_uses_same_daily_decision_and_keeps_allowlist(monkeypatch) -> None:
    telegram = FakeTelegram()
    seen = []

    def fake_decision(day, settings):
        seen.append(day)
        return SimpleNamespace(headline="Easy today.", explanation="I see the load.", provisional=True,
                               based_on="2026-06-28", last_sync_time="never synced",
                               sports=({"rank": 1, "sport": "running",
                                        "session": {"intent": "easy", "duration_min": 30}, "reason": "least done"},),
                               optional=None, team_options=({"sport": "football",
                                                           "label": "Only with team training today"},),
                               athlete_choice="rest", intensity="easy")

    monkeypatch.setattr("services.telegram_chatbot.get_or_create_daily_decision", fake_decision)
    bot = TelegramTrainingChatBot(
        settings=SimpleNamespace(telegram_chat_id="111", telegram_bot_token="token", local_timezone="Europe/Berlin"),
        telegram_service=telegram, chat_service=FakeChat(),
    )
    assert not bot.handle_update({"message": {"chat": {"id": 222}, "text": "/today"}}).authorized
    result = bot.handle_update({"message": {"chat": {"id": 111}, "text": "/today"}})
    assert result.authorized
    assert seen
    assert "Provisional" in result.reply
    assert "1. running: easy" in result.reply
    assert "Football: Only with team training today" in result.reply
    assert "Your choice: rest (coach: easy)" in result.reply


def test_plan_commands_keep_allowlist_and_require_explicit_approval(monkeypatch) -> None:
    telegram = FakeTelegram()
    proposal = {"id": 7, "status": "pending", "changes": [{"decision": "pending"}]}
    monkeypatch.setattr("services.telegram_chatbot.get_weekly_plan",
                        lambda *args, **kwargs: {"version": 0, "sessions": []})
    monkeypatch.setattr("services.telegram_chatbot.list_proposals", lambda *args, **kwargs: [proposal])
    bot = TelegramTrainingChatBot(
        settings=SimpleNamespace(telegram_chat_id="111", telegram_bot_token="token",
                                 local_timezone="Europe/Berlin", db_path=None, default_user_id=1),
        telegram_service=telegram, chat_service=FakeChat(),
    )
    assert not bot.handle_update({"message": {"chat": {"id": 222}, "text": "/plan-accept 11"}}).authorized
    preview = bot.handle_update({"message": {"chat": {"id": 111}, "text": "/plan"}})
    assert "1 pending" in preview.reply
    assert "Review it in the app" in preview.reply
    for command in ("/plan-suggest 2026-11-02", "/plan-accept 11", "/plan-reject 12", "/plan-undo",
                    "/plan-revise 7 make Saturday a rest day", "/plan-fixed Saturday football",
                    "/plan-unfix 2026-11-07"):
        result = bot.handle_update({"message": {"chat": {"id": 111}, "text": command}})
        assert result.authorized
        assert "in the app" in result.reply
