_bot_username: str | None = None


def set_bot_username(username: str | None) -> None:
    global _bot_username
    _bot_username = username.lstrip("@") if username else None


def get_bot_username() -> str | None:
    return _bot_username
