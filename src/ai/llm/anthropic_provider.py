"""
Anthropic (Claude) LLM Provider
Supports Claude Sonnet, Opus, Haiku
"""

import logging
from typing import Optional

from .base import BaseLLMProvider, LLMResponse
from .env_keys import ANTHROPIC, from_env


class AnthropicProvider(BaseLLMProvider):
    """Anthropic/Claude LLM provider"""
    
    provider_name = "anthropic"
    
    # Cost per 1M tokens (USD)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
        "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
        "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    }
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or from_env(ANTHROPIC)
        self.model = model
        self.logger = logging.getLogger("anthropic_provider")
        self._client = None
    
    def _get_client(self):
        """Lazy-initialize the Anthropic client"""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._client
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> LLMResponse:
        """Generate response using Anthropic API"""
        client = self._get_client()
        
        try:
            create_kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
            }
            
            if system_prompt:
                create_kwargs["system"] = system_prompt
            
            response = client.messages.create(**create_kwargs)
            
            content = response.content[0].text if response.content else ""
            prompt_tokens = response.usage.input_tokens if response.usage else 0
            completion_tokens = response.usage.output_tokens if response.usage else 0
            
            return LLMResponse(
                content=content,
                model=self.model,
                provider=self.provider_name,
                tokens_used=prompt_tokens + completion_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate=self.estimate_cost(prompt_tokens, completion_tokens),
                metadata={"stop_reason": response.stop_reason}
            )
        except Exception as e:
            self.logger.error(f"Anthropic API error: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Anthropic API key is configured"""
        return bool(self.api_key) and len(self.api_key) > 10
    
    def get_model_name(self) -> str:
        return self.model
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self.PRICING.get(self.model, {"input": 3.00, "output": 15.00})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
