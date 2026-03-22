"""
Ollama LLM Provider

Supports local LLM models via Ollama (no API keys needed!)
Models: llama2, mistral, codellama, deepseek-coder, etc.
"""

import logging
import requests
from typing import Optional, Dict
import json

from .base import BaseLLMProvider, LLMResponse


logger = logging.getLogger("ollama_provider")


class OllamaProvider(BaseLLMProvider):
    """
    Ollama provider for local LLM models
    
    Requires:
    - Ollama installed: https://ollama.ai
    - Model pulled: ollama pull codellama (or llama2, mistral, etc.)
    """
    
    provider_name = "ollama"
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "codellama",
        timeout: int = 300
    ):
        """
        Initialize Ollama provider
        
        Args:
            base_url: Ollama API URL (default: http://localhost:11434)
            model: Model name (codellama, llama2, mistral, deepseek-coder, etc.)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self._available = None  # Cache availability check
    
    def is_available(self) -> bool:
        """Check if Ollama is running and model is available"""
        if self._available is not None:
            return self._available
        
        try:
            # Check if Ollama server is running
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            
            if response.status_code != 200:
                self._available = False
                return False
            
            # Check if model is available
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            
            # Check if our model exists (exact match or starts with)
            model_available = any(
                self.model in name or name.startswith(self.model)
                for name in model_names
            )
            
            self._available = model_available
            
            if model_available:
                logger.info(f"✅ Ollama provider ready: {self.model}")
            else:
                logger.warning(
                    f"⚠️  Ollama model '{self.model}' not found. "
                    f"Available models: {', '.join(model_names[:5])}"
                )
                logger.info(f"   Pull model with: ollama pull {self.model}")
            
            return model_available
            
        except requests.exceptions.ConnectionError:
            logger.warning(
                f"⚠️  Ollama server not running at {self.base_url}. "
                "Start with: ollama serve"
            )
            self._available = False
            return False
        except Exception as e:
            logger.warning(f"⚠️  Ollama check failed: {e}")
            self._available = False
            return False
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response using Ollama
        
        Args:
            prompt: User prompt
            system_prompt: System prompt (Ollama uses 'system' field)
            temperature: Creativity (0-1)
            max_tokens: Max response tokens
            
        Returns:
            LLMResponse
        """
        if not self.is_available():
            raise RuntimeError(
                f"Ollama model '{self.model}' not available. "
                f"Start Ollama: ollama serve\n"
                f"Pull model: ollama pull {self.model}"
            )
        
        # Build messages (Ollama uses chat format)
        messages = []
        
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        # Ollama API request
        payload = {
            "model": self.model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,  # Ollama uses num_predict
            },
            "stream": False  # Non-streaming for simplicity
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Extract response
            message = result.get("message", {})
            content = message.get("content", "")
            
            # Extract token counts
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens
            
            # Ollama is free (local), so cost is 0
            cost_estimate = 0.0
            
            logger.info(
                f"✅ Ollama response: {total_tokens} tokens "
                f"({prompt_tokens} prompt + {completion_tokens} completion)"
            )
            
            return LLMResponse(
                content=content,
                model=self.model,
                provider="ollama",
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_estimate=cost_estimate,
                metadata={
                    "ollama_response": result,
                    "base_url": self.base_url
                }
            )
            
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Ollama request timed out after {self.timeout}s")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama API error: {e}")
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}")
    
    def get_model_name(self) -> str:
        """Get the current model name"""
        return self.model
    
    def list_available_models(self) -> list:
        """List available Ollama models"""
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [m.get("name", "") for m in models]
            return []
        except Exception:
            return []
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Ollama is free (runs locally)"""
        return 0.0
