#!/usr/bin/env python3
from telethon import TelegramClient, events
import asyncio
import os
import logging
import json
import time
from aiohttp import web

# --- config from env ---
api_id = int(os.getenv('API_ID', '36246931'))
api_hash = os.getenv('API_HASH', 'e9708f05bedf286d69abed0da7f44580')
phone = os.getenv('PHONE', '+917667280752')

first_group = os.getenv('FIRST_GROUP', 'eticalosinter')        # source
second_group = os.getenv('SECOND_GROUP', 'ethicalosinter23')   # destination 1
third_group = os.getenv('THIRD_GROUP', 'IntelXGroup')          # destination 2 (for 2/ commands)

# reply window duration (seconds) after forwarding to third_group
THIRD_REPLY_WINDOW = int(os.getenv('THIRD_REPLY_WINDOW', '5'))

# --- init ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger("relay_bot")

client = TelegramClient('relay_session', api_id, api_hash)

# mapping original_msg_id (in first_group) -> forwarded_msg_id (in second_group)
message_map = {}
# reverse mapping forwarded_msg_id -> original_msg_id
reverse_map = {}

# mapping for third group (source_msg_id -> forwarded_msg_id)
message_map_third = {}
reverse_map_third = {}

# Track which messages from third group have already been forwarded
# Key: forwarded_msg_id (the id in third_group we sent), Value: dict with count/max/deadline, original_msg_id
forwarded_from_third = {}

bot_status = {"running": False, "messages_forwarded": 0}

# Helper: safe get text (message.text can be None)
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

def remove_footer(text):
    """Remove the footer line from JSON responses (best-effort)."""
    if not text:
        return text
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "footer" in data:
            del data["footer"]
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        # fallback: simple line filter
        lines = text.splitlines()
        filtered = [L for L in lines if '"footer"' not in L and '@frappeash' not in L]
        return '\n'.join(filtered)

@client.on(events.NewMessage(chats=first_group))
async def forward_command(event):
    """
    Forward messages starting with '/' or '2/' from first group to appropriate destination group
    - For ALL commands (including 2/), wait 5 seconds and verify message unchanged
    - Never forward '/start'
    """
    message = event.message
    text = _get_text(message)

    # Only proceed if there's text and it starts with '/' or '2/'
    if not text or not (text.startswith('/') or text.startswith('2/')):
        return

    # Determine target group and clean command
    target_group = second_group
    clean_command = text
    is_third_group = False

    if text.startswith('2/'):
        target_group = third_group
        is_third_group = True
        # Remove the '2' prefix but keep the leading slash
        # Example: '2/vnum arg' -> '/vnum arg'
        clean_command = '/' + text[2:]

    # Never forward /start
    stripped = clean_command.split()[0]  # command token (e.g. '/start' or '/help')
    if stripped.lower() == '/start':
        logger.info("Received /start in source group — will NOT forward.")
        return

    try:
        # WAIT 5 seconds for verification for ALL commands (including 2/)
        await asyncio.sleep(5)
        # Re-fetch the message to confirm it still exists and hasn't changed
        latest = await client.get_messages(first_group, ids=message.id)
        if not latest:
            logger.info(f"Message id {message.id} appears deleted after 5s — skipping forward.")
            return
        latest_text = _get_text(latest)
        if latest_text != text:
            logger.info(f"Message id {message.id} text changed after 5s — skipping forward.")
            return

        # All checks passed — forward/send the command text to the target group
        forwarded = await client.send_message(target_group, clean_command)

        # Store mappings based on target group
        if is_third_group:
            # Map source -> forwarded and reverse
            message_map_third[message.id] = forwarded.id
            reverse_map_third[forwarded.id] = message.id

            # Determine allowed replies: default 1; for /vnum and /bomber allow 2
            cmd_token = clean_command.split()[0].lower()
            allowed = 1
            if cmd_token in ['/vnum', '/bomber']:
                allowed = 2

            # Track the forwarded message id with reply window measured from now
            forwarded_from_third[forwarded.id] = {
                'count': 0,
                'max': allowed,
                'deadline': time.time() + THIRD_REPLY_WINDOW,
                'original_msg_id': message.id
            }

            logger.info(f"Reply-tracking set for third_group message {forwarded.id}: max={allowed}, deadline={forwarded_from_third[forwarded.id]['deadline']}")
        else:
            # mapping for second_group forwarded messages
            message_map[message.id] = forwarded.id
            reverse_map[forwarded.id] = message.id

        bot_status["messages_forwarded"] += 1
        logger.info(f"✓ Forwarded command from {first_group} -> {target_group}: {clean_command}")
    except Exception as e:
        logger.exception(f"Error while trying to forward command: {e}")

@client.on(events.NewMessage(chats=second_group))
async def forward_reply_second(event):
    """
    Forward replies from second group back to first group.
    """
    message = event.message
    text = _get_text(message)

    # If this message is a reply to something in second_group, try to map back
    if message.reply_to_msg_id:
        original_msg_id = reverse_map.get(message.reply_to_msg_id)
        if original_msg_id:
            try:
                # Reply back to the original message in the first group
                await client.send_message(first_group, text, reply_to=original_msg_id)
                bot_status["messages_forwarded"] += 1
                logger.info(f"✓ Forwarded reply back to {first_group}: {text[:50]}...")
                return
            except Exception as e:
                logger.exception(f"Error forwarding reply back to source group: {e}")
                return

    # If not a reply (or mapping not found) and not a command (don't forward commands from second_group)
    if text and not text.startswith('/'):
        try:
            await client.send_message(first_group, f"📩 Response from bot:\n{text}")
            bot_status["messages_forwarded"] += 1
            logger.info("✓ Forwarded non-reply response to source group.")
        except Exception as e:
            logger.exception(f"Error forwarding response to source group: {e}")
    else:
        logger.debug("Ignored message from second_group (either command or empty).")

@client.on(events.NewMessage(chats=third_group))
async def forward_reply_third(event):
    """
    Forward replies from third group back to first group.
    Remove footer lines from JSON responses.
    Accept replies only if:
      - The message is a direct reply to a forwarded message (we have forwarded_from_third entry)
      - The reply arrives within the configured reply window (default 5s)
      - We haven't exceeded the allowed number of replies for that forwarded message
    """
    message = event.message
    text = _get_text(message)

    # Only process if this is a reply to a message we forwarded
    if not message.reply_to_msg_id:
        logger.debug("Ignored non-reply message from third_group.")
        return

    # Check if this reply_to_msg_id exists in our mapping
    original_msg_id = reverse_map_third.get(message.reply_to_msg_id)
    if not original_msg_id:
        logger.debug("Reply in third_group doesn't map to any original message.")
        return

    # Check reply tracking info for this forwarded message
    reply_info = forwarded_from_third.get(message.reply_to_msg_id)
    if not reply_info:
        logger.debug(f"No reply tracking info found for message {message.reply_to_msg_id}")
        return

    # Check deadline (only forward replies received within the deadline)
    now = time.time()
    if now > reply_info['deadline']:
        logger.debug(f"Reply arrived after deadline for message {message.reply_to_msg_id} (now={now}, deadline={reply_info['deadline']}) — skipping.")
        return

    # Check if we've already forwarded the maximum number of replies
    if reply_info['count'] >= reply_info['max']:
        logger.debug(f"Already forwarded {reply_info['count']}/{reply_info['max']} replies for message {message.reply_to_msg_id}, skipping.")
        return

    # Clean the response by removing footer
    cleaned_text = remove_footer(text)

    try:
        # Reply back to the original message in the first group with cleaned text
        await client.send_message(first_group, cleaned_text, reply_to=reply_info['original_msg_id'])

        # Increment the reply count
        forwarded_from_third[message.reply_to_msg_id]['count'] += 1

        bot_status["messages_forwarded"] += 1
        current_count = forwarded_from_third[message.reply_to_msg_id]['count']
        logger.info(f"✓ Forwarded reply {current_count}/{reply_info['max']} back to {first_group} from third group: {cleaned_text[:50]}...")
    except Exception as e:
        logger.exception(f"Error forwarding reply back to source group from third: {e}")

async def start_telegram_bot():
    """Start the Telegram client"""
    await client.start(phone)
    bot_status["running"] = True
    logger.info("✓ Telegram bot started successfully!")
    logger.info(f"✓ Monitoring group: {first_group}")
    logger.info(f"✓ Forwarding to groups: {second_group}, {third_group}")
    await client.run_until_disconnected()

# Web server handlers (health + status)
async def health_check(request):
    return web.Response(text="OK", status=200)

async def status(request):
    # Build a small list of active reply-windows for display (optional)
    active_windows = []
    now = time.time()
    for fid, info in forwarded_from_third.items():
        remaining = max(0, int(info['deadline'] - now))
        active_windows.append(f"forwarded_id={fid}, original_msg={info['original_msg_id']}, count={info['count']}/{info['max']}, remaining_s={remaining}")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram Relay Bot</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 30px auto; background:#f5f5f5; }}
            .container {{ background:#fff; padding:24px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08); }}
            h1 {{ color:#0088cc; }}
            .status {{ padding:10px; margin:10px 0; border-radius:5px; background:#d4edda; color:#155724; border:1px solid #c3e6cb; }}
            .info {{ margin:15px 0; padding:10px; background:#e7f3ff; border-left:4px solid #0088cc; }}
            pre {{ background:#f7f7f7; padding:10px; border-radius:6px; overflow:auto; }}
        </style>
        <meta http-equiv="refresh" content="10">
    </head>
    <body>
        <div class="container">
            <h1>🤖 Telegram Multi-Group Relay Bot</h1>
            <div class="status">✅ Status: {'Running' if bot_status['running'] else 'Stopped'}</div>
            <div class="info">
                <strong>📊 Statistics:</strong><br>
                Messages Forwarded: {bot_status['messages_forwarded']}<br>
                Source Group: {first_group}<br>
                Destination Group 1: {second_group}<br>
                Destination Group 2: {third_group}
            </div>
            <div class="info">
                <strong>ℹ️ Behavior:</strong><br>
                • Bot verifies messages from the source group for 5s before forwarding.<br>
                • Messages beginning with '2/' are forwarded to the third group (as '/...').<br>
                • After forwarding to third group a reply-window of {THIRD_REPLY_WINDOW}s opens; replies to the forwarded message within that window are copied back.<br>
                • Commands '/vnum' and '/bomber' (when sent as '2/vnum' or '2/bomber') allow up to 2 replies in the window; others default to 1.
            </div>
            <div>
                <h3>Active reply-windows</h3>
                <pre>{'\\n'.join(active_windows) if active_windows else 'None'}</pre>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', status)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', status)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✓ Web server started on port {port}")
    logger.info(f"✓ Access at http://0.0.0.0:{port}")

    await asyncio.Event().wait()

async def main():
    await asyncio.gather(
        start_web_server(),
        start_telegram_bot()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("✓ Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
