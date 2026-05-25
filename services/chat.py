import asyncio
import base64
import io
import logging

from google import genai
from config import config

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=config.GEMINI_API_KEY)

# Suhbat boshida "shaxsiyat" o'rnatuvchi juft xabar
_PERSONA: list[dict] = [
    {
        "role": "user",
        "parts": [{"text": (
            "Sen foydali, aqlli va do'stona AI yordamchisisan. "
            "Foydalanuvchi qaysi tilda yozsa, shu tilda javob ber: "
            "o'zbek → o'zbek, rus → rus, ingliz → ingliz. "
            "Javoblarni lo'nda va aniq qil."
        )}],
    },
    {
        "role": "model",
        "parts": [{"text": "Tushundim! Har doim yordam berishga tayyorman. 🤝"}],
    },
]


async def chat_with_gemini(history: list[dict], user_message: str) -> str:
    """
    Gemini bilan multi-turn suhbat.

    Args:
        history: DB dan olingan tarix — Gemini formatida
                 [{"role": "user"|"model", "parts": [{"text": "..."}]}, ...]
        user_message: Foydalanuvchining yangi xabari

    Returns:
        Gemini javobi (string)
    """
    contents = _PERSONA + list(history) + [
        {"role": "user", "parts": [{"text": user_message}]}
    ]
    try:
        response = await asyncio.to_thread(
            _client.models.generate_content,
            model=config.GEMINI_MODEL,
            contents=contents,
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini chat xatolik: {e}")
        raise RuntimeError(f"AI javobi olinmadi: {e}")


async def analyze_image(
    image_bytes: bytes,
    prompt: str = "Bu rasmni batafsil tahlil qil. Nima ko'rayotganingni aniq tushuntir.",
    mime_type: str = "image/jpeg",
) -> str:
    """
    Gemini Vision orqali rasmni tahlil qilish.

    Args:
        image_bytes: Rasm baytlari
        prompt:      Foydalanuvchi so'rovi / caption
        mime_type:   image/jpeg | image/png | image/webp

    Returns:
        Tahlil matni
    """
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    try:
        response = await asyncio.to_thread(
            _client.models.generate_content,
            model=config.GEMINI_MODEL,
            contents=[{
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                    {"text": prompt},
                ]
            }],
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini vision xatolik: {e}")
        raise RuntimeError(f"Rasm tahlili muvaffaqiyatsiz: {e}")
