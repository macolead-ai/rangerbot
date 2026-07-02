import os
import sys
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from openai import AsyncOpenAI

# Logging → Render console
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- OpenAI client ---
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
ai_client = AsyncOpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

# --- Global bot mode: "GOALPULSE" (approved cover) or "REDIRECT" (funnel) ---
GLOBAL_BOT_MODE = "GOALPULSE"

# --- Redirect content ---
REDIRECT_TEXT = (
    "⚡️ Access real-time trading signals and educational market content "
    "to support your trading decisions every day."
)
REDIRECT_URL = "https://t.me/+PRbhOr9E405jY2Mx"

def redirect_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⚡️ Access Now 🟢", url=REDIRECT_URL)]])


# ============================================================
# Dummy HTTP server — Render Web Service needs an open port
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalPulse bot running.")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        return  # silence health-check spam

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


# ============================================================
# Safe sender — falls back to plain text if Markdown breaks
# ============================================================
async def safe_reply(update: Update, text: str, reply_markup=None):
    try:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except BadRequest as e:
        logger.warning(f"Markdown parse failed, sending plain text: {e}")
        await update.message.reply_text(text, reply_markup=reply_markup)


# ============================================================
# Handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE

    # ===== REDIRECT MODE =====
    if GLOBAL_BOT_MODE == "REDIRECT":
        await update.message.reply_text(REDIRECT_TEXT, reply_markup=redirect_markup())
        return

    # ===== GOALPULSE MODE (default) =====
    keyboard = [['⚡ Live Matches', '📊 Standings']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = (
        "⚽ *GoalPulse0bot — AI Football Companion* ⚽\n\n"
        "Powered by OpenAI! Ask me anything about match events, "
        "scores, goal details, line-ups, or league tables.\n\n"
        "Use the menu below or ask a football question directly!"
    )
    await safe_reply(update, welcome_text, reply_markup=reply_markup)


async def handle_ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_query=None):
    user_query = custom_query if custom_query else update.message.text
    chat_id = update.effective_chat.id

    if not ai_client:
        await safe_reply(update, "⚠️ System Error: OPENAI_API_KEY is missing in the Render environment.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    system_prompt = (
        "You are GoalPulse0bot, a football tracker and analyst. "
        "Your UI layout emulates the premium Flashscore app style. "
        "Guidelines:\n"
        "1. Structure output with distinct flags, country tags, and bold league headers.\n"
        "2. Break matches into clean rows: Home vs Away, Scorelines, Elapsed Time, "
        "and sub-rows for goals, yellow cards, and red cards.\n"
        "3. Use text-emoji flags (e.g. Argentina, England, France) at the start of rows.\n"
        "4. Keep updates snappy, direct, and readable like a digital scoreboard.\n"
        "5. If you do not have live data for a specific request, say so briefly and offer "
        "general info instead. Never invent specific live scores as if they were real-time facts."
    )

    try:
        response = await ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        ai_reply = response.choices[0].message.content
        if not ai_reply:
            ai_reply = "❌ Empty response. Please try again."
        await safe_reply(update, ai_reply)

    except Exception as e:
        logger.error(f"OpenAI Execution Error: {e}")
        await safe_reply(update, "❌ Failed to process the request. Please try again.")


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GLOBAL_BOT_MODE
    text = update.message.text
    if not text:
        return

    # ---- Admin secret toggle commands (work in any mode) ----
    if text == "REDIRECT":
        GLOBAL_BOT_MODE = "REDIRECT"
        await update.message.reply_text("✅ Mode changed! The bot now sends the trading access funnel.")
        return
    if text == "REVERSE":
        GLOBAL_BOT_MODE = "GOALPULSE"
        await update.message.reply_text("✅ Mode changed! The bot now works as the AI Football Companion.")
        return

    # ---- REDIRECT mode: send the trading message to everyone ----
    if GLOBAL_BOT_MODE == "REDIRECT":
        await update.message.reply_text(REDIRECT_TEXT, reply_markup=redirect_markup())
        return

    # ---- GOALPULSE mode: normal football routing ----
    logger.info(f"Routing text: {text}")

    if "Live" in text or "Matches" in text:
        prompt = "Show me live football scores worldwide, with match cards including goals and statistics."
        await handle_ai_response(update, context, custom_query=prompt)
    elif "Standings" in text or "League" in text:
        prompt = "Show current standings tables for the top European leagues and international groups."
        await handle_ai_response(update, context, custom_query=prompt)
    else:
        await handle_ai_response(update, context)


# ============================================================
# Main
# ============================================================
def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.critical("CRITICAL: TELEGRAM_BOT_TOKEN is missing!")
        return

    # Start the health server first (keeps Render Web Service alive)
    threading.Thread(target=run_health_server, daemon=True).start()

    logger.info("Initializing GoalPulse0bot...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router))

    logger.info("GoalPulse0bot online. Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
