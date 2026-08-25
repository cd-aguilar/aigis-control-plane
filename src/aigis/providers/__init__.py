"""LLM provider adapters. Only ClaudeProvider exists so far (Phase 2) — see
aigis.agent.provider.Provider for the protocol every provider must satisfy.

Importing this module never requires the ``anthropic`` package: ClaudeProvider
only imports it lazily, inside its own __init__.
"""

from aigis.providers.claude import ClaudeProvider

__all__ = ["ClaudeProvider"]
