from __future__ import annotations

from types import SimpleNamespace

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


def test_training_chat_service_uses_llm_answer_and_evidence(monkeypatch) -> None:
    service = TrainingChatService(
        llm_client=FakeLLM(
            {
                "answer": "Keep tomorrow easy because readiness is low.",
                "evidence": ["Readiness 51", "7-day volume 44 km"],
                "follow_up": "Check HRV again tomorrow.",
            }
        )
    )
    monkeypatch.setattr(
        service,
        "_build_context",
        lambda user_id: {
            "snapshot": {
                "readiness": {"score": 51, "label": "low"},
                "weekly_mileage": {"7d": 44},
            },
            "recent_activities": [],
            "recent_health": [],
        },
    )

    reply = service.answer("What should I do tomorrow?")

    assert reply.used_llm is True
    assert "Keep tomorrow easy" in reply.text
    assert "Readiness 51" in reply.text
    assert "athlete_question" in service.llm_client.prompts[0][1]


def test_training_chat_service_falls_back_when_llm_returns_empty(monkeypatch) -> None:
    service = TrainingChatService(llm_client=FakeLLM({}))
    monkeypatch.setattr(
        service,
        "_build_context",
        lambda user_id: {
            "snapshot": {
                "weekly_mileage": {"7d": 12, "28d": 50},
                "readiness": {"score": 72, "label": "building"},
                "fatigue": {"score": 30, "level": "low"},
                "recovery": {"sleep_score": 82, "hrv": 55, "body_battery": 70},
                "prediction": {"predicted_minutes": 241, "predicted_pace": 5.71},
            },
            "recent_activities": [{"date": "2026-05-02", "type": "running", "distance": 8}],
        },
    )

    reply = service.answer("status")

    assert reply.used_llm is False
    assert "7-day running volume 12 km" in reply.text
    assert "Latest activity: 2026-05-02 running 8 km" in reply.text


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
    assert telegram.sent == [("This Marathon Coach bot is private. Your chat id is not authorized.", "222")]


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
