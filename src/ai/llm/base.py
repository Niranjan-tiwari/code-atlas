"""
Base LLM provider interface
All LLM providers implement this interface
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider"""
    content: str
    model: str
    provider: str
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_estimate: float = 0.0
    metadata: Dict = field(default_factory=dict)
    
    def __str__(self):
        return self.content


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    provider_name: str = "base"
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> LLMResponse:
        """Generate a response from the LLM"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available"""
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """Get the current model name"""
        pass
    
    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD"""
        return 0.0
