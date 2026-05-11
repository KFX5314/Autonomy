"""
Factory that returns the correct LLMProvider based on configuration.
Follows the Strategy + Factory pattern: the caller never knows which
concrete provider it is using.
"""

from .base import LLMProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from ...config import config

_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return a singleton LLM provider based on config.LLM_PROVIDER."""
    global _instance
    if _instance is not None:
        return _instance

    match config.LLM_PROVIDER.lower():
        case "ollama":
            _instance = OllamaProvider()
        case "openai":
            _instance = OpenAIProvider()
        case other:
            raise ValueError(f"Unknown LLM provider: {other}. Use 'ollama' or 'openai'.")

    return _instance
