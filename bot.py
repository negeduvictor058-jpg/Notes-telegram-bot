import os
import logging
import sqlite3
from datetime import datetime
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------- LOGGING ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- DATABASE ----------
DB_FILE = "notes.db"

def init_db():
    """Create the database table if it does not exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def add_note(user_id: int, text: str) -> int:
    """Save a new note and return its number."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO notes (user_id, text, created_at) VALUES (?, ?, ?)",
        (user_id, text, datetime.utcnow().isoformat())
    )
    note_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return note_id

def get_notes(user_id: int):
    """Get all notes for one user."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, created_at FROM notes WHERE user_id = ? ORDER BY id",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_note_by_id(user_id: int, note_id: int):
    """Get one specific note (only if it belongs to the user)."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def delete_note(user_id: int, note_id: int) -> bool:
    """Delete a note. Returns True if deleted."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?",
        (note_id, user_id)
    )
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

# ---------- AI EXPLAIN (using free Groq API) ----------
def explain_text(text: str) -> str:
    """Ask Groq AI to explain the note in very simple words."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "AI is not set up yet. Please add the GROQ_API_KEY secret."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {
                "role": "system",
                "content": "You are a friendly teacher. Explain the following note in very simple, easy-to-understand language. Use short sentences. Do not add extra information."
            },
            {
                "role": "user",
                "content": text
            }
        ],
        "temperature": 0.3,
        "max_tokens": 500
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"AI error: {e}")
        return "Sorry, I could not explain the note right now. Please try again later."

# ---------- BOT COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message."""
    await update.message.reply_text(
        "Hello! I am your Notes Bot.\n\n"
        "Just send me any message and I will save it as a note.\n\n"
        "Commands:\n"
        "/notes – show all your notes\n"
        "/explain 1 – explain note number 1 in simple words\n"
        "/delete 1 – delete note number 1\n"
        "/help – show this message again"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help message."""
    await start(update, context)

async def notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all notes for the user."""
    user_id = update.effective_user.id
    notes = get_notes(user_id)

    if not notes:
        await update.message.reply_text("You have no notes yet. Just send me a message to save one!")
        return

    message = "Your notes:\n\n"
    for note_id, text, created_at in notes:
        short_text = text[:80] + "..." if len(text) > 80 else text
        message += f"**{note_id}.** {short_text}\n\n"

    message += "\nTo explain a note: /explain 1\nTo delete a note: /delete 1"
    await update.message.reply_text(message)

async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explain a specific note using AI."""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Please give a note number.\nExample: /explain 1")
        return

    try:
        note_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please use a number.\nExample: /explain 1")
        return

    note = get_note_by_id(user_id, note_id)
    if not note:
        await update.message.reply_text("I could not find that note. Check the number with /notes")
        return

    await update.message.reply_text("Thinking... Please wait a moment.")
    explanation = explain_text(note[1])
    await update.message.reply_text(f"Simple explanation of note {note_id}:\n\n{explanation}")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a specific note."""
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text("Please give a note number.\nExample: /delete 1")
        return

    try:
        note_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please use a number.\nExample: /delete 1")
        return

    if delete_note(user_id, note_id):
        await update.message.reply_text(f"Note {note_id} has been deleted.")
    else:
        await update.message.reply_text("I could not find that note. Check the number with /notes")

async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically save any normal text message as a note."""
    user_id = update.effective_user.id
    text = update.message.text

    if not text or text.startswith("/"):
        return

    note_id = add_note(user_id, text)
    await update.message.reply_text(f"Note saved! Number: {note_id}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Exception while handling an update: {context.error}")

# ---------- MAIN ----------
def main():
    # Get secrets from environment variables
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN is missing!")
        return

    # Create database
    init_db()

    # Create the bot application
    app = Application.builder().token(token).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("notes", notes_command))
    app.add_handler(CommandHandler("explain", explain_command))
    app.add_handler(CommandHandler("delete", delete_command))

    # Save any normal message as a note
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, save_note))

    # Error handler
    app.add_error_handler(error_handler)

    # Start the bot
    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
