import asyncio
import json
import logging
import re
import random
from google import genai
from config import config

logger = logging.getLogger(__name__)

client = genai.Client(api_key=config.GEMINI_API_KEY)

# Tarjima maqsad tillari
TARGET_LANG_NAMES = {
    "uz": "Uzbek (O'zbek lotin alifbosi)",
    "ru": "Russian (Русский)",
    "en": "English",
    "tr": "Turkish (Türkçe)",
    "de": "German (Deutsch)",
    "fr": "French (Français)",
    "ar": "Arabic (العربية)",
    "zh": "Chinese (中文)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
    "es": "Spanish (Español)",
    "it": "Italian (Italiano)",
    "kk": "Kazakh (Қазақша)",
}


async def _call_gemini(prompt: str) -> str:
    """Gemini API ga eksponensial kutish (Exponential Backoff) bilan murojaat."""
    
    # Limitga urilganda ko'proq kutish uchun urinishlar sonini oshirish tavsiya etiladi
    max_retries = 4 
    base_delay = 2.0  # Boshlang'ich kutish vaqti (soniya)

    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=config.GEMINI_MODEL,
                contents=prompt,
            )
            return response.text.strip()
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Gemini attempt {attempt + 1} failed: {error_msg}")

            if attempt < max_retries - 1:
                # Agar xatolik kvota (429) bilan bog'liq bo'lsa
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                    # Eksponensial o'sish: 2^0=1, 2^1=2, 2^2=4 + tasodifiy millisoniyalar (Jitter)
                    delay = (base_delay ** attempt) + random.uniform(0.5, 1.5)
                    logger.info(f"Rate Limit faollashdi. {delay:.2f} soniya kutilmoqda...")
                    await asyncio.sleep(delay)
                else:
                    # Boshqa oddiy xatoliklar uchun standart statik kutish
                    await asyncio.sleep(config.GEMINI_RETRY_DELAY)
            else:
                # Barcha urinishlar tugadi
                raise RuntimeError(f"Gemini API uzil-kesil rad etdi: {error_msg}")


async def translate_text(text: str, target_lang: str) -> tuple[str, str]:
    """
    Matnni aniqlangan tildan maqsad tilga tarjima qiladi.
    Returns: (translated_text, detected_language_name)
    """
    target_name = TARGET_LANG_NAMES.get(target_lang, target_lang)

    prompt = f"""You are a professional translator. 

Task:
1. Detect the language of the input text
2. Translate it accurately to {target_name}

Input text:
{text}

Respond ONLY with valid JSON in this exact format (no markdown, no extra text):
{{"detected": "language name in English", "translation": "your translation here"}}"""

    raw = await _call_gemini(prompt)

    # Markdown fencing ni tozalash
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()

    try:
        data = json.loads(raw)
        return data.get("translation", ""), data.get("detected", "unknown")
    except json.JSONDecodeError:
        # JSON parse bo'lmasa, butun javobni tarjima sifatida qaytarish
        logger.warning(f"JSON parse failed, using raw response. Raw: {raw[:200]}")
        return raw, "unknown"


async def translate_stt_result(transcribed: str, target_lang: str) -> str:
    """
    STT natijasini tarjima qiladi (ovozli xabar + tarjima rejimi).
    Returns: translated_text only
    """
    target_name = TARGET_LANG_NAMES.get(target_lang, target_lang)

    prompt = f"""Translate the following transcribed speech text to {target_name}.
Preserve the original meaning and natural tone.
Return ONLY the translation, nothing else.

Text:
{transcribed}"""

    return await _call_gemini(prompt)


async def detect_language(text: str) -> str:
    """Matn tilini aniqlaydi."""
    prompt = f"""Detect the language of this text and respond with ONLY the language name in English (e.g. "Russian", "Uzbek", "English").

Text: {text[:500]}"""

    result = await _call_gemini(prompt)
    return result.strip().split("\n")[0]

async def refine_and_format_text(text: str, target_lang: str) -> str:
    """
    Xom STT matnini AI Redaktor orqali rasmiy va chiroyli formatga o'tkazadi.
    Returns: refined_text only
    """
    target_name = TARGET_LANG_NAMES.get(target_lang, target_lang)

    prompt = f"""You are an expert copywriter and formal editor. 
Take the following raw transcribed speech and rewrite it into a highly professional, well-structured, and formal text in {target_name}.

Rules:
1. Fix all grammatical and punctuation errors.
2. Remove filler words (um, uh, you know) and repetitions.
3. Improve vocabulary to sound professional and polite.
4. Structure the text using paragraphs or bullet points if necessary.
5. DO NOT change the core meaning or facts.
6. Return ONLY the refined text, no conversational filler or markdown code blocks.

Raw text:
{text}"""

    return await _call_gemini(prompt)