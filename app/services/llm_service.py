from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.services.personality_service import PepeContext


class LLMProvider(str, Enum):
    STUB = "stub"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    LOCAL = "local"


class LLMProviderNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMRequest:
    user_message: str
    pepe_context: PepeContext
    character_engine_context: Mapping[str, object]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: LLMProvider
    is_generated: bool


class LLMAdapter(Protocol):
    provider: LLMProvider

    def generate_response(self, request: LLMRequest) -> LLMResponse: ...


class StubLLMAdapter:
    provider = LLMProvider.STUB

    def generate_response(self, request: LLMRequest) -> LLMResponse:
        _validate_request(request)
        return LLMResponse(
            text=(
                "LLM provider is not connected yet. "
                "Personality, runtime context and character engine context are ready."
            ),
            provider=self.provider,
            is_generated=False,
        )


class UnconfiguredLLMAdapter:
    provider: LLMProvider
    display_name: str

    def generate_response(self, request: LLMRequest) -> LLMResponse:
        _validate_request(request)
        raise LLMProviderNotConfiguredError(
            f"{self.display_name} LLM provider is reserved but not connected yet."
        )


class OpenAILLMAdapter(UnconfiguredLLMAdapter):
    provider = LLMProvider.OPENAI
    display_name = "OpenAI"


class OpenRouterLLMAdapter(UnconfiguredLLMAdapter):
    provider = LLMProvider.OPENROUTER
    display_name = "OpenRouter"


class LocalLLMAdapter(UnconfiguredLLMAdapter):
    provider = LLMProvider.LOCAL
    display_name = "Local LLM"


SUPPORTED_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.OPENROUTER,
    LLMProvider.LOCAL,
)

AVAILABLE_PROVIDERS = (LLMProvider.STUB,)

_ADAPTER_FACTORIES: Mapping[LLMProvider, Callable[[], LLMAdapter]] = {
    LLMProvider.STUB: StubLLMAdapter,
    LLMProvider.OPENAI: OpenAILLMAdapter,
    LLMProvider.OPENROUTER: OpenRouterLLMAdapter,
    LLMProvider.LOCAL: LocalLLMAdapter,
}


def build_llm_request(
    user_message: str,
    pepe_context: PepeContext,
    character_engine_context: Mapping[str, object],
) -> LLMRequest:
    normalized_message = user_message.strip()
    if not normalized_message:
        raise ValueError("LLM user message must not be empty")

    if not character_engine_context:
        raise ValueError("LLM character engine context must not be empty")

    return LLMRequest(
        user_message=normalized_message,
        pepe_context=pepe_context,
        character_engine_context=dict(character_engine_context),
    )


def get_llm_adapter(provider: LLMProvider | str = LLMProvider.STUB) -> LLMAdapter:
    llm_provider = normalize_provider(provider)
    return _ADAPTER_FACTORIES[llm_provider]()


def normalize_provider(provider: LLMProvider | str) -> LLMProvider:
    if isinstance(provider, LLMProvider):
        return provider

    normalized = provider.strip().lower()
    for llm_provider in LLMProvider:
        if normalized in {llm_provider.value, llm_provider.name.lower()}:
            return llm_provider

    raise ValueError(f"Unknown LLM provider: {provider}")


def generate_response(
    user_message: str,
    pepe_context: PepeContext,
    character_engine_context: Mapping[str, object],
    provider: LLMProvider | str = LLMProvider.STUB,
) -> LLMResponse:
    request = build_llm_request(
        user_message=user_message,
        pepe_context=pepe_context,
        character_engine_context=character_engine_context,
    )
    adapter = get_llm_adapter(provider)
    return adapter.generate_response(request)


def _validate_request(request: LLMRequest) -> None:
    if not request.user_message.strip():
        raise ValueError("LLM user message must not be empty")

    if not request.pepe_context.system_prompt.strip():
        raise ValueError("LLM Pepe context must include a system prompt")

    if not request.character_engine_context:
        raise ValueError("LLM character engine context must not be empty")
