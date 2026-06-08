from __future__ import annotations

from typing import TYPE_CHECKING

from app.personality import PepeMode
from app.personality.character_engine import generate_character_engine_context
from app.services.llm_service import LLMProvider, generate_response
from app.services.personality_service import build_pepe_context

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes


DEFAULT_PEPE_MESSAGE = "Test /pepe command"


def generate_pepe_stub_reply(user_message: str = DEFAULT_PEPE_MESSAGE) -> str:
    pepe_context = build_pepe_context(PepeMode.SOFT)
    character_engine_context = generate_character_engine_context()
    llm_response = generate_response(
        user_message=user_message or DEFAULT_PEPE_MESSAGE,
        pepe_context=pepe_context,
        character_engine_context=character_engine_context,
        provider=LLMProvider.STUB,
    )
    return llm_response.text


async def pepe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return

    user_message = " ".join(context.args).strip() if context.args else DEFAULT_PEPE_MESSAGE
    await update.effective_message.reply_text(generate_pepe_stub_reply(user_message))
