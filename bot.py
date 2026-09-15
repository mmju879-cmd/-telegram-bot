import os
import sqlite3
import httpx

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")

DB_PATH = "memory.db"

SYSTEM_PROMPT = """Ты личный Telegram-бот пользователя.
Отвечай на русском языке.
Поддерживай обычный дружеский разговор и творческие сцены.
Сохраняй контекст разговора.
Не задавай лишних вопросов.
Пиши естественно, связно и без повторяющихся формальных фраз."""


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        db.commit()


def get_history(chat_id, limit=20):
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            """
            SELECT role, content
            FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit)
        ).fetchall()

    return [
        {"role": role, "content": content}
        for role, content in reversed(rows)
    ]


def save_message(chat_id, role, content):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content)
        )
        db.commit()


async def ask_api(url, key, model, messages):
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.8
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload
        )

        response.raise_for_status()

        data = response.json()

        return data["choices"][0]["message"]["content"]


async def generate_reply(chat_id, text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    messages.extend(get_history(chat_id))

    messages.append({
        "role": "user",
        "content": text
    })

    # Сначала Gemini
    if GEMINI_KEY:
        try:
            return await ask_api(
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                GEMINI_KEY,
                "gemini-3.1-flash-lite",
                messages
            )
        except Exception:
            pass

    # Если Gemini не ответил — OpenRouter
    if OPENROUTER_KEY:
        return await ask_api(
            "https://openrouter.ai/api/v1/chat/completions",
            OPENROUTER_KEY,
            "openrouter/free",
            messages
        )

    raise RuntimeError("AI API keys are not configured.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет. Я здесь.")


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    text = update.message.text

    save_message(chat_id, "user", text)

    try:
        reply = await generate_reply(chat_id, text)

        save_message(chat_id, "assistant", reply)

        await update.message.reply_text(reply)

    except Exception:
        await update.message.reply_text(
            "Не удалось получить ответ от AI. Попробуй ещё раз."
        )


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured.")

    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
