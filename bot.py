#!/usr/bin/env python3
"""
bot.py — Telegram relay + HTTP API with MongoDB-backed API keys (session-mode)

Env:
  API_ID, API_HASH                -> required (strings)
  FIRST_GROUP, SECOND_GROUP, THIRD_GROUP  -> group usernames or numeric ids
  MASTER_API_SECRET               -> admin secret
  MONGODB_URI                     -> mongodb+srv://... (you provided earlier)
  MONGODB_DBNAME                  -> tg_bot_db (default)
  PORT                            -> web port (default 10000)
  THIRD_REPLY_WINDOW              -> seconds to accept replies (default 5)
  REPLY_STABILIZE_DELAY           -> seconds to wait before finalizing replies (default 3)
  FETCH_WAIT_TIME                 -> seconds to wait for edits/deletes before forwarding (default 3)
  API_REQUEST_TIMEOUT             -> overall HTTP timeout for api/command (optional)
  KEY_DEFAULT_DURATION_DAYS       -> default API key lifetime in days (default 30)

Requirements (recommended in requirements.txt):
  telethon==1.29.1
  aiohttp==3.9.4
  motor==3.7.1
  python-dateutil==2.8.2
"""
import os
import re
import time
import json
import uuid
import secrets
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from telethon import TelegramClient, events
from motor.motor_asyncio import AsyncIOMotorClient

# ---------------- config ----------------
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

FIRST_GROUP = os.getenv("FIRST_GROUP", "ethicalosinterr")
SECOND_GROUP = os.getenv("SECOND_GROUP", "ethicalosint")
THIRD_GROUP = os.getenv("THIRD_GROUP", "IntelXGroup")

MASTER_API_SECRET = os.getenv("MASTER_API_SECRET", "change_me")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")
MONGODB_COLLECTION_API_KEYS = os.getenv("MONGODB_COLLECTION_API_KEYS", "api_keys")

PORT = int(os.getenv("PORT", "10000"))
THIRD_REPLY_WINDOW = int(os.getenv("THIRD_REPLY_WINDOW", "5"))
REPLY_STABILIZE_DELAY = int(os.getenv("REPLY_STABILIZE_DELAY", "3"))
FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))

API_REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", str(THIRD_REPLY_WINDOW + REPLY_STABILIZE_DELAY + FETCH_WAIT_TIME + 5)))
KEY_DEFAULT_DURATION_DAYS = int(os.getenv("KEY_DEFAULT_DURATION_DAYS", "30"))

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("relay_api_bot")

# ---------------- validate required env ----------------
if not (API_ID and API_HASH):
    logger.error("API_ID and API_HASH must be set in environment. Exiting.")
    raise SystemExit(1)

# ---------------- Telethon client (session file) ----------------
client = TelegramClient("relay_session", int(API_ID), API_HASH)

# ---------------- MongoDB init ----------------
mongo_client = None
db = None
api_keys_col = None

async def init_db():
    global mongo_client, db, api_keys_col
    try:
        mongo_client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        # test connection
        await mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        api_keys_col = db[MONGODB_COLLECTION_API_KEYS]
        # create indexes
        try:
            await api_keys_col.create_index("expires_at", expireAfterSeconds=0)
            await api_keys_col.create_index("key", unique=True)
            logger.info("MongoDB: api_keys collection initialized (indexes ok).")
        except Exception as e:
            logger.warning("MongoDB index creation warning: %s", e)
    except Exception as e:
        logger.exception("Could not connect to MongoDB: %s", e)
        api_keys_col = None

# ---------------- runtime maps ----------------
api_request_map = {}       # forwarded_msg_id -> {future, responses(list), max, deadline, stabilize}
forwarded_from_third = {}  # forwarded_msg_id -> {count,max,deadline,original_msg_id,stabilize}
message_map = {}           # source_msg_id -> forwarded_msg_id (second)
reverse_map = {}           # forwarded_msg_id -> source_msg_id
message_map_third = {}     # source_msg_id -> forwarded_msg_id (third)
reverse_map_third = {}     # forwarded_msg_id -> source_msg_id
status_messages = {}       # original_msg_id -> {'status_msg': Message}
bot_status = {"running": False, "messages_forwarded": 0, "filtered_content": 0}

# ---------------- helpers: text cleaning ----------------
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

def remove_footer(text):
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

def filter_links_and_usernames(text):
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
    patterns = url_patterns + username_patterns
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    lines = cleaned.splitlines()
    filtered_lines = []
    promotional = ['use these commands in:', 'join our group', 'visit our channel', '💬 use these commands', 'commands in:']
    for line in lines:
        l = line.strip()
        if l and not any(k in l.lower() for k in promotional):
            filtered_lines.append(line)
    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    was_filtered = (original_text != cleaned)
    return cleaned, was_filtered

def clean_code_fences(text):
    if not text:
        return text
    return re.sub(r"^```+|```+$", "", text.strip(), flags=re.MULTILINE)

def extract_json_from_text(s):
    if not isinstance(s, str):
        return None, s
    cleaned = clean_code_fences(s)
    m = re.search(r"(\{[\s\S]*\})", cleaned)
    candidate = m.group(1) if m else cleaned
    try:
        obj = json.loads(candidate)
        return obj, cleaned
    except Exception:
        cand2 = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            obj = json.loads(cand2)
            return obj, cleaned
        except Exception:
            return None, cleaned

def format_for_telegram_and_api(raw_text, command_hint=None):
    if not raw_text:
        return "", {"text": ""}
    no_footer = remove_footer(raw_text)
    cleaned_links, was_filtered = filter_links_and_usernames(no_footer)
    cleaned = clean_code_fences(cleaned_links).strip()
    parsed, _ = extract_json_from_text(cleaned)
    if parsed is not None:
        header = f"✅ Result"
        if command_hint:
            header = f"✅ Result — {command_hint}"
        lines = []
        for key in ("success", "status", "message", "reg_no", "mobile_no", "name"):
            if key in parsed and key != "data":
                lines.append(f"- **{key.capitalize()}**: {parsed.get(key)}")
        if "data" in parsed and isinstance(parsed["data"], dict):
            lines.append("")
            lines.append("**Details:**")
            for k, v in parsed["data"].items():
                lines.append(f"- {k}: {v}")
        else:
            lines.append("")
            lines.append(json.dumps(parsed, indent=2, ensure_ascii=False))
        telegram_text = header + "\n\n" + "\n".join(lines)
        return telegram_text, {"json": parsed}
    else:
        header = f"✅ Result"
        if command_hint:
            header = f"✅ Result — {command_hint}"
        cleaned_lines = cleaned.splitlines()
        if len(cleaned_lines) > 200:
            cleaned = "\n".join(cleaned_lines[:200]) + "\n... (truncated)"
        telegram_text = header + "\n\n" + cleaned
        return telegram_text, {"text": cleaned}

# ---------------- Mongo-backed API keys ----------------
def _now_utc():
    return datetime.now(timezone.utc)

def _future_utc(days=0):
    return _now_utc() + timedelta(days=days)

async def create_api_key(label=None, days=None, owner=None):
    days = int(days) if days is not None else KEY_DEFAULT_DURATION_DAYS
    key = secrets.token_hex(16)
    doc = {
        "key": key,
        "label": label or "",
        "owner": owner or "",
        "created_at": _now_utc(),
        "expires_at": _future_utc(days=days),
        "revoked": False
    }
    if api_keys_col is not None:
        await api_keys_col.insert_one(doc)
    else:
        # fallback persistence (file) — best-effort
        logger.warning("create_api_key: Mongo not available — using fallback file.")
        try:
            with open("api_keys_fallback.json", "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            local = {}
        local[key] = {"label": label or "", "owner": owner or "", "created_at": int(time.time()), "expires_at": int(time.time()) + days*86400, "revoked": False}
        with open("api_keys_fallback.json", "w", encoding="utf-8") as f:
            json.dump(local, f, indent=2)
    return key

async def validate_api_key(key):
    if not key:
        return False, "missing_key"
    if api_keys_col is not None:
        doc = await api_keys_col.find_one({"key": key})
        if not doc:
            return False, "not_found"
        if doc.get("revoked", False):
            return False, "revoked"
        expires = doc.get("expires_at")
        if expires and isinstance(expires, datetime):
            if expires < _now_utc():
                return False, "expired"
        return True, doc
    else:
        try:
            with open("api_keys_fallback.json", "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            return False, "not_found"
        ent = local.get(key)
        if not ent:
            return False, "not_found"
        if ent.get("revoked"):
            return False, "revoked"
        if ent.get("expires_at") and int(ent.get("expires_at")) < int(time.time()):
            return False, "expired"
        return True, ent

async def revoke_api_key(key):
    if api_keys_col is not None:
        res = await api_keys_col.update_one({"key": key}, {"$set": {"revoked": True}})
        return res.matched_count > 0
    else:
        try:
            with open("api_keys_fallback.json", "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            return False
        if key in local:
            local[key]["revoked"] = True
            with open("api_keys_fallback.json", "w", encoding="utf-8") as f:
                json.dump(local, f, indent=2)
            return True
        return False

async def list_api_keys():
    out = []
    if api_keys_col is not None:
        cursor = api_keys_col.find({}, {"_id": 0}).sort("created_at", -1)
        async for doc in cursor:
            d = dict(doc)
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
            if isinstance(d.get("expires_at"), datetime):
                d["expires_at"] = d["expires_at"].isoformat()
            out.append(d)
    else:
        try:
            with open("api_keys_fallback.json", "r", encoding="utf-8") as f:
                local = json.load(f)
            for k, v in local.items():
                out.append({"key": k, **v})
        except Exception:
            out = []
    return out

# ---------------- stabilization helper ----------------
async def _stabilize_and_forward_third_reply(forwarded_msg_id: int, reply_msg_id: int):
    try:
        await asyncio.sleep(REPLY_STABILIZE_DELAY)
        entry = forwarded_from_third.get(forwarded_msg_id)
        if not entry:
            return
        if entry["count"] >= entry["max"]:
            return
        latest_reply = await client.get_messages(THIRD_GROUP, ids=reply_msg_id)
        if not latest_reply:
            return
        latest_text = _get_text(latest_reply)
        if not latest_text:
            return
        telegram_text, structured = format_for_telegram_and_api(latest_text, command_hint=None)
        if entry.get("original_msg_id") and entry["original_msg_id"] in status_messages:
            try:
                await status_messages[entry["original_msg_id"]]["status_msg"].delete()
                del status_messages[entry["original_msg_id"]]
            except Exception:
                pass
        if entry.get("original_msg_id"):
            await client.send_message(FIRST_GROUP, telegram_text, reply_to=entry["original_msg_id"])
        entry["count"] += 1
        bot_status["messages_forwarded"] += 1
        api_entry = api_request_map.get(forwarded_msg_id)
        if api_entry:
            api_entry["responses"].append(structured)
            if len(api_entry["responses"]) >= api_entry["max"]:
                if not api_entry["future"].done():
                    api_entry["future"].set_result(api_entry["responses"])
    except Exception as e:
        logger.exception("Error in stabilize task: %s", e)

# ---------------- Telegram handlers ----------------
@client.on(events.NewMessage(chats=FIRST_GROUP))
async def forward_command(event):
    message = event.message
    text = _get_text(message)
    if not text or not (text.startswith("/") or text.startswith("2/")):
        return
    target = SECOND_GROUP
    clean_command = text
    is_third = False
    if text.startswith("2/"):
        is_third = True
        target = THIRD_GROUP
        clean_command = "/" + text[2:]
    cmd_token = clean_command.split()[0].lower()
    if cmd_token == "/start":
        logger.info("Ignored /start from source group.")
        return
    try:
        status_msg = await client.send_message(FIRST_GROUP, get_fetch_message(clean_command), reply_to=message.id)
        status_messages[message.id] = {"status_msg": status_msg, "responses": []}
        await asyncio.sleep(5)
        latest = await client.get_messages(FIRST_GROUP, ids=message.id)
        if not latest or _get_text(latest) != text:
            try:
                await status_msg.delete()
                del status_messages[message.id]
            except Exception:
                pass
            return
        forwarded = await client.send_message(target, clean_command)
        if is_third:
            message_map_third[message.id] = forwarded.id
            reverse_map_third[forwarded.id] = message.id
            allowed = 1
            stabilize = False
            if cmd_token in ["/vnum", "/bomber", "/familyinfo", "/insta"]:
                allowed = 2
                stabilize = True
            forwarded_from_third[forwarded.id] = {
                "count": 0,
                "max": allowed,
                "deadline": time.time() + THIRD_REPLY_WINDOW,
                "original_msg_id": message.id,
                "stabilize": stabilize
            }
            logger.info("Tracking third_group forwarded id %s (max=%s, stabilize=%s)", forwarded.id, allowed, stabilize)
        else:
            message_map[message.id] = forwarded.id
            reverse_map[forwarded.id] = message.id
        bot_status["messages_forwarded"] += 1
        logger.info("Forwarded command to %s: %s", target, clean_command)
    except Exception as e:
        logger.exception("Error forwarding command: %s", e)
        if message.id in status_messages:
            try:
                await status_messages[message.id]["status_msg"].delete()
                del status_messages[message.id]
            except:
                pass

def get_fetch_message(command):
    cmd_lower = command.lower()
    if "vnum" in cmd_lower or "vehicle" in cmd_lower:
        return "⏳ Fetching vehicle info… Please wait."
    if "family" in cmd_lower:
        return "⏳ Fetching family info… Please wait."
    if "aadhar" in cmd_lower or "aadhaar" in cmd_lower:
        return "⏳ Fetching Aadhar info… Please wait."
    if "pan" in cmd_lower:
        return "⏳ Fetching PAN info… Please wait."
    if "voter" in cmd_lower:
        return "⏳ Fetching voter info… Please wait."
    if "insta" in cmd_lower:
        return "⏳ Fetching Instagram info… Please wait."
    if "bomber" in cmd_lower:
        return "⏳ Processing bomber request… Please wait."
    return "⏳ Fetching info… Please wait."

@client.on(events.NewMessage(chats=SECOND_GROUP))
async def forward_reply_second(event):
    message = event.message
    text = _get_text(message)
    if message.reply_to_msg_id:
        original_id = reverse_map.get(message.reply_to_msg_id)
        if original_id:
            try:
                await asyncio.sleep(FETCH_WAIT_TIME)
                latest = await client.get_messages(SECOND_GROUP, ids=message.id)
                if not latest:
                    return
                latest_text = _get_text(latest)
                cleaned_text, was_filtered = filter_links_and_usernames(remove_footer(latest_text))
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not cleaned_text.strip():
                    return
                telegram_text, structured = format_for_telegram_and_api(cleaned_text, command_hint=None)
                if original_id in status_messages:
                    try:
                        await status_messages[original_id]["status_msg"].delete()
                        del status_messages[original_id]
                    except:
                        pass
                await client.send_message(FIRST_GROUP, telegram_text, reply_to=original_id)
                bot_status["messages_forwarded"] += 1
                logger.info("Forwarded reply from second_group -> first_group")
                api_entry = api_request_map.get(message.reply_to_msg_id)
                if api_entry:
                    api_entry["responses"].append(structured)
                    if len(api_entry["responses"]) >= api_entry["max"]:
                        if not api_entry["future"].done():
                            api_entry["future"].set_result(api_entry["responses"])
                return
            except Exception as e:
                logger.exception("Error forwarding from second: %s", e)
    if message.reply_to_msg_id:
        api_entry = api_request_map.get(message.reply_to_msg_id)
        if api_entry:
            try:
                await asyncio.sleep(FETCH_WAIT_TIME)
                latest = await client.get_messages(SECOND_GROUP, ids=message.id)
                if not latest:
                    return
                latest_text = _get_text(latest)
                cleaned_text, was_filtered = filter_links_and_usernames(remove_footer(latest_text))
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not cleaned_text.strip():
                    return
                _, structured = format_for_telegram_and_api(cleaned_text, command_hint=None)
                api_entry["responses"].append(structured)
                if len(api_entry["responses"]) >= api_entry["max"]:
                    if not api_entry["future"].done():
                        api_entry["future"].set_result(api_entry["responses"])
            except Exception as e:
                logger.exception("Error in API-related second_group handler: %s", e)

@client.on(events.NewMessage(chats=THIRD_GROUP))
async def forward_reply_third(event):
    message = event.message
    text = _get_text(message)
    if not message.reply_to_msg_id:
        return
    original_id = reverse_map_third.get(message.reply_to_msg_id)
    if original_id:
        reply_info = forwarded_from_third.get(message.reply_to_msg_id)
        if not reply_info:
            return
        now = time.time()
        if now > reply_info["deadline"]:
            return
        if reply_info["count"] >= reply_info["max"]:
            return
        try:
            if reply_info.get("stabilize"):
                asyncio.create_task(_stabilize_and_forward_third_reply(message.reply_to_msg_id, message.id))
            else:
                await asyncio.sleep(FETCH_WAIT_TIME)
                latest = await client.get_messages(THIRD_GROUP, ids=message.id)
                if not latest:
                    return
                latest_text = _get_text(latest)
                cleaned_text, was_filtered = filter_links_and_usernames(remove_footer(latest_text))
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not cleaned_text.strip():
                    return
                telegram_text, structured = format_for_telegram_and_api(cleaned_text, command_hint=None)
                if reply_info["original_msg_id"] in status_messages:
                    try:
                        await status_messages[reply_info["original_msg_id"]]["status_msg"].delete()
                        del status_messages[reply_info["original_msg_id"]]
                    except:
                        pass
                await client.send_message(FIRST_GROUP, telegram_text, reply_to=reply_info["original_msg_id"])
                forwarded_from_third[message.reply_to_msg_id]["count"] += 1
                bot_status["messages_forwarded"] += 1
                api_entry = api_request_map.get(message.reply_to_msg_id)
                if api_entry:
                    api_entry["responses"].append(structured)
                    if len(api_entry["responses"]) >= api_entry["max"]:
                        if not api_entry["future"].done():
                            api_entry["future"].set_result(api_entry["responses"])
        except Exception as e:
            logger.exception("Error handling third_group reply: %s", e)
    else:
        api_entry = api_request_map.get(message.reply_to_msg_id)
        if api_entry:
            try:
                if api_entry.get("stabilize"):
                    asyncio.create_task(_stabilize_and_forward_third_reply(message.reply_to_msg_id, message.id))
                else:
                    await asyncio.sleep(FETCH_WAIT_TIME)
                    latest = await client.get_messages(THIRD_GROUP, ids=message.id)
                    if not latest:
                        return
                    latest_text = _get_text(latest)
                    cleaned_text, was_filtered = filter_links_and_usernames(remove_footer(latest_text))
                    if was_filtered:
                        bot_status["filtered_content"] += 1
                    if not cleaned_text.strip():
                        return
                    _, structured = format_for_telegram_and_api(cleaned_text, command_hint=None)
                    api_entry["responses"].append(structured)
                    if len(api_entry["responses"]) >= api_entry["max"]:
                        if not api_entry["future"].done():
                            api_entry["future"].set_result(api_entry["responses"])
            except Exception as e:
                logger.exception("Error handling third_group API reply: %s", e)

# ---------------- telegram startup ----------------
async def start_telegram():
    await client.start()  # uses existing session file
    bot_status["running"] = True
    logger.info("Started Telethon using session file 'relay_session.session' — monitoring groups.")
    await client.run_until_disconnected()

# ---------------- HTTP endpoints ----------------
async def api_create_key(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    label = data.get("label")
    duration = data.get("duration_days")
    owner = data.get("owner")
    try:
        if duration is not None:
            duration = int(duration)
            if duration <= 0:
                raise ValueError()
            if duration > 365:
                duration = 365
    except Exception:
        return web.json_response({"error": "invalid_duration"}, status=400)
    try:
        key = await create_api_key(label=label, days=duration, owner=owner)
    except Exception as e:
        logger.exception("api_create_key: DB error")
        return web.json_response({"error": "db_unavailable", "detail": str(e)}, status=503)
    return web.json_response({"api_key": key, "label": label, "duration_days": duration or KEY_DEFAULT_DURATION_DAYS})

async def api_revoke_key(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    key = data.get("key")
    if not key:
        return web.json_response({"error": "missing_key"}, status=400)
    try:
        ok = await revoke_api_key(key)
    except Exception as e:
        logger.exception("api_revoke_key: DB error")
        return web.json_response({"error": "db_unavailable", "detail": str(e)}, status=503)
    return web.json_response({"revoked": ok})

async def api_list_keys(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        docs = await list_api_keys()
    except Exception as e:
        logger.exception("api_list_keys: DB error")
        return web.json_response({"error": "db_unavailable", "detail": str(e)}, status=503)
    return web.json_response({"keys": docs})

async def api_command(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    api_key = data.get("api_key")
    command = data.get("command")
    if not api_key or not command:
        return web.json_response({"error": "missing_parameters"}, status=400)
    valid, info = await validate_api_key(api_key)
    if not valid:
        return web.json_response({"error": "invalid_api_key", "reason": info}, status=401)
    is_third = False
    clean_command = command
    target = SECOND_GROUP
    if command.startswith("2/"):
        is_third = True
        target = THIRD_GROUP
        clean_command = "/" + command[2:]
    if clean_command.split()[0].lower() == "/start":
        return web.json_response({"error": "forbidden_command"}, status=400)
    try:
        await client.send_message(FIRST_GROUP, f"[API] {get_fetch_message(clean_command)}")
    except Exception:
        logger.debug("Could not post API status message in first_group (continuing)")
    try:
        forwarded = await client.send_message(target, clean_command)
    except Exception as e:
        logger.exception("Failed sending command to target group: %s", e)
        return web.json_response({"error": "telegram_send_failed", "detail": str(e)}, status=500)
    cmd_token = clean_command.split()[0].lower()
    allowed = 1
    stabilize = False
    if cmd_token in ["/vnum", "/bomber", "/familyinfo", "/insta"]:
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
    if is_third:
        forwarded_from_third[forwarded.id] = {
            "count": 0, "max": allowed, "deadline": time.time() + THIRD_REPLY_WINDOW,
            "original_msg_id": None, "stabilize": stabilize
        }
    try:
        results = await asyncio.wait_for(fut, timeout=API_REQUEST_TIMEOUT)
        api_request_map.pop(forwarded.id, None)
        forwarded_from_third.pop(forwarded.id, None)
        return web.json_response({"success": True, "responses": results})
    except asyncio.TimeoutError:
        responses = api_entry["responses"][:]
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

# ---------------- health / status ----------------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def status(request):
    active_windows = []
    now = time.time()
    for fid, info in forwarded_from_third.items():
        remaining = max(0, int(info["deadline"] - now))
        active_windows.append(f"forwarded_id={fid}, original_msg={info.get('original_msg_id')}, count={info['count']}/{info['max']}, remaining_s={remaining}, stabilize={info.get('stabilize', False)}")
    active_text = "\n".join(active_windows) if active_windows else "None"
    html = f"""
    <!DOCTYPE html><html><head><title>Relay API Bot</title></head><body>
    <h1>Telegram Relay API Bot (user session)</h1>
    <p>Status: {'Running' if bot_status['running'] else 'Stopped'}</p>
    <p>Messages Forwarded: {bot_status['messages_forwarded']}</p>
    <p>Content Filtered: {bot_status['filtered_content']}</p>
    <pre>Active reply-windows:\n{active_text}</pre>
    </body></html>
    """
    return web.Response(text=html, content_type="text/html")

# ---------------- start web server ----------------
async def start_web_server():
    app = web.Application()
    app.router.add_post("/api/create_key", api_create_key)
    app.router.add_post("/api/revoke_key", api_revoke_key)
    app.router.add_post("/api/list_keys", api_list_keys)
    app.router.add_post("/api/command", api_command)
    app.router.add_get("/health", health_check)
    app.router.add_get("/", status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Web server started on port %s", PORT)
    await asyncio.Event().wait()

# ---------------- main ----------------
async def main():
    await init_db()
    # background: expire keys hourly (mark revoked)
    async def expire_task():
        while True:
            try:
                if api_keys_col is not None:
                    await api_keys_col.update_many({"expires_at": {"$lt": _now_utc()}, "revoked": False}, {"$set": {"revoked": True}})
            except Exception:
                logger.debug("expire_task: error (continuing)")
            await asyncio.sleep(3600)
    asyncio.create_task(expire_task())
    await asyncio.gather(start_web_server(), start_telegram())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Fatal error: %s", e)
