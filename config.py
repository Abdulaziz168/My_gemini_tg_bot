import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # ── API Keys ────────────────────────────────────────────
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    GEMINI_API_KEY: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    GROQ_API_KEY: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))

    # ── Admin ───────────────────────────────────────────────
    ADMIN_IDS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    ])

    # ── Rate Limiting ───────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = 10
    RATE_LIMIT_WINDOW: int = 60
    DAILY_LIMIT: int = 200

    # ── STT (Groq Whisper) ──────────────────────────────────
    STT_MODEL: str = "whisper-large-v3"

    # ── Translation (Google Gemini) ─────────────────────────
    GEMINI_MODEL: str = "gemini-3.5-flash"   # gemini-3.5-flash mavjud bo'lsa shu, aks holda 2.0-flash
    GEMINI_MAX_RETRIES: int = 3
    GEMINI_RETRY_DELAY: float = 1.5

    # ── AI Chat ─────────────────────────────────────────────
    CHAT_HISTORY_LIMIT: int = 20   # Gemini kontekstiga yuboriladigan maksimal xabarlar soni

    # ── Files ───────────────────────────────────────────────
    DOWNLOAD_DIR: str = "downloads"
    MAX_AUDIO_SIZE_MB: int = 25

    # ── Database ────────────────────────────────────────────
    DB_PATH: str = "bot_database.db"

    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("❌ TELEGRAM_BOT_TOKEN topilmadi!")
        if not self.GROQ_API_KEY:
            raise ValueError("❌ GROQ_API_KEY topilmadi!")
        if not self.GEMINI_API_KEY:
            raise ValueError("❌ GEMINI_API_KEY topilmadi!")
        os.makedirs(self.DOWNLOAD_DIR, exist_ok=True)
        return self


config = Config().validate()
