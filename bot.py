
#!/usr/bin/env python3
"""
FINAL bot.py — Telegram Relay + HTTP API

✔ FIRST / SECOND / THIRD group relay
✔ MongoDB + fallback JSON
✔ Full Admin APIs
✔ Stabilized replies
✔ Fetch-placeholder watch & edit logic
"""

import os
import re
import json
import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiohttp import web
from telethon import TelegramClient, events, errors
from pymongo import MongoClient

# ================= CONFIG =================
PORT = int(os.getenv("PORT", "10000"))

SESSION_FILE = os.getenv("SESSION_FILE", "relay_session.session")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

FIRST_GROUP = os.getenv("FIRST_GROUP", "ethicalosinterr")
SECOND_GROUP = os.getenv("SECOND_GROUP", "ethicalosint")
THIRD_GROUP = os.getenv("THIRD_GROUP", "IntelXGroup")

MASTER_API_SECRET = os.getenv("MASTER_API_SECRET")

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")
API_KEYS_FALLBACK_FILE = os.getenv("API_KEYS_FALLBACK_FILE", "./api_keys.json")

THIRD_REPLY_WINDOW = int(os.getenv("THIRD_REPLY_WINDOW", "5"))
REPLY_STABILIZE_DELAY = int(os.getenv("REPLY_STABILIZE_DELAY", "3"))

FETCH_EDIT_WATCH_TIME = int(os.getenv("FETCH_EDIT_WATCH_TIME", "15"))
FETCH_PHRASE = "⏳ Fetching"

API_REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", "30"))

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)
logger = logging.getLogger("relay_bot")

# ================= MONGODB =================
mongo_client = None
db = None
api_keys_col = None

def init_mongo():
    global mongo_client, db, api_keys_col
    if not MONGODB_URI:
        logger.warning("MongoDB not configured, using fallback file")
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
        logger.info("MongoDB connected")
    except Exception as e:
        logger.exception("MongoDB failed: %s", e)

# ================= FALLBACK =================
def load_keys():
    try:
        if os.path.exists(API_KEYS_FALLBACK_FILE):
            with open(API_KEYS_FALLBACK_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_keys(data):
    try:
        with open(API_KEYS_FALLBACK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# ================= UTILITIES =================
def now_utc():
    return datetime.now(timezone.utc)

def is_fetch_message(text: str) -> bool:
    return bool(text) and FETCH_PHRASE.lower() in text.lower()

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    return text.strip()

def remove_footer(text: str) -> str:
    return "\n".join(
        l for l in text.splitlines()
        if "footer" not in l.lower() and "@frappeash" not in l
    )

def get_fetch_message(cmd: str) -> str:
    return "⏳ Fetching info… Please wait."

def _get_text(msg):
    return msg.text if msg and msg.text else ""

# ================= API KEYS =================
async def create_api_key(label="", days=30):
    key = uuid.uuid4().hex
    doc = {
        "key": key,
        "label": label,
        "created_at": now_utc().isoformat(),
        "expires_at": (now_utc() + timedelta(days=days)).isoformat(),
        "revoked": False
    }
    if api_keys_col:
        await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.insert_one, doc
        )
    else:
        data = load_keys()
        data[key] = doc
        save_keys(data)
    return key

async def validate_api_key(key):
    if not key:
        return False
    if api_keys_col:
        doc = await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.find_one({"key": key})
        )
    else:
        doc = load_keys().get(key)

    if not doc or doc.get("revoked"):
        return False
    try:
        if datetime.fromisoformat(doc["expires_at"]) < now_utc():
            return False
    except Exception:
        pass
    return True

# ================= RUNTIME MAPS =================
forwarded_from_third = {}
api_request_map = {}

# ================= TELEGRAM =================
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

# ================= FETCH WATCHER =================
async def watch_fetch_then_resolve(forwarded_id: int):
    start = time.time()
    api_entry = api_request_map.get(forwarded_id)
    info = forwarded_from_third.get(forwarded_id)
    last_seen = None

    while time.time() - start < FETCH_EDIT_WATCH_TIME:
        await asyncio.sleep(1)

        try:
            msg = await client.get_messages(THIRD_GROUP, ids=forwarded_id)
            if msg and msg.text and not is_fetch_message(msg.text):
                text = clean_text(remove_footer(msg.text))
                if text:
                    if info and info.get("original_msg_id"):
                        await client.send_message(
                            FIRST_GROUP, text,
                            reply_to=info["original_msg_id"]
                        )
                    if api_entry and not api_entry["future"].done():
                        api_entry["future"].set_result([text])
                return
        except Exception:
            pass

        async for m in client.iter_messages(
            THIRD_GROUP, reply_to=forwarded_id, limit=3
        ):
            if last_seen == m.id:
                continue
            last_seen = m.id
            t = _get_text(m)
            if t and not is_fetch_message(t):
                text = clean_text(remove_footer(t))
                if text:
                    if info and info.get("original_msg_id"):
                        await client.send_message(
                            FIRST_GROUP, text,
                            reply_to=info["original_msg_id"]
                        )
                    if api_entry and not api_entry["future"].done():
                        api_entry["future"].set_result([text])
                return

# ================= TELEGRAM HANDLERS =================
@client.on(events.NewMessage(chats=FIRST_GROUP))
async def forward_command(event):
    text = _get_text(event.message)
    if not text or not (text.startswith("/") or text.startswith("2/")):
        return

    target = THIRD_GROUP if text.startswith("2/") else SECOND_GROUP
    clean = "/" + text[2:] if text.startswith("2/") else text

    await client.send_message(
        FIRST_GROUP,
        get_fetch_message(clean),
        reply_to=event.message.id
    )

    forwarded = await client.send_message(target, clean)

    if target == THIRD_GROUP:
        forwarded_from_third[forwarded.id] = {
            "original_msg_id": event.message.id
        }

@client.on(events.NewMessage(chats=THIRD_GROUP))
async def handle_third_reply(event):
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

    final = clean_text(remove_footer(text))
    if final:
        await client.send_message(
            FIRST_GROUP,
            final,
            reply_to=info["original_msg_id"]
        )

# ================= HTTP API =================
async def api_create_key(request):
    data = await request.json()
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    key = await create_api_key(data.get("label", ""))
    return web.json_response({"api_key": key})

async def api_list_keys(request):
    if api_keys_col:
        keys = list(api_keys_col.find({}, {"_id": 0}))
    else:
        keys = list(load_keys().values())
    return web.json_response({"keys": keys})

async def api_validate_key(request):
    data = await request.json()
    valid = await validate_api_key(data.get("api_key"))
    return web.json_response({"valid": valid})

async def api_command(request):
    data = await request.json()
    if not await validate_api_key(data.get("api_key")):
        return web.json_response({"error": "invalid_api_key"}, status=401)

    cmd = data.get("command")
    if not cmd or not cmd.startswith("2/"):
        return web.json_response({"error": "invalid_command"}, status=400)

    forwarded = await client.send_message(
        THIRD_GROUP, "/" + cmd[2:]
    )

    fut = asyncio.get_running_loop().create_future()
    api_request_map[forwarded.id] = {"future": fut}
    forwarded_from_third[forwarded.id] = {"original_msg_id": None}

    try:
        res = await asyncio.wait_for(fut, timeout=API_REQUEST_TIMEOUT)
        return web.json_response({"success": True, "responses": res})
    except asyncio.TimeoutError:
        return web.json_response({"error": "timeout"}, status=504)

async def health(request):
    return web.Response(text="OK")

async def status(request):
    return web.json_response({
        "running": True,
        "active_requests": len(api_request_map)
    })

# ================= START =================
async def start_web():
    app = web.Application()
    app.router.add_get("/", status)
    app.router.add_get("/health", health)
    app.router.add_post("/api/create_key", api_create_key)
    app.router.add_post("/api/list_keys", api_list_keys)
    app.router.add_post("/api/validate_key", api_validate_key)
    app.router.add_post("/api/command", api_command)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Web server started")
    await asyncio.Event().wait()

async def start_tg():
    await client.start()
    logger.info("Telegram started")
    await client.run_until_disconnected()

async def main():
    init_mongo()
    await asyncio.gather(start_web(), start_tg())

if __name__ == "__main__":
    asyncio.run(main())
