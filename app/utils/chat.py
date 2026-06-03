from telegram import Update


def is_private_chat(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    return update.effective_chat.type == "private"
