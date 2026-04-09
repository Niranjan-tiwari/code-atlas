"""
Single source for LLM-related environment variable names and user-facing hints.
Import these instead of repeating string literals across providers and scripts.
"""

from __future__ import annotations

import os
from typing import Final

# Canonical env var names (same as in .env.example / ai_config.json.example)
OPENAI: Final = "OPENAI_API_KEY"
ANTHROPIC: Final = "ANTHROPIC_API_KEY"
GEMINI: Final = "GEMINI_API_KEY"
GROQ: Final = "GROQ_API_KEY"


def from_env(name: str, config_fallback: str = "") -> str:
    """Trimmed value: environment first, then optional config string."""
    return (os.environ.get(name, config_fallback) or "").strip()


def no_providers_runtime_message() -> str:
    """Body for RuntimeError when generate() is called with zero providers."""
    return (
        "No LLM providers available:\n"
        f"  export {GROQ}=gsk_...  # or start Ollama\n"
        f"  export {OPENAI}=sk-...\n"
        f"  export {ANTHROPIC}=sk-ant-...\n"
        f"  export {GEMINI}=AI..."
    )


def explicit_provider_setup_hint(provider: str) -> str:
    """One line for a missing explicit provider."""
    hints = {
        "openai": f"export {OPENAI}=sk-...",
        "anthropic": f"export {ANTHROPIC}=sk-ant-...",
        "gemini": f"export {GEMINI}=...",
        "groq": f"export {GROQ}=gsk_...",
        "ollama": "start Ollama: ollama serve (and ensure the model is pulled)",
    }
    return hints.get(provider, "")


def cli_set_keys_tip() -> str:
    """Short line for CLI when no providers (query_code, etc.)."""
    return (
        f"Set API keys in .env or export {GROQ}, {OPENAI}, {ANTHROPIC}, or {GEMINI} "
        f"(see .env.example)"
    )


def cli_export_block() -> str:
    """Multi-line hint for exception handlers in query_code."""
    return (
        f"  export {GROQ}=gsk_...\n"
        f"  export {OPENAI}=sk-...\n"
        f"  export {ANTHROPIC}=sk-ant-...\n"
        f"  export {GEMINI}=AI..."
    )
