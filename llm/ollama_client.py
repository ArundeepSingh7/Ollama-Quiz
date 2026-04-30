import os
import requests
import httpx
import logging
import asyncio
import time

logger = logging.getLogger("ollama-client")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")


class OllamaClient:
    _instance = None

    def __init__(self):
        self.base_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

        self.async_client = httpx.AsyncClient(timeout=60)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = OllamaClient()
        return cls._instance

    def generate(self, prompt, temperature=0.5, max_tokens=200):
        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens
                        }
                    },
                    timeout=20
                )

                resp.raise_for_status()
                return resp.json().get("response", "").strip()

            except Exception as e:
                logger.warning(f"[SYNC] Attempt {attempt+1} failed: {e}")
                time.sleep(0.5)

        return ""

    async def generate_async(self, prompt, max_tokens=500):
        for attempt in range(3):
            try:
                resp = await self.async_client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": 0.5
                        }
                    },
                )

                resp.raise_for_status()
                return resp.json().get("response", "")

            except Exception as e:
                logger.warning(f"[ASYNC] Attempt {attempt+1} failed: {e}")
                await asyncio.sleep(0.5)

        return ""

    async def stream(self, prompt, max_tokens=200):
        try:
            async with self.async_client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"num_predict": max_tokens},
                },
            ) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if line:
                        yield line

        except Exception as e:
            logger.error(f"[STREAM ERROR]: {e}")