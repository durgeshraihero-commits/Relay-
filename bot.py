#!/usr/bin/env python3
"""
bot.py — Telegram relay + HTTP API (single-file, ready for Render)

FULL VERSION (user-approved re-emission)
"""

import os
import re
import json
import time
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta

from aiohttp import web
from telethon import TelegramClient, events, errors
from pymongo import MongoClient

# ================= CONFIG =================
PORT = int(os.getenv("PORT", "10000"))

SESSION_FILE = os.getenv("SESSION_FILE", "relay_session.session")
TELETHON_API_ID = int(os.getenv("API_ID", "0"))
TELETHON_API_HASH = os.getenv("API_HASH", "")

FIRST_GROUP = os.getenv("FIRST_GROUP", "ethicalosinterr")
SECOND_GROUP = os.getenv("SECOND_GROUP", "ethicalosint")
THIRD_GROUP = os.getenv("THIRD_GROUP", "IntelXGroup")

MASTER_API_SECRET = os.getenv("MASTER_API_SECRET")

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")
API_KEYS_FALLBACK_FILE = os.getenv("API_KEYS_FALLBACK_FILE", "./api_keys_fallback.json")

THIRD_REPLY_WINDOW = int(os.getenv("THIRD_REPLY_WINDOW", "5"))
REPLY_STABILIZE_DELAY = int(os.getenv("REPLY_STABILIZE_DELAY", "3"))
FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))

# 🔴 ADDED FEATURE CONFIG
FETCH_EDIT_WATCH_TIME = int(os.getenv("FETCH_EDIT_WATCH_TIME", "15"))
FETCH_PHRASE = "⏳ Fetching"

API_REQUEST_TIMEOUT = int(
    os.getenv(
        "API_REQUEST_TIMEOUT",
        str(THIRD_REPLY_WINDOW + FETCH_EDIT_WATCH_TIME + FETCH_WAIT_TIME + 10)
    )
)

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("relay_api_bot")

# ================= MONGODB =================
mongo_client = None
db = None
api_keys_col = None

def init_mongo():
    global mongo_client, db, api_keys_col
    if not MONGODB_URI:
        logger.warning("Mongo not configured, using fallback file storage.")
        return
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        api_keys_col = db["api_keys"]
        try:
            api_keys_col.create_index([("key", 1)], unique=True)
        except Exception:
            pass
        try:
            if "expires_at_1" not in api_keys_col.index_information():
                api_keys_col.create_index([("expires_at", 1)])
        except Exception:
            pass
        logger.info("MongoDB initialized.")
    except Exception as e:
        logger.exception("MongoDB failed: %s", e)

# ================= FALLBACK STORAGE =================
def load_fallback_keys():
    try:
        if os.path.exists(API_KEYS_FALLBACK_FILE):
            with open(API_KEYS_FALLBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_fallback_keys(data):
    try:
        with open(API_KEYS_FALLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ================= UTILITIES =================
def _now_utc():
    return datetime.now(timezone.utc)

def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()

def _get_text(msg):
    return msg.text if msg and msg.text else ""

def is_fetch_message(text: str) -> bool:
    return bool(text) and FETCH_PHRASE.lower() in text.lower()

# ================= API KEY HELPERS =================
async def create_api_key_in_db(key, label="", owner="", duration_days=30):
    doc = {
        "key": key,
        "label": label,
        "owner": owner,
        "created_at": _iso(_now_utc()),
        "expires_at": _iso(_now_utc() + timedelta(days=duration_days)),
        "revoked": False,
    }
    if api_keys_col:
        await asyncio.get_running_loop().run_in_executor(None, api_keys_col.insert_one, doc)
    else:
        data = load_fallback_keys()
        data[key] = doc
        save_fallback_keys(data)
    return True, doc

async def find_api_key_doc(key):
    if api_keys_col:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.find_one({"key": key})
        )
    return load_fallback_keys().get(key)

async def validate_api_key_in_storage(key):
    if not key:
        return False, "missing_key"
    doc = await find_api_key_doc(key)
    if not doc:
        return False, "not_found"
    if doc.get("revoked"):
        return False, "revoked"
    try:
        if datetime.fromisoformat(doc["expires_at"]) < _now_utc():
            return False, "expired"
    except Exception:
        pass
    return True, doc

# ================= TEXT CLEANING =================
def filter_links_and_usernames(text):
    if not text:
        return "", False
    original = text
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return text.strip(), text != original

def remove_footer(text):
    if not text:
        return text
    lines = [l for l in text.splitlines() if '"footer"' not in l and '@frappeash' not in l]
    return "\n".join(lines)

def get_fetch_message(cmd):
    return "⏳ Fetching info… Please wait."

# ================= RUNTIME MAPS =================
message_map = {}
reverse_map = {}
message_map_third = {}
reverse_map_third = {}
forwarded_from_third = {}
status_messages = {}
api_request_map = {}

bot_status = {"running": False, "messages_forwarded": 0, "filtered_content": 0}

# ================= TELEGRAM CLIENT =================
client = TelegramClient(SESSION_FILE, TELETHON_API_ID, TELETHON_API_HASH)

# ================= FETCH WATCHER (NEW) =================
async def watch_fetch_then_resolve(forwarded_id: int):
    start = time.time()
    api_entry = api_request_map.get(forwarded_id)
    reply_info = forwarded_from_third.get(forwarded_id)
    last_seen = None

    while time.time() - start < FETCH_EDIT_WATCH_TIME:
        await asyncio.sleep(1)

        try:
            msg = await client.get_messages(THIRD_GROUP, ids=forwarded_id)
            if msg and msg.text and not is_fetch_message(msg.text):
                cleaned, _ = filter_links_and_usernames(remove_footer(msg.text))
                if cleaned:
                    if reply_info and reply_info.get("original_msg_id"):
                        await client.send_message(
                            FIRST_GROUP, cleaned,
                            reply_to=reply_info["original_msg_id"]
                        )
                    if api_entry and not api_entry["future"].done():
                        api_entry["future"].set_result([cleaned])
                return
        except Exception:
            pass

        async for m in client.iter_messages(THIRD_GROUP, reply_to=forwarded_id, limit=3):
            if last_seen == m.id:
                continue
            last_seen = m.id
            txt = _get_text(m)
            if txt and not is_fetch_message(txt):
                cleaned, _ = filter_links_and_usernames(remove_footer(txt))
                if cleaned:
                    if reply_info and reply_info.get("original_msg_id"):
                        await client.send_message(
                            FIRST_GROUP, cleaned,
                            reply_to=reply_info["original_msg_id"]
                        )
                    if api_entry and not api_entry["future"].done():
                        api_entry["future"].set_result([cleaned])
                return

# ================= STABILIZER =================
async def _stabilize_and_forward_third_reply(fid, rid):
    await asyncio.sleep(REPLY_STABILIZE_DELAY)
    info = forwarded_from_third.get(fid)
    if not info or info["count"] >= info["max"]:
        return
    msg = await client.get_messages(THIRD_GROUP, ids=rid)
    if not msg:
        return
    text = _get_text(msg)
    if is_fetch_message(text):
        asyncio.create_task(watch_fetch_then_resolve(fid))
        return
    cleaned, _ = filter_links_and_usernames(remove_footer(text))
    if cleaned:
        await client.send_message(FIRST_GROUP, cleaned, reply_to=info["original_msg_id"])
        info["count"] += 1

# ================= HANDLERS =================
@client.on(events.NewMessage(chats=FIRST_GROUP))
async def forward_command(event):
    text = _get_text(event.message)
    if not text or not (text.startswith("/") or text.startswith("2/")):
        return

    target = THIRD_GROUP if text.startswith("2/") else SECOND_GROUP
    clean = "/" + text[2:] if text.startswith("2/") else text

    status = await client.send_message(
        FIRST_GROUP, get_fetch_message(clean),
        reply_to=event.message.id
    )
    status_messages[event.message.id] = status

    forwarded = await client.send_message(target, clean)

    if target == THIRD_GROUP:
        forwarded_from_third[forwarded.id] = {
            "count": 0,
            "max": 1,
            "deadline": time.time() + THIRD_REPLY_WINDOW,
            "original_msg_id": event.message.id,
            "stabilize": True,
        }

@client.on(events.NewMessage(chats=THIRD_GROUP))
async def forward_reply_third(event):
    if not event.message.reply_to_msg_id:
        return
    fid = event.message.reply_to_msg_id
    text = _get_text(event.message)

    if is_fetch_message(text):
        asyncio.create_task(watch_fetch_then_resolve(fid))
        return

    info = forwarded_from_third.get(fid)
    if not info:
        return

    cleaned, _ = filter_links_and_usernames(remove_footer(text))
    if cleaned:
        await client.send_message(FIRST_GROUP, cleaned, reply_to=info["original_msg_id"])

# ================= API =================
async def api_command(request):
    data = await request.json()
    valid, _ = await validate_api_key_in_storage(data.get("api_key"))
    if not valid:
        return web.json_response({"error": "invalid_api_key"}, status=401)

    cmd = data.get("command")
    if not cmd or not cmd.startswith("2/"):
        return web.json_response({"error": "invalid_command"}, status=400)

    forwarded = await client.send_message(THIRD_GROUP, "/" + cmd[2:])
    fut = asyncio.get_running_loop().create_future()
    api_request_map[forwarded.id] = {"future": fut}
    forwarded_from_third[forwarded.id] = {"original_msg_id": None}

    try:
        res = await asyncio.wait_for(fut, timeout=API_REQUEST_TIMEOUT)
        return web.json_response({"success": True, "responses": res})
    except asyncio.TimeoutError:
        return web.json_response({"success": False, "error": "timeout"}, status=504)

# ================= WEB =================
async def start_web_server():
    app = web.Application()
    app.router.add_post("/api/command", api_command)
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    await asyncio.Event().wait()

async def start_telegram():
    await client.start()
    bot_status["running"] = True
    logger.info("Telegram started")

async def main():
    init_mongo()
    await asyncio.gather(start_web_server(), start_telegram())

if __name__ == "__main__":
    asyncio.run(main())
