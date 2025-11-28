# relay_bot.py
import os
import re
import json
import logging
from time import time
from pathlib import Path
from typing import Dict

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import ParseMode
from aiogram import F
from aiogram.utils.keyboard import ReplyKeyboardRemove
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("relay_bot")

# CONFIG from .env (defaults come from values you gave)
RELAY_TOKEN = os.getenv("RELAY_TOKEN", "8224146762:AAEJpeFIHmMeG2fjUn7ccMBiupA9Cxuewew")
TARGET_GROUP_ID = int(os.getenv("TARGET_GROUP_ID", "-1003275777221"))
TARGET_BOT_ID = int(os.getenv("TARGET_BOT_ID", "7574815513"))
REPLY_BACK_TO = os.getenv("REPLY_BACK_TO", "group")       # "group" or "user"
DELETE_ORIGINAL = os.getenv("DELETE_ORIGINAL", "yes").lower() in ("1", "true", "yes")
PERSIST_FILE = os.getenv("PERSIST_FILE", "pending_map.json")

if not RELAY_TOKEN or TARGET_GROUP_ID == 0 or TARGET_BOT_ID == 0:
    raise SystemExit("Set RELAY_TOKEN, TARGET_GROUP_ID and TARGET_BOT_ID in .env or environment.")

bot = Bot(token=RELAY_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# In-memory pending map: key -> metadata
pending: Dict[str, dict] = {}

# Load persistence file if exists
persist_path = Path(PERSIST_FILE)
if persist_path.exists():
    try:
        pending = json.loads(persist_path.read_text())
        logger.info("Loaded pending map with %d entries", len(pending))
    except Exception:
        logger.exception("Failed to load persistence file; starting with empty pending map.")
        pending = {}

def save_pending():
    try:
        persist_path.write_text(json.dumps(pending))
    except Exception:
        logger.exception("Failed to save pending map")

# Cleaning regexes
JOIN_LINK_RE = re.compile(r"https?://t\.me/[A-Za-z0-9_+/=%-]+")
JOIN_FIELD_RE = re.compile(r'(?i)"join_(?:main|backup)"\s*:\s*".+?"\s*(,)?')
UNWANTED_KEYS_RE = re.compile(r'(?im)^\s*"?(join_main|join_backup|join_.*invite|join.*)"?.*$', re.MULTILINE)

def clean_text(text: str) -> str:
    """Strip join links/fields and try to extract respCode/respMessage."""
    if not text:
        return ""
    text = JOIN_LINK_RE.sub("", text)
    text = JOIN_FIELD_RE.sub("", text)
    text = UNWANTED_KEYS_RE.sub("", text)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()

    # Try to extract respCode and respMessage if present
    m_code = re.search(r'"respCode"\s*:\s*"?(?P<code>\d+)"?', text)
    mm = re.search(r'"respMessage"\s*:\s*"(?P<msg>[^"]*)"', text)
    if m_code or mm:
        out = ["📁 Family Information:"]
        if m_code:
            out.append(f"• Code: <code>{m_code.group('code')}</code>")
        if mm:
            out.append(f"• Message: {mm.group('msg')}")
        return "\n".join(out)
    return text

def pending_key(chat_id: int, msg_id: int) -> str:
    return f"{chat_id}:{msg_id}"

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer("Relay bot ready. Use /familyinfo <number> to query.", reply_markup=ReplyKeyboardRemove())

@dp.message(Command("familyinfo"))
async def familyinfo_handler(msg: types.Message):
    args = msg.text.partition(" ")[2].strip()
    if not args:
        await msg.reply("Usage: /familyinfo <number>\nExample: /familyinfo 524928543777")
        return

    query_text = args
    try:
        # send request to target group
        sent = await bot.send_message(chat_id=TARGET_GROUP_ID, text=query_text)
        key = pending_key(sent.chat.id, sent.message_id)
        pending[key] = {
            "origin_chat_id": msg.chat.id,
            "origin_user_id": msg.from_user.id,
            "origin_message_id": msg.message_id,
            "query_text": query_text,
            "sent_time": int(time())
        }
        save_pending()
        await msg.reply("✅ Request forwarded to target group. I'll post the cleaned reply when it's ready.")
    except Exception as e:
        logger.exception("Failed forwarding to target group: %s", e)
        await msg.reply("Failed to forward request. Make sure the relay bot is added to the target group and can send messages.")

@dp.message(F.chat.id == TARGET_GROUP_ID, F.from_user.is_bot == True)
async def on_friendbot_message(msg: types.Message):
    # Only handle messages from the designated friend-bot
    if msg.from_user.id != TARGET_BOT_ID:
        return

    logger.info("Received message from friend-bot in target group: %s", msg.message_id)

    linked = None
    # Ideal: friend-bot replies to our message (reply_to_message)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        try:
            me = await bot.get_me()
            if msg.reply_to_message.from_user.id == me.id:
                key = pending_key(msg.reply_to_message.chat.id, msg.reply_to_message.message_id)
                linked = pending.get(key)
        except Exception:
            logger.exception("get_me failed")

    # Fallback: try to match by query_text substring
    if not linked:
        text_lower = (msg.text or msg.caption or "").lower()
        for k, v in list(pending.items()):
            if v.get("query_text", "").lower() in text_lower:
                linked = v
                pending.pop(k, None)
                save_pending()
                break

    if not linked:
        logger.info("Could not map friend-bot reply to pending request. Ignoring.")
        return

    original_text = msg.text or msg.caption or ""
    cleaned = clean_text(original_text)
    if not cleaned:
        cleaned = "⚠️ Bot replied but nothing remained after cleaning."

    origin_chat = linked["origin_chat_id"]
    origin_user = linked["origin_user_id"]

    # Attempt to delete the friend-bot's noisy message
    if DELETE_ORIGINAL:
        try:
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception:
            logger.exception("Could not delete friend-bot message (insufficient rights?).")

    # Also remove the relay's original message in the target group if present
    if msg.reply_to_message and msg.reply_to_message.from_user:
        try:
            me = await bot.get_me()
            if msg.reply_to_message.from_user.id == me.id:
                try:
                    await bot.delete_message(chat_id=msg.chat.id, message_id=msg.reply_to_message.message_id)
                except Exception:
                    pass
                # clear mapping
                pending.pop(pending_key(msg.reply_to_message.chat.id, msg.reply_to_message.message_id), None)
                save_pending()
        except Exception:
            pass

    # Send the cleaned message back to the origin (group or DM)
    try:
        if REPLY_BACK_TO == "user":
            try:
                await bot.send_message(chat_id=origin_user, text=cleaned, parse_mode=ParseMode.HTML)
            except Exception:
                # fallback to origin chat
                await bot.send_message(chat_id=origin_chat, text=cleaned, parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(chat_id=origin_chat, text=cleaned, parse_mode=ParseMode.HTML)
    except Exception:
        logger.exception("Failed sending cleaned message back")

@dp.message()
async def fallback(message: types.Message):
    return

if __name__ == "__main__":
    import asyncio
    from aiogram import executor
    logger.info("Starting relay bot")
    executor.start_polling(dp, skip_updates=True)
