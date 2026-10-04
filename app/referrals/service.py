"""Partner totals from completed invitee orders and referral_payable."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import btc_rub_rate
from app.formatting import rub_kop_for_sats
from app.ledger.service import balance_of, referral_payable_code
from app.models import Order, OrderStatus, ReferralReward, User
from app.users.service import invited_count


@dataclass(frozen=True)
class PartnerSummary:
    invited: int
    completed_invitees: int
    turnover_rub_kop: int
    earned_sats: int
    available_sats: int
    snapshot_rub_kop: int
    estimate_rub_kop: int


async def partner_summary(session: AsyncSession, user_id: uuid.UUID) -> PartnerSummary:
    invited = await invited_count(session, user_id)
    completed_invitees = await session.scalar(
        select(func.count(func.distinct(User.id)))
        .select_from(User)
        .join(Order, Order.client_id == User.id)
        .where(
            User.referred_by_user_id == user_id,
            Order.status == OrderStatus.COMPLETED.value,
        )
    )
    turnover = await session.scalar(
        select(func.coalesce(func.sum(Order.principal_rub_kop), 0))
        .select_from(User)
        .join(Order, Order.client_id == User.id)
        .where(
            User.referred_by_user_id == user_id,
            Order.status == OrderStatus.COMPLETED.value,
        )
    )
    earned = await session.scalar(
        select(func.coalesce(func.sum(ReferralReward.amount_sats), 0)).where(
            ReferralReward.referrer_user_id == user_id
        )
    )
    available = await balance_of(session, referral_payable_code(user_id))
    reward_rows = (
        await session.execute(
            select(ReferralReward.amount_sats, Order.market_rate_rub_per_btc)
            .join(Order, Order.id == ReferralReward.order_id)
            .where(ReferralReward.referrer_user_id == user_id)
        )
    ).all()
    snapshot_rub = 0
    for sats, rate in reward_rows:
        snapshot_rub += rub_kop_for_sats(int(sats), Decimal(rate))
    estimate = rub_kop_for_sats(available, btc_rub_rate())
    return PartnerSummary(
        invited=invited,
        completed_invitees=int(completed_invitees or 0),
        turnover_rub_kop=int(turnover or 0),
        earned_sats=int(earned or 0),
        available_sats=available,
        snapshot_rub_kop=snapshot_rub,
        estimate_rub_kop=estimate,
    )
