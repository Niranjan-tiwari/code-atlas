"""
Multi-Model LLM Manager
Routes requests to the best available model with fallback support
"""

import json
import logging
from typing import Dict, List, Optional
from pathlib import Path

from .base import BaseLLMProvider, LLMResponse
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .groq_provider import GroqProvider
from .env_keys import (
    ANTHROPIC,
    GEMINI,
    GROQ,
    OPENAI,
    explicit_provider_setup_hint,
    from_env,
    no_providers_runtime_message,
)


class LLMManager:
    """
    Manages multiple LLM providers with fallback and routing
    
    Features:
    - Auto-detect available providers based on API keys
    - Fallback chain: if one provider fails, try the next
    - Task-based routing: use different models for different tasks
    - Cost tracking
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.logger = logging.getLogger("llm_manager")
        self.providers: Dict[str, BaseLLMProvider] = {}
        self.fallback_chain: List[str] = []
        self.total_cost: float = 0.0
        self.total_tokens: int = 0
        self.request_count: int = 0
        
        # Initialize providers
        self._init_providers(config_path)
    
    def _init_providers(self, config_path: Optional[str] = None):
        """Initialize all available LLM providers"""
        # Load config if available
        config = {}
        if config_path and Path(config_path).exists():
            try:
                with open(config_path) as f:
                    config = json.load(f).get("llm", {})
            except Exception as e:
                self.logger.warning(f"Error loading config: {e}")
        
        # Groq — register before others when key present
        groq_cfg = config.get("groq", {})
        if groq_cfg.get("enabled", True):
            groq_key = from_env(GROQ, groq_cfg.get("api_key", ""))
            groq_model = groq_cfg.get("model", "llama-3.3-70b-versatile")
            provider = GroqProvider(api_key=groq_key or None, model=groq_model)
            if provider.is_available():
                self.providers["groq"] = provider
                self.logger.info(f"✅ Groq provider ready: {groq_model}")

        # Initialize OpenAI
        openai_key = from_env(OPENAI, config.get("openai", {}).get("api_key", ""))
        openai_model = config.get("openai", {}).get("model", "gpt-4o-mini")
        provider = OpenAIProvider(api_key=openai_key, model=openai_model)
        if provider.is_available():
            self.providers["openai"] = provider
            self.logger.info(f"✅ OpenAI provider ready: {openai_model}")
        
        # Initialize Anthropic
        anthropic_key = from_env(ANTHROPIC, config.get("claude", {}).get("api_key", ""))
        anthropic_model = config.get("claude", {}).get("model", "claude-3-5-sonnet-20241022")
        provider = AnthropicProvider(api_key=anthropic_key, model=anthropic_model)
        if provider.is_available():
            self.providers["anthropic"] = provider
            self.logger.info(f"✅ Anthropic provider ready: {anthropic_model}")
        
        # Initialize Gemini
        gemini_key = from_env(GEMINI, config.get("gemini", {}).get("api_key", ""))
        gemini_model = config.get("gemini", {}).get("model", "gemini-2.0-flash")
        provider = GeminiProvider(api_key=gemini_key, model=gemini_model)
        if provider.is_available():
            self.providers["gemini"] = provider
            self.logger.info(f"✅ Gemini provider ready: {gemini_model}")
        
        # Ollama (local LLM) — off when llm.ollama.enabled is false
        ollama_config = config.get("ollama", {})
        if ollama_config.get("enabled", True):
            ollama_url = ollama_config.get("base_url", "http://localhost:11434")
            ollama_model = ollama_config.get("model", "qwen2.5-coder:1.5b")
            provider = OllamaProvider(base_url=ollama_url, model=ollama_model)
            if provider.is_available():
                self.providers["ollama"] = provider
                self.logger.info(f"✅ Ollama provider ready: {ollama_model} (local, free)")
        
        # Fallback chain: prefer Groq → Ollama → cloud APIs (only registered providers kept)
        configured_chain = config.get(
            "fallback_chain",
            ["groq", "ollama", "openai", "anthropic", "gemini"],
        )
        self.fallback_chain = [p for p in configured_chain if p in self.providers]
        
        if not self.providers:
            self.logger.warning("⚠️  No LLM providers available!")
            self.logger.warning("   Options:")
            self.logger.warning("   1. Use Ollama (local, free, recommended):")
            self.logger.warning("      - Install: https://ollama.ai")
            self.logger.warning("      - Start: ollama serve")
            self.logger.warning("      - Pull model: ollama pull codellama")
            self.logger.warning(f"   2. export {GROQ}=gsk_... or export {OPENAI}=sk-...")
        else:
            chain_str = ' → '.join(self.fallback_chain)
            self.logger.info(f"📋 Fallback chain: {chain_str}")
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        provider: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> LLMResponse:
        """
        Generate a response using the best available model
        
        Args:
            prompt: User prompt
            system_prompt: System prompt for context
            provider: Specific provider to use (or None for auto)
            temperature: Creativity level (0-1)
            max_tokens: Maximum response tokens
        
        Returns:
            LLMResponse with content and metadata
        """
        if not self.providers:
            raise RuntimeError(no_providers_runtime_message())

        if isinstance(provider, str):
            provider = provider.strip().lower()
            if provider in ("", "auto"):
                provider = None
            elif provider == "claude":
                provider = "anthropic"

        # Explicit provider: do not silently fall back (avoids e.g. hanging on Ollama)
        providers_to_try: List[str]
        if provider:
            if provider not in self.providers:
                avail = ", ".join(sorted(self.providers.keys()))
                hint = explicit_provider_setup_hint(provider)
                extra = f"\n  {hint}" if hint else ""
                raise RuntimeError(
                    f"LLM provider {provider!r} is not available (missing key, disabled in config, or unreachable).\n"
                    f"  Configured right now: {avail}{extra}"
                )
            providers_to_try = [provider]
        else:
            providers_to_try = (
                self.fallback_chain if self.fallback_chain else list(self.providers.keys())
            )
        
        last_error = None
        for provider_name in providers_to_try:
            try:
                llm = self.providers[provider_name]
                self.logger.info(f"🤖 Using {provider_name} ({llm.get_model_name()})...")
                
                response = llm.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
                
                # Track usage
                self.total_cost += response.cost_estimate
                self.total_tokens += response.tokens_used
                self.request_count += 1
                
                self.logger.info(
                    f"✅ Response from {provider_name}: "
                    f"{response.tokens_used} tokens, ${response.cost_estimate:.6f}"
                )
                
                return response
                
            except Exception as e:
                last_error = e
                self.logger.warning(f"⚠️  {provider_name} failed: {e}, trying next...")
                continue
        
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
    
    def get_available_providers(self) -> List[Dict]:
        """Get list of available providers"""
        return [
            {
                "name": name,
                "model": provider.get_model_name(),
                "available": provider.is_available()
            }
            for name, provider in self.providers.items()
        ]
    
    def get_usage_stats(self) -> Dict:
        """Get usage statistics"""
        return {
            "total_requests": self.request_count,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost, 6),
            "available_providers": list(self.providers.keys()),
            "fallback_chain": self.fallback_chain
        }
