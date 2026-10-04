"""Credit trader_available for an admin telegram id.

    python -m app.admin_credit --telegram-id N --sats N

The telegram id must already be in admin_users. This is a virtual deposit:
nothing is read from the Bitcoin network.
"""

import argparse
import asyncio
import sys

from app.admin.service import NotAdmin, admin_adjust_deposit
from app.db import get_sessionmaker
from app.users.service import get_user_by_telegram_id


async def _credit(telegram_id: int, sats: int) -> int:
    maker = get_sessionmaker()
    async with maker() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if user is None:
            raise LookupError("user not found")
        balances = await admin_adjust_deposit(session, user.id, user.id, sats)
        await session.commit()
        return balances.available_sats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin_credit")
    parser.add_argument("--telegram-id", type=int, required=True)
    parser.add_argument("--sats", type=int, required=True)
    args = parser.parse_args(argv)
    if args.sats <= 0:
        print("Сумма в сатоши должна быть положительной.", file=sys.stderr)
        return 1
    try:
        available = asyncio.run(_credit(args.telegram_id, args.sats))
    except NotAdmin:
        print("Этого Telegram ID нет в admin_users. Пополнение отклонено.", file=sys.stderr)
        return 1
    except LookupError:
        print("Пользователь с этим Telegram ID не найден.", file=sys.stderr)
        return 1
    print(f"available_sats={available}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
