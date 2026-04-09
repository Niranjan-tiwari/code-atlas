"""
Google Gemini LLM Provider
Supports Gemini Pro, Gemini Flash
"""

import logging
from typing import Optional

from .base import BaseLLMProvider, LLMResponse
from .env_keys import GEMINI, from_env


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider"""
    
    provider_name = "gemini"
    
    # Cost per 1M tokens (USD)
    PRICING = {
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-pro": {"input": 0.50, "output": 1.50},
    }
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or from_env(GEMINI)
        self.model = model
        self.logger = logging.getLogger("gemini_provider")
        self._client = None
    
    def _get_client(self):
        """Lazy-initialize the Gemini client"""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai.GenerativeModel(self.model)
            except ImportError:
                raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")
        return self._client
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> LLMResponse:
        """Generate response using Gemini API"""
        model = self._get_client()
        
        try:
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }
            
            response = model.generate_content(
                full_prompt,
                generation_config=generation_config
            )
            
            content = response.text if response.text else ""
            
            # Gemini doesn't always return token counts
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0)
                completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0)
            
            return LLMResponse(
                content=content,
                model=self.model,
                provider=self.provider_name,
                tokens_used=prompt_tokens + completion_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate=self.estimate_cost(prompt_tokens, completion_tokens),
                metadata={}
            )
        except Exception as e:
            self.logger.error(f"Gemini API error: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if Gemini API key is configured"""
        return bool(self.api_key) and len(self.api_key) > 10
    
    def get_model_name(self) -> str:
        return self.model
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self.PRICING.get(self.model, {"input": 0.10, "output": 0.40})
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
