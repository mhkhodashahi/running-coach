"""Run the Marathon Coach Telegram chat bot."""

from __future__ import annotations

import argparse

from services.telegram_chatbot import TelegramTrainingChatBot


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Marathon Coach Telegram training chat bot.")
    parser.add_argument("--poll-timeout", type=int, default=30, help="Telegram long-poll timeout in seconds.")
    args = parser.parse_args()

    bot = TelegramTrainingChatBot()
    print("Telegram training chat bot is polling. Press Ctrl+C to stop.")
    bot.run_polling(poll_timeout=args.poll_timeout)


if __name__ == "__main__":
    main()
