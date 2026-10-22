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
