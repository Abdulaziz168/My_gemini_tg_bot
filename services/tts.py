# services/tts.py
import asyncio
import os
import tempfile
from gtts import gTTS

LANG_MAP = {
    "uz": "uz",
    "ru": "ru",
    "en": "en",
}

async def text_to_speech(text: str, lang: str = "uz") -> str:
    """
    Matnni ovozga aylantiradi.
    Returns: mp3 fayl yo'li (foydalanib bo'lgach o'chirish kerak)
    """
    gtts_lang = LANG_MAP.get(lang, "uz")

    # gTTS sinxron — thread pool da ishlatamiz
    def _generate():
        tts = gTTS(text=text, lang=gtts_lang, slow=False)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False, dir="downloads"
        )
        tts.save(tmp.name)
        return tmp.name

    loop = asyncio.get_event_loop()
    file_path = await loop.run_in_executor(None, _generate)
    return file_path