import os
import time
import logging
from openai import AsyncOpenAI
from config import config

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=config.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

# Whisper tomonidan to'liq qo'llab-quvvatlanadigan tillar
SUPPORTED_LANGS = {
    "uz", "ru", "en", "tr", "de", "fr",
    "ar", "zh", "ja", "ko", "es", "it",
    "pt", "pl", "uk", "fa", "hi", "nl",
}


async def transcribe_audio(file_path: str, lang_pref: str = "auto") -> tuple[str, float]:
    """
    Audio faylni Groq Whisper-large-v3 yordamida matnga o'girish.
    Returns: (transcribed_text, elapsed_seconds)
    """
    start = time.monotonic()

    try:
        with open(file_path, "rb") as audio_file:
            kwargs: dict = {
                "model": config.STT_MODEL,
                "file": audio_file,
                "response_format": "text",
            }

            # Faqat aniq STT rejimlarida til belgilanadi
            # translate_* rejimlarda Whisper avto-aniqlaydi
            if lang_pref in SUPPORTED_LANGS:
                kwargs["language"] = lang_pref

            response = await client.audio.transcriptions.create(**kwargs)

        elapsed = time.monotonic() - start
        text = response.strip() if isinstance(response, str) else response.text.strip()

        logger.info(f"✅ Groq STT | {len(text)} belgi | {elapsed:.2f}s | lang={lang_pref}")
        return text, elapsed

    except Exception as e:
        logger.error(f"Groq STT xatolik: {e}")
        raise RuntimeError(f"STT xatolik yuz berdi: {e}")
