"""Run the local web server with python -m web."""

import os

import uvicorn

from config import get_settings


def main() -> None:
    get_settings()  # Load .env before resolving the server bind settings.
    host = os.getenv("WEB_HOST", "127.0.0.1")
    uvicorn.run("web.app:app", host=host, port=int(os.getenv("WEB_PORT", "8000")))


if __name__ == "__main__":
    main()
