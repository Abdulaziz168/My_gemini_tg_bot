from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ══════════════════════════════════════════════════════════════
#  LABELS (Foydalanuvchiga ko'rinadigan matnlar)
# ══════════════════════════════════════════════════════════════

LANG_LABELS = {
    "auto":         "🔍 Avtomatik",
    "uz":           "🇺🇿 O'zbekcha (STT)",
    "ru":           "🇷🇺 Русский (STT)",
    "en":           "🇬🇧 English (STT)",
    "translate_uz": "🌐→🇺🇿 O'zbekchaga tarjima",
    "translate_ru": "🌐→🇷🇺 Ruschaga tarjima",
    "translate_en": "🌐→🇬🇧 Inglizchaga tarjima",
    "redact_uz":    "✨ AI Redaktor (🇺🇿 O'zbekcha)",
    "redact_ru":    "✨ AI Redaktor (🇷🇺 Русский)",
}

TRANSLATE_TARGET_LABELS = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
    "tr": "🇹🇷 Türkçe",
    "de": "🇩🇪 Deutsch",
    "fr": "🇫🇷 Français",
    "ar": "🇸🇦 العربية",
    "kk": "🇰🇿 Қазақша",
}

# ══════════════════════════════════════════════════════════════
#  STT TIL TANLASH (Ovozli xabar uchun rejimlar)
# ══════════════════════════════════════════════════════════════

def lang_keyboard() -> InlineKeyboardMarkup:
    """Ovozli xabar STT rejimini tanlash. Mobil ekranga moslashtirilgan."""
    return InlineKeyboardMarkup(inline_keyboard=[
        # 1-qator: Asosiy tavsiya
        [
            InlineKeyboardButton(text="🔍 Avtomatik aniqlash (Tavsiya)", callback_data="lang:auto"),
        ],
        # 2-qator: Sof transkripsiya (STT)
        [
            InlineKeyboardButton(text="🇺🇿 O'zbek",  callback_data="lang:uz"),
            InlineKeyboardButton(text="🇷🇺 Рус",    callback_data="lang:ru"),
            InlineKeyboardButton(text="🇬🇧 Eng",    callback_data="lang:en"),
        ],
        # 3-qator: STT + Tarjima
        [
            InlineKeyboardButton(text="🌐→ 🇺🇿 UZ", callback_data="lang:translate_uz"),
            InlineKeyboardButton(text="🌐→ 🇷🇺 RU", callback_data="lang:translate_ru"),
            InlineKeyboardButton(text="🌐→ 🇬🇧 EN", callback_data="lang:translate_en"),
        ],
        # 4-qator: AI Redaktor (Matnni rasmiylashtirish)
        [
            InlineKeyboardButton(text="✨ AI Redaktor (UZ)", callback_data="lang:redact_uz"),
            InlineKeyboardButton(text="✨ AI Redaktor (RU)", callback_data="lang:redact_ru"),
        ],
    ])

# ══════════════════════════════════════════════════════════════
#  MATN TARJIMA (Text xabar uchun maqsad til)
# ══════════════════════════════════════════════════════════════

def translate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbek",  callback_data="translate:uz"),
            InlineKeyboardButton(text="🇷🇺 Рус",    callback_data="translate:ru"),
            InlineKeyboardButton(text="🇬🇧 Eng",    callback_data="translate:en"),
            
        ],
        [
            InlineKeyboardButton(text="🇹🇷 Türk",   callback_data="translate:tr"),
            InlineKeyboardButton(text="🇩🇪 Deu",    callback_data="translate:de"),
            InlineKeyboardButton(text="🇫🇷 Fra",    callback_data="translate:fr"),
        ],
        [
            InlineKeyboardButton(text="🇸🇦 Arab",   callback_data="translate:ar"),
            InlineKeyboardButton(text="🇰🇿 Qaz",    callback_data="translate:kk"),
        ],
        [
            InlineKeyboardButton(text="🤖 AI Chat", callback_data="switch:chat"),
            InlineKeyboardButton(text="❌ Bekor",   callback_data="translate:cancel"),
            InlineKeyboardButton(text="📋 Xulosa", callback_data="summarize"),
            InlineKeyboardButton(text="🔊 Ovozli", callback_data="tts")
        ],
    ])

# ══════════════════════════════════════════════════════════════
#  AI CHAT (yangi)
# ══════════════════════════════════════════════════════════════

def chat_keyboard() -> InlineKeyboardMarkup:
    """Chat rejimida tezkor harakatlar."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Tarixni tozalash", callback_data="chat:clear"),
            InlineKeyboardButton(text="📜 Tarixni ko'rish",  callback_data="chat:history"),
        ],
        [
            InlineKeyboardButton(text="� Ovozli", callback_data="tts"),
            InlineKeyboardButton(text="�🚪 Chatdan chiqish", callback_data="chat:exit"),
        ],
    ])

# ══════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika",  callback_data="admin:stats"),
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin:users"),
        ],
        [
            InlineKeyboardButton(text="📢 Broadcast",   callback_data="admin:broadcast"),
        ],
    ])
