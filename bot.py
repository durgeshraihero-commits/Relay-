#!/usr/bin/env python3
"""
bot.py — Telegram relay + HTTP API (single-file, ready for Render)

Features:
 - Uses a Telethon session file (default: relay_session.session) — no interactive login required.
 - MongoDB-backed API key storage (with safe fallback to a JSON file when Mongo is unavailable).
 - Admin endpoints: /api/create_key, /api/list_keys, /api/revoke_key
 - Public endpoints: /api/validate_key, /api/command
 - Health endpoint: /health and human status page at /
 - Reply-window tracking for third_group replies and optional stabilization delay
 - Filtering of links/usernames and footer-removal for replies
 - Robust error handling and logging (no raw tracebacks returned publicly)
 - Avoids crashing when Mongo index options conflict (skips creation if already present)

Environment variables used:
 - SESSION_FILE          (default: relay_session.session)
 - API_ID                (optional; Telethon app id, 0 works if session file already valid)
 - API_HASH              (optional; Telethon app hash)
 - FIRST_GROUP           (source group username or ID)
 - SECOND_GROUP          (destination group 1)
 - THIRD_GROUP           (destination group 2)
 - MASTER_API_SECRET     (admin secret for creating/listing/revoking keys)
 - MONGODB_URI           (optional; when not set fallback file storage used)
 - MONGODB_DBNAME        (default: tg_bot_db)
 - API_KEYS_FALLBACK_FILE (default: ./api_keys_fallback.json)
 - PORT                  (default: 10000)
 - THIRD_REPLY_WINDOW    (seconds; default 5)
 - REPLY_STABILIZE_DELAY (seconds; default 3)
 - FETCH_WAIT_TIME       (seconds; default 3)
 - API_REQUEST_TIMEOUT   (seconds; default computed from above)
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

# ---------------- Config ----------------
PORT = int(os.getenv("PORT", "10000"))

SESSION_FILE = os.getenv("SESSION_FILE", "relay_session.session")
TELETHON_API_ID = int(os.getenv("API_ID", "0"))
TELETHON_API_HASH = os.getenv("API_HASH", "")

FIRST_GROUP = os.getenv("FIRST_GROUP", "ethicalosinterr")
SECOND_GROUP = os.getenv("SECOND_GROUP", "ethicalosint")
THIRD_GROUP = os.getenv("THIRD_GROUP", "IntelXGroup")

MASTER_API_SECRET = os.getenv("MASTER_API_SECRET")  # required for admin endpoints

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")
API_KEYS_FALLBACK_FILE = os.getenv("API_KEYS_FALLBACK_FILE", "./api_keys_fallback.json")

THIRD_REPLY_WINDOW = int(os.getenv("THIRD_REPLY_WINDOW", "5"))
REPLY_STABILIZE_DELAY = int(os.getenv("REPLY_STABILIZE_DELAY", "3"))
FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))
API_REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", str(THIRD_REPLY_WINDOW + REPLY_STABILIZE_DELAY + FETCH_WAIT_TIME + 8)))

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("relay_api_bot")

# ---------------- MongoDB (safe init) ----------------
mongo_client = None
db = None
api_keys_col = None

def init_mongo():
    """
    Initialize MongoDB connection if MONGODB_URI provided.
    Safe behavior: if indexes already exist with different options, skip creation and continue.
    """
    global mongo_client, db, api_keys_col
    if not MONGODB_URI:
        logger.warning("MONGODB_URI not set — using fallback file storage for API keys.")
        mongo_client = None
        db = None
        api_keys_col = None
        return

    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()  # force immediate connection / failure
        db = mongo_client[MONGODB_DBNAME]
        api_keys_col = db["api_keys"]

        # Ensure unique index on key (attempt, but ignore if it already exists)
        try:
            api_keys_col.create_index([("key", 1)], unique=True)
            logger.info("MongoDB: ensured unique index on 'key'.")
        except Exception as e:
            logger.debug("Could not ensure unique index on 'key' (continuing): %s", e)

        # Check if 'expires_at_1' index exists — create only if missing
        try:
            existing = api_keys_col.index_information()
            if "expires_at_1" in existing:
                logger.info("MongoDB: 'expires_at' index already exists; skipping creation.")
            else:
                api_keys_col.create_index([("expires_at", 1)])
                logger.info("MongoDB: created index on 'expires_at'.")
        except Exception as e:
            logger.warning("MongoDB: could not create/check 'expires_at' index (continuing): %s", e)

        logger.info("MongoDB: api_keys collection ready.")
    except Exception as e:
        logger.exception("Could not connect to MongoDB — falling back to file storage: %s", e)
        mongo_client = None
        db = None
        api_keys_col = None

# ---------------- Fallback file storage ----------------
def load_fallback_keys():
    try:
        if os.path.exists(API_KEYS_FALLBACK_FILE):
            with open(API_KEYS_FALLBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        logger.exception("Failed reading fallback api keys file.")
    return {}

def save_fallback_keys(data):
    try:
        with open(API_KEYS_FALLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed saving fallback api keys file.")

# ---------------- Utilities ----------------
def _now_utc():
    return datetime.now(timezone.utc)

def _iso(dt):
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return dt

# ---------------- API key DB helpers ----------------
async def create_api_key_in_db(key: str, label: str = "", owner: str = None, duration_days: int = 30):
    doc = {
        "key": key,
        "label": label or "",
        "owner": owner or "",
        "created_at": _iso(_now_utc()),
        "expires_at": _iso(_now_utc() + timedelta(days=int(duration_days))),
        "revoked": False
    }
    if api_keys_col is not None:
        try:
            # run insert in executor to avoid blocking loop
            await asyncio.get_running_loop().run_in_executor(None, api_keys_col.insert_one, doc)
            return True, doc
        except Exception as e:
            logger.exception("Error inserting api key to Mongo: %s", e)
    # fallback to file
    data = load_fallback_keys()
    data[key] = doc
    save_fallback_keys(data)
    return True, doc

async def find_api_key_doc(key: str):
    if api_keys_col is not None:
        try:
            doc = await asyncio.get_running_loop().run_in_executor(None, api_keys_col.find_one, {"key": key})
            if doc:
                return doc
        except Exception as e:
            logger.exception("Mongo lookup error: %s", e)
    data = load_fallback_keys()
    return data.get(key)

async def list_api_keys_from_storage():
    if api_keys_col is not None:
        try:
            cursor = api_keys_col.find({})
            docs = await asyncio.get_running_loop().run_in_executor(None, lambda: list(cursor))
            out = []
            for d in docs:
                out.append({
                    "key": d.get("key"),
                    "label": d.get("label", ""),
                    "owner": d.get("owner", ""),
                    "created_at": d.get("created_at"),
                    "expires_at": d.get("expires_at"),
                    "revoked": bool(d.get("revoked", False))
                })
            return out
        except Exception as e:
            logger.exception("Mongo list error: %s", e)
    data = load_fallback_keys()
    out = []
    for k, d in data.items():
        out.append({
            "key": k,
            "label": d.get("label", ""),
            "owner": d.get("owner", ""),
            "created_at": d.get("created_at"),
            "expires_at": d.get("expires_at"),
            "revoked": bool(d.get("revoked", False))
        })
    return out

async def revoke_api_key_in_storage(key: str):
    if api_keys_col is not None:
        try:
            res = await asyncio.get_running_loop().run_in_executor(None, lambda: api_keys_col.find_one_and_update({"key": key}, {"$set": {"revoked": True}}))
            if res:
                return True
        except Exception as e:
            logger.exception("Mongo revoke error: %s", e)
    data = load_fallback_keys()
    if key in data:
        data[key]["revoked"] = True
        save_fallback_keys(data)
        return True
    return False

async def validate_api_key_in_storage(key: str):
    if not key:
        return False, "missing_key"
    doc = await find_api_key_doc(key)
    if not doc:
        return False, "not_found"
    try:
        if doc.get("revoked", False):
            return False, "revoked"
        expires_at = doc.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                # make timezone aware; stored value is in iso UTC
                if exp_dt.replace(tzinfo=timezone.utc) < _now_utc():
                    return False, "expired"
            except Exception:
                pass
        return True, doc
    except Exception as e:
        logger.exception("Error validating key: %s", e)
        return False, "internal_error"

# ---------------- Text cleaning helpers ----------------
def filter_links_and_usernames(text: str):
    if not text:
        return text, False
    original_text = text
    url_patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r't\.me/[^\s]+',
        r'[a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*'
    ]
    username_patterns = [r'@[\w]{2,32}']
    cleaned = text
    for p in (url_patterns + username_patterns):
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    # remove promotional lines
    lines = cleaned.splitlines()
    filtered_lines = []
    promotional = ['use these commands in:', 'join our group', 'visit our channel', '💬 use these commands', 'commands in:']
    for line in lines:
        l = line.strip()
        if not l:
            continue
        if any(k in l.lower() for k in promotional):
            continue
        filtered_lines.append(line)
    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    was_filtered = (original_text != cleaned)
    return cleaned, was_filtered

def remove_footer(text: str):
    if not text:
        return text
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "footer" in data:
            del data["footer"]
            return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        lines = text.splitlines()
        filtered = [L for L in lines if '"footer"' not in L and '@frappeash' not in L]
        return "\n".join(filtered)
    return text

def get_fetch_message(command: str):
    cmd_lower = command.lower()
    if 'vnum' in cmd_lower or 'vehicle' in cmd_lower:
        return "⏳ Fetching vehicle info… Please wait."
    if 'family' in cmd_lower:
        return "⏳ Fetching family info… Please wait."
    if 'aadhar' in cmd_lower or 'aadhaar' in cmd_lower:
        return "⏳ Fetching Aadhar info… Please wait."
    if 'pan' in cmd_lower:
        return "⏳ Fetching PAN info… Please wait."
    if 'voter' in cmd_lower:
        return "⏳ Fetching voter info… Please wait."
    if 'insta' in cmd_lower:
        return "⏳ Fetching Instagram info… Please wait."
    if 'bomber' in cmd_lower:
        return "⏳ Processing bomber request… Please wait."
    return "⏳ Fetching info… Please wait."

# ---------------- Runtime maps ----------------
message_map = {}           # source_msg_id -> forwarded_msg_id
reverse_map = {}
message_map_third = {}
reverse_map_third = {}
forwarded_from_third = {}  # forwarded_msg_id -> {count,max,deadline,original_msg_id,stabilize}
status_messages = {}       # original_msg_id -> {'status_msg':..., 'responses':[]}
api_request_map = {}       # forwarded_msg_id -> {future,responses,max,deadline,stabilize,original_api_req_id}
bot_status = {"running": False, "messages_forwarded": 0, "filtered_content": 0}

# ---------------- Telethon client ----------------
client = TelegramClient(SESSION_FILE, TELETHON_API_ID, TELETHON_API_HASH)

def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

# ---------------- Stabilizer ----------------
async def _stabilize_and_forward_third_reply(forwarded_msg_id: int, reply_msg_id: int):
    try:
        await asyncio.sleep(REPLY_STABILIZE_DELAY)
        info = forwarded_from_third.get(forwarded_msg_id)
        if not info:
            return
        if info['count'] >= info['max']:
            return
        latest = await client.get_messages(THIRD_GROUP, ids=reply_msg_id)
        if not latest:
            return
        latest_text = _get_text(latest)
        if not latest_text:
            return
        cleaned = remove_footer(latest_text)
        filtered_text, was_filtered = filter_links_and_usernames(cleaned)
        if was_filtered:
            bot_status["filtered_content"] += 1
        if not filtered_text.strip():
            return
        original_msg_id = info.get('original_msg_id')
        # delete status msg if exists
        if original_msg_id and original_msg_id in status_messages:
            try:
                await status_messages[original_msg_id]['status_msg'].delete()
                del status_messages[original_msg_id]
            except Exception:
                pass
        if original_msg_id:
            await client.send_message(FIRST_GROUP, filtered_text, reply_to=original_msg_id)
        forwarded_from_third[forwarded_msg_id]['count'] += 1
        bot_status["messages_forwarded"] += 1
        # satisfy any API waiter
        api_entry = api_request_map.get(forwarded_msg_id)
        if api_entry:
            api_entry['responses'].append(filtered_text)
            if len(api_entry['responses']) >= api_entry['max']:
                if not api_entry['future'].done():
                    api_entry['future'].set_result(api_entry['responses'])
    except Exception as e:
        logger.exception("Error in stabilize task: %s", e)

# ---------------- Telethon event handlers ----------------
@client.on(events.NewMessage(chats=FIRST_GROUP))
async def forward_command(event):
    message = event.message
    text = _get_text(message)
    if not text or not (text.startswith('/') or text.startswith('2/')):
        return
    target = SECOND_GROUP
    clean_command = text
    is_third = False
    if text.startswith('2/'):
        is_third = True
        target = THIRD_GROUP
        clean_command = '/' + text[2:]
    cmd_token = clean_command.split()[0].lower()
    if cmd_token == '/start':
        logger.info("Ignored /start from source group.")
        return
    try:
        status_msg = await client.send_message(FIRST_GROUP, get_fetch_message(clean_command), reply_to=message.id)
        status_messages[message.id] = {'status_msg': status_msg, 'responses': []}
        await asyncio.sleep(5)
        latest = await client.get_messages(FIRST_GROUP, ids=message.id)
        if not latest or _get_text(latest) != text:
            try:
                await status_msg.delete()
            except Exception:
                pass
            status_messages.pop(message.id, None)
            return
        forwarded = await client.send_message(target, clean_command)
        if is_third:
            message_map_third[message.id] = forwarded.id
            reverse_map_third[forwarded.id] = message.id
            allowed = 1
            stabilize = False
            if cmd_token in ['/vnum', '/bomber', '/familyinfo', '/insta']:
                allowed = 2
                stabilize = True
            forwarded_from_third[forwarded.id] = {
                'count': 0, 'max': allowed, 'deadline': time.time() + THIRD_REPLY_WINDOW,
                'original_msg_id': message.id, 'stabilize': stabilize
            }
        else:
            message_map[message.id] = forwarded.id
            reverse_map[forwarded.id] = message.id
        bot_status["messages_forwarded"] += 1
    except errors.rpcerrorlist.ChatWriteForbiddenError:
        logger.warning("Chat write forbidden when forwarding; informing source group.")
        try:
            await client.send_message(FIRST_GROUP, "⚠️ Bot cannot write to the destination group. Check permissions.", reply_to=message.id)
        except Exception:
            pass
    except Exception as e:
        logger.exception("Error forwarding command from source: %s", e)
        if message.id in status_messages:
            try:
                await status_messages[message.id]['status_msg'].delete()
                del status_messages[message.id]
            except Exception:
                pass

@client.on(events.NewMessage(chats=SECOND_GROUP))
async def forward_reply_second(event):
    message = event.message
    if not message.reply_to_msg_id:
        return
    original_id = reverse_map.get(message.reply_to_msg_id)
    if original_id:
        try:
            await asyncio.sleep(FETCH_WAIT_TIME)
            latest = await client.get_messages(SECOND_GROUP, ids=message.id)
            if not latest:
                return
            filtered, was_filtered = filter_links_and_usernames(_get_text(latest))
            if was_filtered:
                bot_status["filtered_content"] += 1
            if not filtered.strip():
                return
            if original_id in status_messages:
                try:
                    await status_messages[original_id]['status_msg'].delete()
                    del status_messages[original_id]
                except Exception:
                    pass
            await client.send_message(FIRST_GROUP, filtered, reply_to=original_id)
            bot_status["messages_forwarded"] += 1
            # API support: if reply corresponds to a forwarded API msg, satisfy future
            api_entry = api_request_map.get(message.reply_to_msg_id)
            if api_entry:
                api_entry['responses'].append(filtered)
                if len(api_entry['responses']) >= api_entry['max']:
                    if not api_entry['future'].done():
                        api_entry['future'].set_result(api_entry['responses'])
        except Exception as e:
            logger.exception("Error forwarding reply from second: %s", e)

@client.on(events.NewMessage(chats=THIRD_GROUP))
async def forward_reply_third(event):
    message = event.message
    if not message.reply_to_msg_id:
        return
    original_id = reverse_map_third.get(message.reply_to_msg_id)
    if original_id:
        reply_info = forwarded_from_third.get(message.reply_to_msg_id)
        if not reply_info:
            return
        now = time.time()
        if now > reply_info['deadline']:
            return
        if reply_info['count'] >= reply_info['max']:
            return
        try:
            if reply_info.get('stabilize'):
                asyncio.create_task(_stabilize_and_forward_third_reply(message.reply_to_msg_id, message.id))
            else:
                await asyncio.sleep(FETCH_WAIT_TIME)
                latest = await client.get_messages(THIRD_GROUP, ids=message.id)
                if not latest:
                    return
                cleaned = remove_footer(_get_text(latest))
                filtered, was_filtered = filter_links_and_usernames(cleaned)
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not filtered.strip():
                    return
                if reply_info['original_msg_id'] in status_messages:
                    try:
                        await status_messages[reply_info['original_msg_id']]['status_msg'].delete()
                        del status_messages[reply_info['original_msg_id']]
                    except Exception:
                        pass
                await client.send_message(FIRST_GROUP, filtered, reply_to=reply_info['original_msg_id'])
                forwarded_from_third[message.reply_to_msg_id]['count'] += 1
                bot_status["messages_forwarded"] += 1
                api_entry = api_request_map.get(message.reply_to_msg_id)
                if api_entry:
                    api_entry['responses'].append(filtered)
                    if len(api_entry['responses']) >= api_entry['max']:
                        if not api_entry['future'].done():
                            api_entry['future'].set_result(api_entry['responses'])
        except Exception as e:
            logger.exception("Error handling third_group reply: %s", e)
    else:
        # reply to an API-only forwarded message
        api_entry = api_request_map.get(message.reply_to_msg_id)
        if api_entry:
            try:
                if api_entry.get('stabilize'):
                    asyncio.create_task(_stabilize_and_forward_third_reply(message.reply_to_msg_id, message.id))
                else:
                    await asyncio.sleep(FETCH_WAIT_TIME)
                    latest = await client.get_messages(THIRD_GROUP, ids=message.id)
                    if not latest:
                        return
                    cleaned = remove_footer(_get_text(latest))
                    filtered, was_filtered = filter_links_and_usernames(cleaned)
                    if was_filtered:
                        bot_status["filtered_content"] += 1
                    if not filtered.strip():
                        return
                    api_entry['responses'].append(filtered)
                    if len(api_entry['responses']) >= api_entry['max']:
                        if not api_entry['future'].done():
                            api_entry['future'].set_result(api_entry['responses'])
            except Exception as e:
                logger.exception("Error handling third_group API reply: %s", e)

# ---------------- Telegram startup ----------------
async def start_telegram():
    await client.start()
    bot_status["running"] = True
    logger.info("Telegram session started — monitoring groups.")

# ---------------- HTTP helpers ----------------
async def json_request(request):
    try:
        return await request.json()
    except Exception:
        return None

# ---------------- HTTP API handlers ----------------
async def api_create_key(request):
    data = await json_request(request)
    if not data:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not MASTER_API_SECRET:
        return web.json_response({"error": "server_not_configured"}, status=500)
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    label = data.get("label", "")
    owner = data.get("owner", "")
    duration_days = int(data.get("duration_days", 30))
    token = uuid.uuid4().hex
    ok, doc = await create_api_key_in_db(token, label=label, owner=owner, duration_days=duration_days)
    if not ok:
        return web.json_response({"error": "db_error"}, status=500)
    return web.json_response({"api_key": token, "label": label, "duration_days": duration_days})

async def api_list_keys(request):
    data = await json_request(request)
    if not data:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not MASTER_API_SECRET or data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        docs = await list_api_keys_from_storage()
        return web.json_response({"keys": docs})
    except Exception as e:
        logger.exception("api_list_keys error: %s", e)
        return web.json_response({"error": "internal_error"}, status=500)

async def api_revoke_key(request):
    data = await json_request(request)
    if not data:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not MASTER_API_SECRET or data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    key = data.get("key")
    if not key:
        return web.json_response({"error": "missing_key"}, status=400)
    ok = await revoke_api_key_in_storage(key)
    return web.json_response({"revoked": bool(ok)})

async def api_validate_key(request):
    data = await json_request(request)
    if not data:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = data.get("api_key")
    if not key:
        return web.json_response({"valid": False, "reason": "missing_key"}, status=401)
    valid, doc_or_reason = await validate_api_key_in_storage(key)
    if not valid:
        return web.json_response({"valid": False, "reason": doc_or_reason}, status=401)
    doc = doc_or_reason
    expires_at = doc.get("expires_at")
    days_left = None
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            delta = exp_dt - _now_utc()
            days_left = max(0, int(delta.total_seconds() // 86400))
        except Exception:
            days_left = None
    return web.json_response({"valid": True, "expires_at": expires_at, "days_left": days_left, "revoked": bool(doc.get("revoked", False))})

async def api_command(request):
    """
    Client API: {"api_key":"...","command":"2/vnum MH12AB1234"}
    Only commands prefixed with '2/' are allowed (per your design).
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    api_key = data.get("api_key")
    command = data.get("command")
    if not api_key or not command:
        return web.json_response({"error": "missing_parameters"}, status=400)

    valid, doc_or_reason = await validate_api_key_in_storage(api_key)
    if not valid:
        return web.json_response({"error": "invalid_api_key", "reason": doc_or_reason}, status=401)

    if not command.startswith("2/"):
        return web.json_response({"error": "forbidden_command", "reason": "must_prefix_with_2_slash"}, status=400)

    clean_command = "/" + command[2:]
    # post status in FIRST_GROUP (best-effort)
    try:
        await client.send_message(FIRST_GROUP, f"[API] {get_fetch_message(clean_command)}")
    except Exception:
        pass

    try:
        forwarded = await client.send_message(THIRD_GROUP, clean_command)
    except errors.rpcerrorlist.ChatWriteForbiddenError:
        return web.json_response({"error": "telegram_send_failed", "detail": "chat_write_forbidden"}, status=403)
    except Exception as e:
        logger.exception("Failed sending command to third_group: %s", e)
        return web.json_response({"error": "telegram_send_failed", "detail": str(e)}, status=500)

    # determine stabilize / allowed replies for this command
    cmd_token = clean_command.split()[0].lower()
    allowed = 1
    stabilize = False
    if cmd_token in ['/vnum', '/bomber', '/familyinfo', '/insta']:
        allowed = 2
        stabilize = True

    fut = asyncio.get_running_loop().create_future()
    api_entry = {
        "future": fut,
        "responses": [],
        "max": allowed,
        "deadline": time.time() + THIRD_REPLY_WINDOW,
        "stabilize": stabilize,
        "original_api_req_id": uuid.uuid4().hex
    }
    api_request_map[forwarded.id] = api_entry

    forwarded_from_third[forwarded.id] = {
        'count': 0, 'max': allowed, 'deadline': time.time() + THIRD_REPLY_WINDOW,
        'original_msg_id': None, 'stabilize': stabilize
    }

    try:
        results = await asyncio.wait_for(fut, timeout=API_REQUEST_TIMEOUT)
        api_request_map.pop(forwarded.id, None)
        forwarded_from_third.pop(forwarded.id, None)
        return web.json_response({"success": True, "responses": results})
    except asyncio.TimeoutError:
        responses = api_entry['responses'][:]
        api_request_map.pop(forwarded.id, None)
        forwarded_from_third.pop(forwarded.id, None)
        if responses:
            return web.json_response({"success": True, "responses": responses, "note": "partial/timeout"})
        return web.json_response({"success": False, "error": "timeout_no_response"}, status=504)
    except Exception as e:
        logger.exception("Error while waiting for API response: %s", e)
        api_request_map.pop(forwarded.id, None)
        forwarded_from_third.pop(forwarded.id, None)
        return web.json_response({"success": False, "error": "internal_error", "detail": str(e)}, status=500)

# ---------------- Health & status ----------------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def status_page(request):
    active_windows = []
    now = time.time()
    for fid, info in forwarded_from_third.items():
        remaining = max(0, int(info['deadline'] - now))
        active_windows.append(f"forwarded_id={fid}, original_msg={info.get('original_msg_id')}, count={info['count']}/{info['max']}, remaining_s={remaining}, stabilize={info.get('stabilize', False)}")
    active_text = "\n".join(active_windows) if active_windows else "None"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Relay API Bot</title></head>
    <body>
      <h1>Telegram Relay API Bot</h1>
      <p>Status: {'Running' if bot_status['running'] else 'Stopped'}</p>
      <p>Messages Forwarded: {bot_status['messages_forwarded']}</p>
      <p>Content Filtered: {bot_status['filtered_content']}</p>
      <pre>Active reply-windows:\n{active_text}</pre>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

# ---------------- Web server startup ----------------
async def start_web_server():
    app = web.Application()
    app.router.add_post("/api/create_key", api_create_key)
    app.router.add_post("/api/list_keys", api_list_keys)
    app.router.add_post("/api/revoke_key", api_revoke_key)
    app.router.add_post("/api/validate_key", api_validate_key)
    app.router.add_post("/api/command", api_command)
    app.router.add_get("/health", health_check)
    app.router.add_get("/", status_page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Web server started on port %s", PORT)
    await asyncio.Event().wait()

# ---------------- Main ----------------
async def main():
    init_mongo()
    # run webserver and telegram loop concurrently
    await asyncio.gather(start_web_server(), start_telegram())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception:
        logger.exception("Fatal error on startup")
