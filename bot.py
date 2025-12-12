#!/usr/bin/env python3
"""
bot.py — Telegram relay + HTTP API in a single file.
(Full corrected version — ready for Render; bug fixes applied)
"""
import os
import time
import json
import uuid
import re
import asyncio
import logging
from aiohttp import web
from telethon import TelegramClient, events

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")  # REQUIRED (recommended)
FIRST_GROUP = os.getenv("FIRST_GROUP", "ethicalosinterr")
SECOND_GROUP = os.getenv("SECOND_GROUP", "ethicalosint")
THIRD_GROUP = os.getenv("THIRD_GROUP", "IntelXGroup")

MASTER_API_SECRET = os.getenv("MASTER_API_SECRET")  # required to create keys
API_KEYS_FILE = os.getenv("API_KEYS_FILE", "./api_keys.json")

PORT = int(os.getenv("PORT", "10000"))
THIRD_REPLY_WINDOW = int(os.getenv("THIRD_REPLY_WINDOW", "5"))
REPLY_STABILIZE_DELAY = int(os.getenv("REPLY_STABILIZE_DELAY", "3"))
FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))

API_REQUEST_TIMEOUT = int(os.getenv("API_REQUEST_TIMEOUT", str(THIRD_REPLY_WINDOW + REPLY_STABILIZE_DELAY + FETCH_WAIT_TIME + 5)))

# CORRECTED: read env names (previously you had literal numbers/strings)
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("relay_api_bot")

# ---------- Telethon client ----------
if BOT_TOKEN:
    _api_id = int(API_ID) if API_ID else 0
    _api_hash = API_HASH if API_HASH else None
    client = TelegramClient("relay_bot_session", _api_id, _api_hash)
else:
    if not (API_ID and API_HASH and PHONE):
        logger.error("Either BOT_TOKEN or API_ID+API_HASH+PHONE must be provided. Exiting.")
        raise SystemExit(1)
    client = TelegramClient("relay_session", int(API_ID), API_HASH)

# ---------- In-memory maps ----------
message_map = {}
reverse_map = {}
message_map_third = {}
reverse_map_third = {}
forwarded_from_third = {}
status_messages = {}
bot_status = {"running": False, "messages_forwarded": 0, "filtered_content": 0}
api_request_map = {}

# ---------- API keys persistence ----------
def load_api_keys():
    try:
        with open(API_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_api_keys(keys):
    try:
        with open(API_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
    except Exception as e:
        logger.warning("Could not save API keys: %s", e)

api_keys = load_api_keys()

def generate_api_key(label=None):
    token = uuid.uuid4().hex
    api_keys[token] = {"label": label or "", "created_at": int(time.time())}
    save_api_keys(api_keys)
    return token

def validate_api_key(token):
    return token in api_keys

# ---------- Helpers ----------
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

def get_fetch_message(command):
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
    return cleaned, (original_text != cleaned)

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

# ---------- Stabilize helper ----------
async def _stabilize_and_forward_third_reply(forwarded_msg_id: int, reply_msg_id: int):
    try:
        await asyncio.sleep(REPLY_STABILIZE_DELAY)
        reply_info = forwarded_from_third.get(forwarded_msg_id)
        if not reply_info:
            return
        if reply_info['count'] >= reply_info['max']:
            return
        latest_reply = await client.get_messages(THIRD_GROUP, ids=reply_msg_id)
        if not latest_reply:
            return
        latest_text = _get_text(latest_reply)
        if not latest_text:
            return
        cleaned = remove_footer(latest_text)
        filtered_text, was_filtered = filter_links_and_usernames(cleaned)
        if was_filtered:
            bot_status["filtered_content"] += 1
        if not filtered_text.strip():
            return

        original_msg_id = reply_info.get('original_msg_id')
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

        api_entry = api_request_map.get(forwarded_msg_id)
        if api_entry:
            api_entry['responses'].append(filtered_text)
            if len(api_entry['responses']) >= api_entry['max']:
                if not api_entry['future'].done():
                    api_entry['future'].set_result(api_entry['responses'])
    except Exception as e:
        logger.exception("Error in stabilize task: %s", e)

# ---------- Telegram event handlers ----------
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
                del status_messages[message.id]
            except:
                pass
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
                await status_messages[message.id]['status_msg'].delete()
                del status_messages[message.id]
            except:
                pass

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
                filtered, was_filtered = filter_links_and_usernames(_get_text(latest))
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not filtered.strip():
                    return
                if original_id in status_messages:
                    try:
                        await status_messages[original_id]['status_msg'].delete()
                        del status_messages[original_id]
                    except:
                        pass
                await client.send_message(FIRST_GROUP, filtered, reply_to=original_id)
                bot_status["messages_forwarded"] += 1
                logger.info("Forwarded reply from second_group -> first_group")
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
                filtered, was_filtered = filter_links_and_usernames(_get_text(latest))
                if was_filtered:
                    bot_status["filtered_content"] += 1
                if not filtered.strip():
                    return
                api_entry['responses'].append(filtered)
                if len(api_entry['responses']) >= api_entry['max']:
                    if not api_entry['future'].done():
                        api_entry['future'].set_result(api_entry['responses'])
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
                    except:
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

# ---------- Telegram startup ----------
async def start_telegram():
    if BOT_TOKEN:
        await client.start(bot_token=BOT_TOKEN)
        logger.info("Started Telethon as bot.")
    else:
        await client.start(PHONE)
        logger.info("Started Telethon with phone session.")
    bot_status["running"] = True
    await client.run_until_disconnected()

# ---------- HTTP API endpoints ----------
async def api_create_key(request):
    if MASTER_API_SECRET is None:
        return web.json_response({"error": "server_not_configured"}, status=500)
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    if data.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    label = data.get("label")
    token = generate_api_key(label)
    return web.json_response({"api_key": token, "label": label})

async def api_command(request):
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    api_key = data.get("api_key")
    if not api_key or not validate_api_key(api_key):
        return web.json_response({"error": "invalid_api_key"}, status=401)
    command = data.get("command")
    if not command or not isinstance(command, str):
        return web.json_response({"error": "missing_command"}, status=400)

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

    if is_third:
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

async def api_list_keys(request):
    try:
        q = await request.json()
    except:
        return web.json_response({"error": "invalid_json"}, status=400)
    if q.get("master_secret") != MASTER_API_SECRET:
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"keys": api_keys})

async def health_check(request):
    return web.Response(text="OK", status=200)

async def status(request):
    active_windows = []
    now = time.time()
    for fid, info in forwarded_from_third.items():
        remaining = max(0, int(info['deadline'] - now))
        active_windows.append(f"forwarded_id={fid}, original_msg={info.get('original_msg_id')}, count={info['count']}/{info['max']}, remaining_s={remaining}, stabilize={info.get('stabilize', False)}")
    active_text = "\n".join(active_windows) if active_windows else "None"
    html = f"""
    <!DOCTYPE html><html><head><title>Relay API Bot</title></head><body>
    <h1>Telegram Relay API Bot</h1>
    <p>Status: {'Running' if bot_status['running'] else 'Stopped'}</p>
    <p>Messages Forwarded: {bot_status['messages_forwarded']}</p>
    <p>Content Filtered: {bot_status['filtered_content']}</p>
    <pre>Active reply-windows:\n{active_text}</pre>
    </body></html>
    """
    return web.Response(text=html, content_type="text/html")

# ---------- Web server startup ----------
async def start_web_server():
    app = web.Application()
    app.router.add_post("/api/create_key", api_create_key)
    app.router.add_post("/api/command", api_command)
    app.router.add_post("/api/list_keys", api_list_keys)
    app.router.add_get("/health", health_check)
    app.router.add_get("/", status)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Web server started on port %s", PORT)
    await asyncio.Event().wait()

# ---------- Main ----------
async def main():
    await asyncio.gather(start_web_server(), start_telegram())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Fatal error: %s", e)
