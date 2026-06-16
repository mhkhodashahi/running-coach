from __future__ import annotations

import pytest

from llm.ollama_client import OLLAMA_INPUT_TOKEN_LIMIT, OllamaClient, estimate_input_tokens


def test_ollama_client_rejects_prompts_at_token_limit(monkeypatch) -> None:
    def fail_post(*args, **kwargs):
        raise AssertionError("Ollama should not be called when the input is too large")

    monkeypatch.setattr("llm.ollama_client.requests.post", fail_post)
    client = OllamaClient(base_url="http://localhost:11434", model="qwen3:14b")

    with pytest.raises(ValueError, match="under 7500"):
        client.generate_json("", "token " * OLLAMA_INPUT_TOKEN_LIMIT)


def test_ollama_token_estimate_counts_words_and_punctuation() -> None:
    assert estimate_input_tokens("Run easy, then stop.") == 6
