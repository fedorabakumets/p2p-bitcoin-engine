"""Telegram display name and descriptions.

The username belongs to BotFather. These calls change only the name people see.
"""

from aiogram import Bot

BOT_NAME = "Кедр"
BOT_SHORT_DESCRIPTION = "Кедр. Биткоин за рубли. Оплата трейдеру по СБП."
BOT_DESCRIPTION = (
    "Кедр — обмен биткоина за рубли.\n"
    "Клиент платит трейдеру по СБП.\n"
    "Биткоин приходит на адрес клиента.\n"
    "Бот рубли не принимает."
)


async def apply_bot_profile(bot: Bot) -> None:
    for language_code in (None, "ru"):
        await bot.set_my_name(name=BOT_NAME, language_code=language_code)
        await bot.set_my_short_description(
            short_description=BOT_SHORT_DESCRIPTION,
            language_code=language_code,
        )
        await bot.set_my_description(description=BOT_DESCRIPTION, language_code=language_code)
    from app.bot.brand import apply_profile_photo

    await apply_profile_photo(bot)
