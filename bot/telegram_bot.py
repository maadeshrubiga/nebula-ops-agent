"""
Telegram wiring.

Idempotency at the transport layer: Telegram can redeliver the same update
(e.g. after a slow response or reconnect). We record every update_id in
`processed_telegram_updates` (PRIMARY KEY) BEFORE doing any work; if the
insert fails (already seen), we skip processing entirely — separate from,
and in addition to, the bill-level finalize_token idempotency inside
billing.finalize_bill (which guards against a *different* replay path:
the owner tapping "finalize" twice, or the model retrying a tool call).
"""
import logging
import os
import sqlite3

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

from db.database import get_conn, init_db, seed_demo_products, transaction
from agent.orchestrator import run_turn, reset_history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nebula-ops-bot")


def _mark_update_processed(update_id: int) -> bool:
    """Returns True if this is the first time we've seen this update_id."""
    conn = get_conn()
    try:
        with transaction() as conn:
            conn.execute("INSERT INTO processed_telegram_updates (update_id) VALUES (?)", (update_id,))
        return True
    except sqlite3.IntegrityError:
        return False  # already processed — Telegram redelivered it


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if not _mark_update_processed(update.update_id):
        logger.info("Duplicate update %s ignored (Telegram redelivery).", update.update_id)
        return

    chat_id = update.message.chat_id
    text = update.message.text.strip()

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        reply, files = run_turn(chat_id, text, request_token=str(update.update_id))
    except Exception:
        logger.exception("Error handling message")
        await update.message.reply_text("Something went wrong on my end — please try that again.")
        return

    if reply:
        await update.message.reply_text(reply)
    for path in files:
        try:
            with open(path, "rb") as f:
                await context.bot.send_document(chat_id=chat_id, document=f, filename=os.path.basename(path))
        except Exception:
            logger.exception("Failed to send file %s", path)


async def handle_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/new — clears conversation context. Preferences/shop info/DB state are untouched
    on purpose: that's the memory-survives-a-new-chat requirement."""
    if not _mark_update_processed(update.update_id):
        return
    reset_history(update.message.chat_id)
    await update.message.reply_text("Started a fresh conversation. Store data and your preferences are unchanged.")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _mark_update_processed(update.update_id):
        return
    await update.message.reply_text(
        "Nebula Kirana Ops Agent ready. Talk to me like you'd talk to a smart assistant manager:\n"
        "- '50 packets of Maggi came in, cost ₹12'\n"
        "- 'make a bill: 2kg sugar, 1 maggi, UPI'\n"
        "- 'put ₹500 on Ramesh's credit'\n"
        "- 'today's sales?' / 'what's running out?'\n"
        "- '/new' to start a fresh conversation (your preferences stay remembered)."
    )


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    init_db()
    seed_demo_products()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("new", handle_new))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
