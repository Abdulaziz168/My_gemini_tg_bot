import asyncio
import io
import logging
import os
import html
from services.tts import text_to_speech
from aiogram.types import FSInputFile

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

from config import config
from database.db import (
    DB,
    add_chat_message,
    ban_user,
    clear_chat_history,
    get_all_user_ids,
    get_chat_history,
    get_chat_history_display,
    get_daily_count,
    get_global_stats,
    get_user,
    get_user_full_stats,
    get_ui_lang,
    init_db,
    log_request,
    set_lang_pref,
)
from middlewares.auth import AuthMiddleware
from services.chat import analyze_image, chat_with_gemini, extract_text_from_image
from services.stt import transcribe_audio
from services.translator import refine_and_format_text, summarize_text, translate_stt_result, translate_text
from utils.i18n import t
from utils.keyboards import (
    LANG_LABELS,
    TRANSLATE_TARGET_LABELS,
    admin_keyboard,
    chat_keyboard,
    lang_keyboard,
    translate_keyboard,
)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

router = Router()


async def get_user_ui_lang(user_id: int) -> str:
    async with aiosqlite.connect(DB) as db:
        return await get_ui_lang(db, user_id)


# ══════════════════════════════════════════════════════════════
#  FSM STATES
# ══════════════════════════════════════════════════════════════

class ChatState(StatesGroup):
    active = State()          # AI Chat rejimi

class TranslateState(StatesGroup):
    waiting_text = State()    # Tarjima uchun matnni kutish
    waiting_lang = State()    # Matn tarjimasi: tilni kutish

class PhotoState(StatesGroup):
    waiting_for_prompt = State()  # Rasm caption/prompt kutish (forward uchun)

class OCRState(StatesGroup):
    waiting_image = State()

class SummarizeState(StatesGroup):
    waiting_text = State()

class BroadcastState(StatesGroup):
    waiting_message = State() # Admin broadcast


# ══════════════════════════════════════════════════════════════
#  YORDAMCHI FUNKSIYALAR
# ══════════════════════════════════════════════════════════════

def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def _download_file(bot: Bot, file_id: str, ext: str) -> str:
    file = await bot.get_file(file_id)
    local_path = os.path.join(config.DOWNLOAD_DIR, f"{file_id}{ext}")
    await bot.download_file(file.file_path, local_path)
    return local_path


async def _process_audio(message: Message, file_id: str, ext: str, bot: Bot):
    """STT + ixtiyoriy tarjima yoki AI Redaktor."""
    user = message.from_user
    db_user = await get_user(user.id)
    ui_lang = db_user.get("ui_lang", "uz") if db_user else "uz"
    lang_pref = db_user.get("lang_pref", "auto") if db_user else "auto"
    daily_count = await get_daily_count(user.id)
    remaining = config.DAILY_LIMIT - daily_count

    status = await message.reply(
        t(
            ui_lang,
            "audio_processing",
            mode=LANG_LABELS.get(lang_pref, lang_pref),
            remaining=remaining,
            daily_limit=config.DAILY_LIMIT,
        ),
        parse_mode="HTML",
    )

    local_path = None
    try:
        local_path = await _download_file(bot, file_id, ext)

        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        if size_mb > config.MAX_AUDIO_SIZE_MB:
            await status.edit_text(
                t(
                    ui_lang,
                    "too_large_audio",
                    size=size_mb,
                    max_mb=config.MAX_AUDIO_SIZE_MB,
                )
            )
            return

        # ── STT ─────────────────────────────────────────────
        if lang_pref.startswith("translate_") or lang_pref.startswith("redact_"):
            stt_lang = "auto"
        else:
            stt_lang = lang_pref

        text, elapsed = await transcribe_audio(local_path, stt_lang)

        if not text:
            await log_request(user.id, elapsed, 0, success=False)
            await status.edit_text(
                t(ui_lang, "audio_no_text"),
                parse_mode="HTML",
            )
            return

        # ── Qayta ishlash (Tarjima yoki AI Redaktor) ────────
        processed_block = ""

        if lang_pref.startswith("translate_"):
            target = lang_pref.split("_", 1)[1]
            flag = TRANSLATE_TARGET_LABELS.get(target, target)
            await status.edit_text(
                t(ui_lang, "translate_processing", target=flag),
                parse_mode="HTML",
            )
            translated = await translate_stt_result(text, target)
            processed_block = (
                f"\n\n🌐 <b>Tarjima ({flag}):</b>\n"
                f"{'─'*30}\n"
                f"{translated}"
            )

        elif lang_pref.startswith("redact_"):
            target = lang_pref.split("_", 1)[1]
            flag = TRANSLATE_TARGET_LABELS.get(target, target)
            await status.edit_text(
                t(ui_lang, "redact_processing", target=flag),
                parse_mode="HTML",
            )
            refined = await refine_and_format_text(text, target)
            processed_block = (
                f"\n\n✨ <b>AI Redaktor ({flag}):</b>\n"
                f"{'─'*30}\n"
                f"{refined}"
            )

        # ── Natija ──────────────────────────────────────────
        await log_request(user.id, elapsed, len(text), success=True)

        header = t(ui_lang, "stt_done", elapsed=elapsed)

        # Show raw STT in monospace/preformatted block to preserve formatting
        escaped_text = html.escape(text)
        full_msg = header + f"<pre>{escaped_text}</pre>" + processed_block
        if len(full_msg) > 4096:
            full_msg = full_msg[:4040] + "\n\n" + t(ui_lang, "text_truncated")

        await status.edit_text(full_msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Audio xatolik (user={user.id}): {e}")
        await log_request(user.id, 0, 0, success=False)
        await status.edit_text(
            t(ui_lang, "audio_error", error=str(e)[:300]),
            parse_mode="HTML",
        )
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


# ══════════════════════════════════════════════════════════════
#  ASOSIY BUYRUQLAR
# ══════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    name = message.from_user.first_name or "Foydalanuvchi"
    await message.answer(
        f"👋 Xush kelibsiz, <b>{name}</b>!\n\n"
        f"🤖 Men <b>STT Pro</b> botman — ovoz, matn va rasmni qayta ishlayman.\n\n"
        f"<b>🎙️ Audio imkoniyatlar:</b>\n"
        f"• Ovozli xabar → Matn (STT)\n"
        f"• Audio/video fayl → Matn\n"
        f"• 20+ tilda avtomatik aniqlash\n"
        f"• STT natijasini tarjima qilish\n\n"
        f"<b>📝 Matn imkoniyatlari:</b>\n"
        f"• Har qanday matn yuboring → AI Chat javob beradi\n"
        f"• Tarjima uchun: /translate\n\n"
        f"<b>🤖 AI Chat (YANGI):</b>\n"
        f"• Gemini bilan multi-turn suhbat\n"
        f"• Suhbat tarixi saqlanadi\n\n"
        f"<b>📸 Rasm tahlili (YANGI):</b>\n"
        f"• Istalgan rasm yuboring → AI tahlil qiladi\n"
        f"• Caption qo'shsangiz — aniqroq javob\n\n"
        f"<b>Buyruqlar:</b>\n"
        f"/translate — Tarjima rejimi\n"
        f"/chat — AI Chat rejimini boshlash\n"
        f"/lang — STT rejimini sozlash\n"
        f"/history — Chat tarixini ko'rish\n"
        f"/mystats — Shaxsiy statistika\n"
        f"/help — Yordam\n\n"
        f"▶️ Boshlash uchun ovozli xabar, matn yoki rasm yuboring!",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Foydalanish qo'llanmasi</b>\n\n"
        "<b>🎙️ Audio → Matn (STT):</b>\n"
        "Ovozli xabar, audio fayl (.mp3 .ogg .wav .m4a)\n"
        "yoki video xabar yuboring — matn olasiz.\n\n"
        "<b>📝 Matn → AI Chat (default):</b>\n"
        "Har qanday matn yuboring — Gemini AI javob beradi.\n"
        "Tarix saqlanadi, kontekst tushunadi.\n\n"
        "<b>🌐 Tarjima (/translate):</b>\n"
        "/translate buyrug'ini yuboring, so'ng matnni yozing.\n"
        "Bot tilni avtomatik aniqlab, tarjima tilini so'raydi.\n\n"
        "• /history — so'nggi xabarlarni ko'rish\n"
        "• /clearhistory — tarixni tozalash\n\n"
        "<b>📸 Rasm tahlili:</b>\n"
        "• Rasm yuboring + caption = darhol tahlil\n"
        "• Forward qilingan rasm (caption yo'q) → bot prompt so'raydi\n"
        "• Masalan: 'Bu nima?' yoki 'Matni o'qi'\n\n"
        "<b>🌐 STT + Tarjima rejimi (/lang):</b>\n"
        "• 🔍 Auto — Tilni avtomatik aniqlash\n"
        "• 🇺🇿/🇷🇺/🇬🇧 — Aniq til STT\n"
        "• 🌐→🇺🇿 — STT + O'zbekcha tarjima\n"
        "• ✨ AI Redaktor — Matnni rasmiylash\n\n"
        f"<b>⚡ Limitlar:</b>\n"
        f"• {config.RATE_LIMIT_REQUESTS} so'rov / {config.RATE_LIMIT_WINDOW} soniya\n"
        f"• Kunlik: {config.DAILY_LIMIT} so'rov\n"
        f"• Maks. fayl: {config.MAX_AUDIO_SIZE_MB} MB",
        parse_mode="HTML",
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message):
    db_user = await get_user(message.from_user.id)
    current = db_user.get("lang_pref", "auto") if db_user else "auto"
    await message.answer(
        f"🌐 <b>STT rejimini sozlash</b>\n\n"
        f"Hozirgi rejim: <b>{LANG_LABELS.get(current, current)}</b>\n\n"
        f"Yangi rejim tanlang:",
        reply_markup=lang_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang(callback: CallbackQuery):
    lang = callback.data.split(":", 1)[1]
    await set_lang_pref(callback.from_user.id, lang)
    label = LANG_LABELS.get(lang, lang)
    await callback.message.edit_text(
        f"✅ <b>Rejim o'zgartirildi!</b>\n\n"
        f"Yangi rejim: <b>{label}</b>\n\n"
        f"Endi ovozli xabar yuboring. 🎤",
        parse_mode="HTML",
    )
    await callback.answer(f"✅ {label}")


@router.callback_query(F.data == "tts")
async def cb_tts(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("last_stt_text") or data.get("last_bot_reply", "")
    
    if not text:
        await callback.answer("Matn topilmadi.", show_alert=True)
        return

    await callback.answer("🔊 Tayyorlanmoqda...")
    await bot.send_chat_action(callback.message.chat.id, "record_voice")

    async with aiosqlite.connect(config.DB_PATH) as db:
        ui_lang = await get_ui_lang(db, callback.from_user.id)

    file_path = None
    try:
        file_path = await text_to_speech(text, lang=ui_lang)
        audio = FSInputFile(file_path)
        await bot.send_voice(callback.message.chat.id, voice=audio)
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

@router.message(Command("mystats"))
async def cmd_mystats(message: Message):
    uid = message.from_user.id
    db_user = await get_user(uid)
    if not db_user:
        await message.answer("Hali statistika yo'q. Biror xabar yuboring!")
        return

    stats = await get_user_full_stats(uid)
    lang = db_user.get("lang_pref", "auto")
    joined = db_user.get("joined_at", "—")[:10]
    success_rate = (
        round(stats["successful"] / stats["total"] * 100, 1)
        if stats["total"] > 0 else 0
    )

    await message.answer(
        f"👤 <b>Sizning statistikangiz</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 A'zo bo'lgan: <i>{joined}</i>\n"
        f"🌐 Joriy rejim: <b>{LANG_LABELS.get(lang, lang)}</b>\n\n"
        f"<b>📊 So'rovlar:</b>\n"
        f"• Jami: <b>{stats['total']}</b>\n"
        f"• Bugun: <b>{stats['today']}</b> / {config.DAILY_LIMIT}\n"
        f"• Qolgan: <b>{config.DAILY_LIMIT - stats['today']}</b>\n"
        f"• Muvaffaqiyat: <b>{success_rate}%</b>\n\n"
        f"<b>⚡ Sifat:</b>\n"
        f"• O'rtacha vaqt: <b>{stats['avg_duration']}s</b>\n"
        f"• Jami belgilar: <b>{stats['total_chars']:,}</b>\n\n"
        f"<b>🤖 AI Chat:</b>\n"
        f"• Jami xabarlar: <b>{stats.get('chat_messages', 0)}</b>",
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════
#  AI CHAT BUYRUQLARI (yangi)
# ══════════════════════════════════════════════════════════════

@router.message(Command("chat"))
async def cmd_chat(message: Message, state: FSMContext):
    """AI Chat rejimini boshlash."""
    await state.set_state(ChatState.active)
    await message.answer(
        "🤖 <b>AI Chat rejimi faol!</b>\n\n"
        "Gemini AI bilan erkin suhbatlashishingiz mumkin.\n"
        "• Har qanday savol yoki mavzuda gaplashing\n"
        "• Bot sizning kontekstingizni eslab qoladi\n"
        "• 📸 Rasm yuborsangiz — uni ham tahlil qilaman\n\n"
        "<i>Chiqish uchun: /endchat yoki quyidagi tugma</i>",
        parse_mode="HTML",
        reply_markup=chat_keyboard(),
    )


@router.message(ChatState.active, F.text & ~F.text.startswith("/"))
async def handle_chat_message(message: Message, state: FSMContext):
    """Chat rejimida matn xabarni Gemini ga yuborish."""
    user_id = message.from_user.id
    user_text = message.text.strip()

    if len(user_text) > 4000:
        await message.reply("⚠️ Xabar juda uzun (maks. 4000 belgi).")
        return

    status = await message.reply("🤔 <i>Javob tayyorlanmoqda...</i>", parse_mode="HTML")

    try:
        history = await get_chat_history(user_id, limit=config.CHAT_HISTORY_LIMIT)
        reply_text = await chat_with_gemini(history, user_text)

        # Ikkala xabarni ham tarixga saqlash
        await add_chat_message(user_id, "user", user_text)
        await add_chat_message(user_id, "model", reply_text)
        await state.update_data(last_bot_reply=reply_text)

        if len(reply_text) > 4096:
            reply_text = reply_text[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"

        await status.edit_text(reply_text, parse_mode="HTML", reply_markup=chat_keyboard())

    except Exception as e:
        logger.error(f"Chat xatolik (user={user_id}): {e}")
        await status.edit_text(
            f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>\n\nQayta urinib ko'ring.",
            parse_mode="HTML",
        )




@router.message(Command("endchat"))
async def cmd_endchat(message: Message, state: FSMContext):
    current = await state.get_state()
    if current == ChatState.active.state:
        await state.clear()
        await message.answer(
            "✅ <b>Chat rejimidan chiqildi.</b>\n\n"
            "STT yoki tarjima uchun xabar yuboring.\n"
            "Chat tarixini ko'rish: /history",
            parse_mode="HTML",
        )
    else:
        await message.answer("Siz hozir chat rejimida emassiz. Boshlash: /chat")


@router.message(Command("history"))
async def cmd_history(message: Message):
    """So'nggi chat tarixini ko'rsatish."""
    history = await get_chat_history_display(message.from_user.id, limit=10)
    if not history:
        await message.answer(
            "📭 <b>Chat tarixi yo'q.</b>\n\nChat boshlash: /chat",
            parse_mode="HTML",
        )
        return

    lines = ["📜 <b>So'nggi 10 ta xabar:</b>\n"]
    for msg in history:
        icon = "👤" if msg["role"] == "user" else "🤖"
        snippet = msg["content"][:120] + ("…" if len(msg["content"]) > 120 else "")
        time_str = msg["created_at"][11:16]  # HH:MM
        lines.append(f"{icon} <i>[{time_str}]</i>\n{snippet}\n")

    text = "\n".join(lines)
    if len(text) > 4096:
        text = text[:4040] + "\n\n⚠️ <i>Qisqartirildi</i>"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("clearhistory"))
async def cmd_clearhistory(message: Message):
    """Chat tarixini tozalash."""
    await clear_chat_history(message.from_user.id)
    await message.answer(
        "🗑 <b>Chat tarixi tozalandi!</b>\n\n"
        "Yangi suhbat boshlash: /chat",
        parse_mode="HTML",
    )


# Chat tugmalari (callback)
@router.callback_query(F.data == "chat:exit")
async def cb_chat_exit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "✅ <b>Chat rejimidan chiqildi.</b>\n\n"
        "STT yoki tarjima uchun xabar yuboring.",
        parse_mode="HTML",
    )
    await callback.answer("Chat yakunlandi")


@router.callback_query(F.data == "chat:clear")
async def cb_chat_clear(callback: CallbackQuery):
    await clear_chat_history(callback.from_user.id)
    await callback.answer("✅ Tarix tozalandi!", show_alert=True)


@router.callback_query(F.data == "chat:history")
async def cb_chat_history(callback: CallbackQuery):
    history = await get_chat_history_display(callback.from_user.id, limit=6)
    if not history:
        await callback.answer("📭 Tarix yo'q hali", show_alert=True)
        return

    lines = ["📜 <b>So'nggi xabarlar:</b>\n"]
    for msg in history:
        icon = "👤" if msg["role"] == "user" else "🤖"
        snippet = msg["content"][:80] + ("…" if len(msg["content"]) > 80 else "")
        lines.append(f"{icon} {snippet}")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "switch:chat")
async def cb_switch_to_chat(callback: CallbackQuery, state: FSMContext):
    """Tarjima klaviaturasidan chat ga o'tish."""
    await state.set_state(ChatState.active)
    await callback.message.edit_text(
        "🤖 <b>AI Chat rejimi faol!</b>\n\nXabaringizni yozing:",
        parse_mode="HTML",
        reply_markup=chat_keyboard(),
    )
    await callback.answer("Chat rejimi!")


# ══════════════════════════════════════════════════════════════
#  RASM TAHLILI (yangi)
# ══════════════════════════════════════════════════════════════

async def _handle_photo_core(message: Message, bot: Bot, prompt: str | None = None):
    """Rasmni Gemini Vision orqali tahlil qilish — asosiy mantiq."""
    photo = message.photo[-1]
    caption = (message.caption or "").strip().lower()

    if caption in ("ocr", "/ocr", "matn", "text"):
        await bot.send_chat_action(message.chat.id, "typing")
        status = await message.reply("📝 <i>Matn aniqlanmoqda...</i>", parse_mode="HTML")
        try:
            file = await bot.get_file(photo.file_id)
            buf = io.BytesIO()
            await bot.download_file(file.file_path, buf)
            image_bytes = buf.getvalue()
            result = await extract_text_from_image(image_bytes)
            if len(result) > 4096:
                result = result[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"
            await status.edit_text(f"📝 <b>Rasmdagi matn:</b>\n\n{result}", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Photo OCR xatolik (user={message.from_user.id}): {e}")
            await status.edit_text(f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>", parse_mode="HTML")
        return

    if prompt is None:
        prompt = (
            message.caption.strip()
            if message.caption
            else "Bu rasmni batafsil tahlil qil. Nima ko'rayotganingni aniq tushuntir."
        )
    status = await message.reply("🔍 <i>Rasm tahlil qilinmoqda...</i>", parse_mode="HTML")
    try:
        file = await bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        image_bytes = buf.getvalue()
        result = await analyze_image(image_bytes, prompt)
        if len(result) > 4096:
            result = result[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"
        await status.edit_text(f"🖼 <b>Rasm tahlili:</b>\n\n{result}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Photo handler xatolik (user={message.from_user.id}): {e}")
        await status.edit_text(f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>", parse_mode="HTML")


async def _handle_photo_by_file_id(message: Message, bot: Bot, file_id: str, prompt: str):
    """File ID bo'yicha rasmni Gemini Vision ga yuborish (forward + keyingi prompt uchun)."""
    status = await message.reply("🔍 <i>Rasm tahlil qilinmoqda...</i>", parse_mode="HTML")
    try:
        file = await bot.get_file(file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        image_bytes = buf.getvalue()
        result = await analyze_image(image_bytes, prompt)
        if len(result) > 4096:
            result = result[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"
        await status.edit_text(f"🖼 <b>Rasm tahlili:</b>\n\n{result}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Photo (file_id) xatolik (user={message.from_user.id}): {e}")
        await status.edit_text(f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>", parse_mode="HTML")


# ── Rasm handlerlari ──────────────────────────────────────────

_PHOTO_ASK_TEXT = (
    "📸 <b>Rasm qabul qilindi!</b>\n\n"
    "✏️ Bu rasm bilan nima qilishni xohlaysiz? Yozing:\n\n"
    "<i>Masalan: tarjima qil / nima bor / matnni o'qi / tahlil qil</i>\n\n"
    "Bekor qilish: /cancel"
)


@router.message(ChatState.active, F.photo)
async def handle_chat_photo(message: Message, bot: Bot, state: FSMContext):
    """Chat rejimida rasm: caption bo'lsa darhol, bo'lmasa so'ra."""
    caption = message.caption.strip() if message.caption else None
    if caption:
        await _handle_photo_core(message, bot, caption)
    else:
        await state.set_state(PhotoState.waiting_for_prompt)
        await state.update_data(
            photo_file_id=message.photo[-1].file_id,
            from_chat=True,
        )
        await message.answer(_PHOTO_ASK_TEXT, parse_mode="HTML")


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, state: FSMContext):
    """Oddiy rasm: caption bo'lsa darhol, bo'lmasa (forward) prompt so'ra."""
    caption = message.caption.strip() if message.caption else None
    if caption:
        await _handle_photo_core(message, bot, caption)
    else:
        await state.set_state(PhotoState.waiting_for_prompt)
        await state.update_data(
            photo_file_id=message.photo[-1].file_id,
            from_chat=False,
        )
        await message.answer(_PHOTO_ASK_TEXT, parse_mode="HTML")


@router.message(PhotoState.waiting_for_prompt, F.text & ~F.text.startswith("/"))
async def handle_photo_prompt(message: Message, bot: Bot, state: FSMContext):
    """Foydalanuvchi rasm uchun prompt yuborganda."""
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    from_chat = data.get("from_chat", False)

    if from_chat:
        await state.set_state(ChatState.active)
    else:
        await state.clear()

    await _handle_photo_by_file_id(message, bot, file_id, message.text.strip())


# ══════════════════════════════════════════════════════════════
#  MATN → GEMINI CHAT (default rejim)
# ══════════════════════════════════════════════════════════════

@router.message(Command("translate"))
async def cmd_translate(message: Message, state: FSMContext):
    """Tarjima rejimini boshlash — foydalanuvchi matn yuboradi."""
    await state.set_state(TranslateState.waiting_text)
    await message.answer(
        "🌐 <b>Tarjima rejimi</b>\n\n"
        "Tarjima qilinishi kerak bo'lgan matnni yuboring:\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )


@router.message(Command("ocr"))
async def cmd_ocr(message: Message, state: FSMContext):
    await state.set_state(OCRState.waiting_image)
    await message.answer(
        "🖼 Matnni ko'chirmoqchi bo'lgan rasmni yuboring:\n"
        "(Yoki istalgan rasmga caption qilib 'ocr' yozing)",
        parse_mode="HTML",
    )


@router.message(OCRState.waiting_image, F.photo)
async def handle_ocr_photo(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    photo = message.photo[-1]
    await bot.send_chat_action(message.chat.id, "typing")
    status = await message.reply("📝 <i>Matn aniqlanmoqda...</i>", parse_mode="HTML")

    try:
        file = await bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, buf)
        image_bytes = buf.getvalue()
        result = await extract_text_from_image(image_bytes)
        if len(result) > 4096:
            result = result[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"
        await status.edit_text(f"📝 <b>Rasmdagi matn:</b>\n\n{result}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"OCR handler xatolik (user={message.from_user.id}): {e}")
        await status.edit_text(f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>", parse_mode="HTML")


@router.message(Command("summarize"))
async def cmd_summarize(message: Message, state: FSMContext):
    await state.set_state(SummarizeState.waiting_text)
    await message.answer("📝 Xulosa qilmoqchi bo'lgan matnni yuboring:")


@router.message(SummarizeState.waiting_text, F.text)
async def handle_summarize_text(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await bot.send_chat_action(message.chat.id, "typing")

    async with aiosqlite.connect(config.DB_PATH) as db:
        ui_lang = await get_ui_lang(db, message.from_user.id)

    result = await summarize_text(message.text, target_lang=ui_lang)
    await message.answer(f"📋 **Xulosa:**\n\n{result}", parse_mode="Markdown")


@router.message(TranslateState.waiting_text, F.text & ~F.text.startswith("/"))
async def handle_translate_input(message: Message, state: FSMContext):
    """Tarjima uchun matn qabul qilish."""
    text = message.text.strip()
    if len(text) < 2:
        await message.answer("⚠️ Matn juda qisqa.")
        return
    if len(text) > 4000:
        await message.answer(f"⚠️ Matn juda uzun ({len(text)} belgi). Maksimal: 4000 belgi.")
        return

    await state.update_data(pending_text=text)
    await state.set_state(TranslateState.waiting_lang)

    preview = text[:120] + ("..." if len(text) > 120 else "")
    await message.answer(
        f"📝 <b>Matn qabul qilindi</b> ({len(text)} belgi)\n\n"
        f"<i>{preview}</i>\n\n"
        f"🌐 Qaysi tilga tarjima qilish kerak?",
        reply_markup=translate_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message, state: FSMContext):
    """
    Har qanday matn — Gemini Chat ga yuboriladi (default rejim).
    Tarjima uchun /translate buyrug'idan foydalaning.
    """
    user_id = message.from_user.id
    user_text = message.text.strip()

    if len(user_text) < 2:
        await message.answer("⚠️ Matn juda qisqa.")
        return
    if len(user_text) > 4000:
        await message.answer(
            f"⚠️ Matn juda uzun ({len(user_text)} belgi).\n"
            f"Maksimal: 4000 belgi."
        )
        return

    status = await message.reply("🤔 <i>Javob tayyorlanmoqda...</i>", parse_mode="HTML")

    try:
        history = await get_chat_history(user_id, limit=config.CHAT_HISTORY_LIMIT)
        reply_text = await chat_with_gemini(history, user_text)

        await add_chat_message(user_id, "user", user_text)
        await add_chat_message(user_id, "model", reply_text)

        if len(reply_text) > 4096:
            reply_text = reply_text[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"

        await status.edit_text(reply_text, parse_mode="HTML", reply_markup=chat_keyboard())

    except Exception as e:
        logger.error(f"Chat xatolik (user={user_id}): {e}")
        await status.edit_text(
            f"❌ <b>Xatolik:</b> <i>{str(e)[:200]}</i>\n\nQayta urinib ko'ring.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("translate:"))
async def cb_translate(callback: CallbackQuery, state: FSMContext):
    target = callback.data.split(":", 1)[1]

    if target == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Bekor qilindi.")
        await callback.answer()
        return

    data = await state.get_data()
    text = data.get("pending_text")

    if not text:
        await callback.answer("❌ Matn topilmadi. Qayta yuboring.", show_alert=True)
        await state.clear()
        return

    flag = TRANSLATE_TARGET_LABELS.get(target, target)
    await callback.message.edit_text(
        f"⏳ <b>Tarjima qilinmoqda...</b>\n"
        f"🎯 Maqsad: {flag}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "summarize")
async def cb_summarize(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("last_stt_text", "")
    if not text:
        await callback.answer("Matn topilmadi.", show_alert=True)
        return

    await bot.send_chat_action(callback.message.chat.id, "typing")
    result = await summarize_text(text)
    await callback.message.answer(f"📋 **Xulosa:**\n\n{result}", parse_mode="Markdown")
    await callback.answer()

    try:
        translated, detected = await translate_text(text, target)

        result = (
            f"🌐 <b>Tarjima natijasi</b>\n"
            f"🔍 Manba til: <i>{detected}</i>\n"
            f"🎯 Maqsad: <b>{flag}</b>\n"
            f"{'─'*30}\n\n"
            f"{translated}"
        )

        if len(result) > 4096:
            result = result[:4040] + "\n\n⚠️ <i>Matn qisqartirildi</i>"

        await callback.message.edit_text(result, parse_mode="HTML")
        await log_request(
            callback.from_user.id, 0, len(translated),
            success=True, req_type="translate"
        )

    except Exception as e:
        logger.error(f"Tarjima xatolik (user={callback.from_user.id}): {e}")
        await callback.message.edit_text(
            f"❌ <b>Tarjima xatoligi:</b>\n<i>{str(e)[:300]}</i>",
            parse_mode="HTML",
        )

    await state.clear()
    await callback.answer()


# ══════════════════════════════════════════════════════════════
#  AUDIO HANDLERLAR
# ══════════════════════════════════════════════════════════════

@router.message(F.voice)
async def handle_voice(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await _process_audio(message, message.voice.file_id, ".ogg", bot)


@router.message(F.audio)
async def handle_audio(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    file_name = message.audio.file_name or "audio.mp3"
    ext = os.path.splitext(file_name)[1].lower() or ".mp3"
    await _process_audio(message, message.audio.file_id, ext, bot)


@router.message(F.video_note)
async def handle_video_note(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await _process_audio(message, message.video_note.file_id, ".mp4", bot)


@router.message(F.video)
async def handle_video(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    file_name = message.video.file_name or "video.mp4"
    ext = os.path.splitext(file_name)[1].lower() or ".mp4"
    await _process_audio(message, message.video.file_id, ext, bot)


# ══════════════════════════════════════════════════════════════
#  ADMIN BUYRUQLAR
# ══════════════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not _is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q.")
        return
    await message.answer(
        "👑 <b>Admin Panel</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    stats = await get_global_stats()
    total = stats["total_requests"]
    success_rate = (
        round(stats["successful"] / total * 100, 1) if total > 0 else 0
    )

    await callback.message.edit_text(
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"<b>👥 Foydalanuvchilar:</b>\n"
        f"• Jami: <b>{stats['total_users']}</b>\n"
        f"• Bugun aktiv: <b>{stats['active_today']}</b>\n"
        f"• Bloklangan: <b>{stats['banned_users']}</b>\n\n"
        f"<b>📨 So'rovlar:</b>\n"
        f"• Jami: <b>{total}</b>\n"
        f"• Bugun: <b>{stats['requests_today']}</b>\n"
        f"• Muvaffaqiyat: <b>{success_rate}%</b>\n"
        f"• Tarjimalar: <b>{stats['translate_requests']}</b>\n\n"
        f"<b>🤖 AI Chat:</b>\n"
        f"• Jami xabarlar: <b>{stats.get('chat_messages', 0)}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    ids = await get_all_user_ids()
    await callback.message.edit_text(
        f"👥 <b>Foydalanuvchilar</b>\n\n"
        f"Jami: <b>{len(ids)}</b> aktiv foydalanuvchi",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⛔ Ruxsat yo'q!", show_alert=True)
        return

    await state.set_state(BroadcastState.waiting_message)
    await callback.message.answer(
        "📢 <b>Broadcast xabari</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni kiriting.\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer("❌ Bekor qilindi.")
    else:
        await message.answer("Hozir aktiv jarayon yo'q.")


@router.message(BroadcastState.waiting_message)
async def handle_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        return

    await state.clear()
    user_ids = await get_all_user_ids()

    sent = 0
    failed = 0
    status_msg = await message.answer(
        f"📢 <b>Broadcast yuborilmoqda...</b>\n"
        f"👥 Manzillar: {len(user_ids)}",
        parse_mode="HTML",
    )

    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"📢 <b>Broadcast yakunlandi!</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Xatolik: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if not _is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Foydalanish: /ban <user_id>")
        return
    uid = int(args[1])
    await ban_user(uid, True)
    await message.answer(f"🚫 Foydalanuvchi <code>{uid}</code> bloklandi.", parse_mode="HTML")


@router.message(Command("unban"))
async def cmd_unban(message: Message):
    if not _is_admin(message.from_user.id):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Foydalanish: /unban <user_id>")
        return
    uid = int(args[1])
    await ban_user(uid, False)
    await message.answer(f"✅ Foydalanuvchi <code>{uid}</code> blokdan chiqarildi.", parse_mode="HTML")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    await init_db()

    bot = Bot(token=config.BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.message.middleware(AuthMiddleware())

    bot_info = await bot.get_me()
    logger.info(f"✅ Bot ishga tushdi: @{bot_info.username}")
    print(f"✅ Bot ishga tushdi: @{bot_info.username}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())