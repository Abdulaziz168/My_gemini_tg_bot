import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config import config
from database.db import check_rate_limit, get_daily_count, get_user, upsert_user

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Har bir xabar uchun:
    1. Foydalanuvchini DB ga ro'yxatdan o'tkazish / yangilash
    2. Ban holati tekshirish
    3. Rate limit tekshirish (audio/video uchun)
    4. Kunlik limit tekshirish (audio/video uchun)
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # ── 1. DB ga upsert ──────────────────────────────────
        await upsert_user(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name or user.first_name or "Unknown",
        )

        # ── 2. Ban tekshirish ────────────────────────────────
        db_user = await get_user(user.id)
        if db_user and db_user.get("is_banned"):
            await event.answer(
                "🚫 Siz tizimdan bloklangansiz.\n"
                "Murojaat uchun admin bilan bog'laning."
            )
            return

        # ── 3. Admin uchun limitlar yo'q ─────────────────────
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        # ── 4. Faqat media xabarlar uchun limit ──────────────
        is_media = bool(
            event.voice or event.audio or
            event.video_note or event.video
        )

        if is_media:
            # Rate limit
            allowed = await check_rate_limit(user.id)
            if not allowed:
                await event.answer(
                    f"⏳ <b>Tezlik cheklovi!</b>\n"
                    f"{config.RATE_LIMIT_WINDOW} soniyada "
                    f"{config.RATE_LIMIT_REQUESTS} tadan ko'p so'rov yuborib bo'lmaydi.\n"
                    f"Biroz kuting va qayta urinib ko'ring. 🙏",
                    parse_mode="HTML"
                )
                return

            # Kunlik limit
            daily = await get_daily_count(user.id)
            if daily >= config.DAILY_LIMIT:
                await event.answer(
                    f"📅 <b>Kunlik limit tugadi!</b>\n"
                    f"Bugun {config.DAILY_LIMIT} ta so'rov bajarildi.\n"
                    f"Ertaga qaytib keling! 🌅",
                    parse_mode="HTML"
                )
                return

        return await handler(event, data)
