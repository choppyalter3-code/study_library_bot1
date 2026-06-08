from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.personality import PepeMode
from app.personality.character_engine import generate_character_engine_context
from app.services.llm_service import (
    LLMProvider,
    LLMProviderRequestError,
    LLMResponse,
    LLMRuntimeConfig,
    generate_response,
)
from app.services.personality_service import build_pepe_context

if TYPE_CHECKING:
    from app.config import Config
    from telegram import Update
    from telegram.ext import ContextTypes


DEFAULT_PEPE_MESSAGE = "Test /pepe command"
TELEGRAM_REPLY_LIMIT = 4000
logger = logging.getLogger("study_library_bot")


def generate_pepe_response(
    user_message: str = DEFAULT_PEPE_MESSAGE,
    openrouter_api_key: str = "",
    openrouter_model: str = "",
) -> LLMResponse:
    pepe_context = build_pepe_context(PepeMode.SOFT)
    character_engine_context = generate_character_engine_context()
    runtime_config = LLMRuntimeConfig(
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
    )

    try:
        return generate_response(
            user_message=user_message or DEFAULT_PEPE_MESSAGE,
            pepe_context=pepe_context,
            character_engine_context=character_engine_context,
            provider=LLMProvider.OPENROUTER,
            runtime_config=runtime_config,
        )
    except LLMProviderRequestError as error:
        logger.warning("OpenRouter request failed, falling back to STUB: %s", error)
        return generate_response(
            user_message=user_message or DEFAULT_PEPE_MESSAGE,
            pepe_context=pepe_context,
            character_engine_context=character_engine_context,
            provider=LLMProvider.STUB,
        )


def generate_pepe_stub_reply(user_message: str = DEFAULT_PEPE_MESSAGE) -> str:
    return generate_response(
        user_message=user_message or DEFAULT_PEPE_MESSAGE,
        pepe_context=build_pepe_context(PepeMode.SOFT),
        character_engine_context=generate_character_engine_context(),
        provider=LLMProvider.STUB,
    ).text


def _get_openrouter_settings(config: Config | None) -> tuple[str, str]:
    if config is None:
        return "", ""
    return (
        getattr(config, "openrouter_api_key", ""),
        getattr(config, "openrouter_model", ""),
    )


def split_telegram_reply(text: str, max_length: int = TELEGRAM_REPLY_LIMIT) -> tuple[str, ...]:
    normalized_text = text.strip()
    if not normalized_text:
        return ("...",)

    chunks: list[str] = []
    remaining_text = normalized_text
    while len(remaining_text) > max_length:
        split_at = remaining_text.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = remaining_text.rfind(" ", 0, max_length)
        if split_at <= 0:
            split_at = max_length

        chunks.append(remaining_text[:split_at].strip())
        remaining_text = remaining_text[split_at:].strip()

    if remaining_text:
        chunks.append(remaining_text)

    return tuple(chunks)


async def pepe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    user_message = " ".join(context.args).strip() if context.args else DEFAULT_PEPE_MESSAGE
    config = context.application.bot_data.get("config")
    openrouter_api_key, openrouter_model = _get_openrouter_settings(config)
    llm_response = await asyncio.to_thread(
        generate_pepe_response,
        user_message=user_message,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
    )
    for chunk in split_telegram_reply(llm_response.text):
        await update.effective_message.reply_text(chunk)
