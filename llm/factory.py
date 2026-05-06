"""Factory for selecting the configured LLM provider."""

from __future__ import annotations

from llm.base import LLMClient, NullLLMClient
from llm.ollama_client import OllamaClient
from llm.openai_client import OpenAIClient


def get_llm_client(provider: str, openai_api_key: str, openai_model: str, ollama_base_url: str, ollama_model: str) -> LLMClient:
    """Create an LLM client from the configured provider."""

    provider = (provider or "").lower()
    if provider == "chatgpt" and openai_api_key:
        return OpenAIClient(api_key=openai_api_key, model=openai_model)
    if provider == "ollama":
        return OllamaClient(base_url=ollama_base_url, model=ollama_model)
    return NullLLMClient()
