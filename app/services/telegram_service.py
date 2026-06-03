from typing import Optional

from telegram.constants import ParseMode
from telegram.ext import Application

from app.models import Material
from app.services.materials_service import format_material_text


async def send_material_to_chat(
    application: Application,
    chat_id: int,
    material: Material,
    db,
    thread_id: Optional[int] = None,
) -> None:
    text = format_material_text(material, db)
    thread_kwargs = {}
    if thread_id is not None and thread_id > 0:
        thread_kwargs["message_thread_id"] = thread_id

    await application.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        **thread_kwargs,
    )

    if material.file_id.strip():
        await application.bot.send_document(
            chat_id=chat_id,
            document=material.file_id.strip(),
            caption=f"{material.title}",
            **thread_kwargs,
        )
