"""
Groq LLM Provider (OpenAI-compatible API).
Set GROQ_API_KEY — https://console.groq.com/keys
"""

import logging
from typing import Optional

from .base import BaseLLMProvider, LLMResponse
from .env_keys import GROQ, from_env

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(BaseLLMProvider):
    provider_name = "groq"

    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = (api_key or from_env(GROQ)).strip()
        self.model = model
        self.logger = logging.getLogger("groq_provider")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ImportError("openai package required for Groq. Run: pip install openai") from e
            self._client = OpenAI(api_key=self.api_key, base_url=GROQ_BASE_URL)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs,
    ) -> LLMResponse:
        client = self._get_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        pt = usage.prompt_tokens if usage else 0
        ct = usage.completion_tokens if usage else 0
        return LLMResponse(
            content=content,
            model=self.model,
            provider=self.provider_name,
            tokens_used=pt + ct,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_estimate=0.0,
            metadata={"finish_reason": response.choices[0].finish_reason},
        )

    def is_available(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 12

    def get_model_name(self) -> str:
        return self.model
