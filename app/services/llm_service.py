from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import json
from typing import Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

from app.services.personality_service import PepeContext


OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
OPENROUTER_MAX_TOKENS = 600


class LLMProvider(str, Enum):
    STUB = "stub"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    LOCAL = "local"


class LLMProviderNotConfiguredError(RuntimeError):
    pass


class LLMProviderRequestError(RuntimeError):
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


@dataclass(frozen=True)
class LLMRuntimeConfig:
    openrouter_api_key: str = ""
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL


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


class OpenRouterLLMAdapter:
    provider = LLMProvider.OPENROUTER

    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str = OPENROUTER_CHAT_COMPLETIONS_URL,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds

        if not self.api_key:
            raise LLMProviderNotConfiguredError("OpenRouter API key is not configured.")
        if not self.model:
            raise LLMProviderNotConfiguredError("OpenRouter model is not configured.")

    def generate_response(self, request: LLMRequest) -> LLMResponse:
        _validate_request(request)
        payload = {
            "model": self.model,
            "messages": _build_openrouter_messages(request),
            "max_tokens": OPENROUTER_MAX_TOKENS,
        }
        http_request = urlrequest.Request(
            self.api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": "study_library_bot",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(http_request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urlerror.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise LLMProviderRequestError(f"OpenRouter request failed: {details}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise LLMProviderRequestError(f"OpenRouter request failed: {error}") from error

        text = parse_openrouter_response(response_payload)
        return LLMResponse(
            text=text,
            provider=self.provider,
            is_generated=True,
        )


class LocalLLMAdapter(UnconfiguredLLMAdapter):
    provider = LLMProvider.LOCAL
    display_name = "Local LLM"


SUPPORTED_PROVIDERS = (
    LLMProvider.OPENAI,
    LLMProvider.OPENROUTER,
    LLMProvider.LOCAL,
)

AVAILABLE_PROVIDERS = (LLMProvider.STUB, LLMProvider.OPENROUTER)

_ADAPTER_FACTORIES: Mapping[LLMProvider, Callable[[], LLMAdapter]] = {
    LLMProvider.STUB: StubLLMAdapter,
    LLMProvider.OPENAI: OpenAILLMAdapter,
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


def get_llm_adapter(
    provider: LLMProvider | str = LLMProvider.STUB,
    runtime_config: LLMRuntimeConfig | None = None,
) -> LLMAdapter:
    llm_provider = normalize_provider(provider)
    if llm_provider == LLMProvider.OPENROUTER:
        config = runtime_config or LLMRuntimeConfig()
        if not config.openrouter_api_key.strip():
            return StubLLMAdapter()
        model = config.openrouter_model.strip() or DEFAULT_OPENROUTER_MODEL
        return OpenRouterLLMAdapter(
            api_key=config.openrouter_api_key,
            model=model,
        )

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
    runtime_config: LLMRuntimeConfig | None = None,
) -> LLMResponse:
    request = build_llm_request(
        user_message=user_message,
        pepe_context=pepe_context,
        character_engine_context=character_engine_context,
    )
    adapter = get_llm_adapter(provider, runtime_config=runtime_config)
    return adapter.generate_response(request)


def _validate_request(request: LLMRequest) -> None:
    if not request.user_message.strip():
        raise ValueError("LLM user message must not be empty")

    if not request.pepe_context.system_prompt.strip():
        raise ValueError("LLM Pepe context must include a system prompt")

    if not request.character_engine_context:
        raise ValueError("LLM character engine context must not be empty")


def _build_openrouter_messages(request: LLMRequest) -> list[dict[str, str]]:
    character_context = json.dumps(
        request.character_engine_context,
        ensure_ascii=False,
        indent=2,
    )
    system_content = (
        f"{request.pepe_context.system_prompt}\n\n"
        "Character engine context:\n"
        f"{character_context}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": request.user_message},
    ]


def parse_openrouter_response(response_payload: Mapping[str, object]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderRequestError("OpenRouter response does not contain choices.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise LLMProviderRequestError("OpenRouter response choice has invalid format.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise LLMProviderRequestError("OpenRouter response does not contain a message.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMProviderRequestError("OpenRouter response text is empty.")

    return content.strip()
