# STT Pro - Telegram AI Assistant

A multi-functional Telegram bot built with [Aiogram 3.x](https://docs.aiogram.dev/en/latest/). This bot provides advanced Speech-to-Text (STT) capabilities, AI-powered text translation, multi-turn conversations using Google Gemini, and image analysis via Gemini Vision.

## 🚀 Key Features

* **🎙️ Audio & Video Processing (STT):** Extracts text from voice messages, audio files (`.mp3`, `.ogg`, `.wav`, `.m4a`), and video notes.
* **🤖 AI Chat:** Continuous, context-aware conversations powered by Gemini API. Includes chat history memory.
* **📸 Image Analysis:** Processes images using Gemini Vision. Users can add captions to give the AI specific instructions.
* **📝 Smart Translation & Redaction:** Translates text across multiple languages automatically. Includes an "AI Redaktor" mode to formalize and refine raw text.
* **📊 User & Admin Statistics:** Tracks user request limits, daily usage, and bot-wide analytics.
* **🛡️ Admin Panel:** Built-in tools for user broadcasting, banning/unbanning, and viewing global metrics.

---

## 🛠️ Prerequisites

* **Python 3.9+**
* **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
* **Google Gemini API Key** (for chat, redaction, and image analysis)
* **STT Provider API Key** (depending on your `services.stt` implementation)
* SQLite / PostgreSQL (depending on your `database.db` setup)

---

## ⚙️ Installation & Setup

**1. Clone the repository:**
```bash
git clone <your-repository-url>
cd <your-project-directory>
