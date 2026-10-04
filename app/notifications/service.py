import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def enqueue(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    order_id: uuid.UUID | None,
    kind: str,
    text: str,
    buttons: list[dict[str, str]] | None = None,
) -> None:
    if order_id is not None:
        existing = await session.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.order_id == order_id,
                Notification.kind == kind,
            )
        )
        if existing is not None:
            return
    session.add(
        Notification(
            user_id=user_id,
            order_id=order_id,
            kind=kind,
            payload={"text": text, "buttons": buttons or []},
            status="pending",
        )
    )


async def pending_ids(session: AsyncSession, *, limit: int = 50) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(Notification.id)
        .where(Notification.status == "pending")
        .order_by(Notification.created_at)
        .limit(limit)
    )
    return list(rows)
