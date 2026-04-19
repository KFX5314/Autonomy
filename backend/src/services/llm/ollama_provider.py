"""
Ollama provider - calls the local Ollama HTTP API.
"""

import httpx
from .base import LLMProvider
from ...config import config


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.LLM_MODEL
        # Reuse a single AsyncClient across all generate() calls so we get
        # HTTP/1.1 keep-alive and connection pooling instead of opening a
        # fresh TCP connection for every LLM request. The generous timeout
        # covers warm/cold model loads; short timeouts are used explicitly
        # for the health_check / check_model requests below.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, system_prompt: str, user_message: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def check_model(self) -> None:
        """Verify the Ollama model is available. Raise if missing."""
        import logging
        log = logging.getLogger(__name__)
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if any(self.model in m or m.startswith(self.model.split(":")[0]) for m in models):
                log.info(f"Ollama model '{self.model}' ✓")
                return
            log.error(
                f"\n{'='*60}\n"
                f"  Ollama model '{self.model}' NOT FOUND.\n"
                f"  Run this command first:\n\n"
                f"    ollama pull {self.model}\n\n"
                f"  Then restart the server.\n"
                f"{'='*60}"
            )
            raise SystemExit(1)
        except SystemExit:
            raise
        except httpx.ConnectError:
            log.error(
                f"\n{'='*60}\n"
                f"  Cannot connect to Ollama at {self.base_url}.\n"
                f"  Make sure Ollama is running:\n\n"
                f"    ollama serve\n\n"
                f"{'='*60}"
            )
            raise SystemExit(1)
        except Exception as e:
            log.warning(f"Could not verify Ollama model: {e}")
