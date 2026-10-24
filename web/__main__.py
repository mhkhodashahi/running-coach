"""Run the local web server with python -m web."""

import os

import uvicorn


def main() -> None:
    host = os.getenv("WEB_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"} and not os.getenv("WEB_PASSWORD"):
        raise RuntimeError("Set WEB_PASSWORD before binding the web UI to a non-local address")
    uvicorn.run("web.app:app", host=host, port=int(os.getenv("WEB_PORT", "8000")))


if __name__ == "__main__":
    main()
