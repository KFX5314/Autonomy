"""
Strategy interface for LLM providers.
Any new provider (Claude, Gemini, local llama.cpp, etc.) just implements this ABC.
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base for LLM inference providers."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt and return the generated text."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable."""
        ...
