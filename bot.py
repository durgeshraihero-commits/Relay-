# bot.py
from telethon import TelegramClient, events
import asyncio
import os
import logging
import time
from aiohttp import web

# --- config from env ---
api_id = int(os.getenv('API_ID', '36246931'))
api_hash = os.getenv('API_HASH', 'e9708f05bedf286d69abed0da7f44580')
phone = os.getenv('PHONE', '+917667280752')

first_group = os.getenv('FIRST_GROUP', 'eticalosinter')        # source
second_group = os.getenv('SECOND_GROUP', 'ethicalosinter23')   # destination

# --- init ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger("relay_bot")

client = TelegramClient('relay_session', api_id, api_hash)

# mapping original_msg_id (in first_group) -> { forwarded_id, ts }
message_map = {}
# reverse mapping forwarded_msg_id -> original_msg_id
reverse_map = {}

bot_status = {"running": False, "messages_forwarded": 0}

# constants
FORWARD_STABILITY_WAIT = 5        # seconds to wait and re-check original message before forwarding
RESPONSE_WINDOW = 30              # seconds: only forward replies that arrive within this window
CLEANUP_INTERVAL = 60             # seconds: how often to cleanup old mappings
MAPPING_MAX_AGE = 120             # seconds: delete mappings older than this

# Helper: safe get text (message.text can be None)
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

@client.on(events.NewMessage(chats=first_group))
async def forward_command(event):
    """
    Forward messages starting with '/' from first group to second group
    Conditions:
      - message starts with '/'
      - not '/start'
      - message still exists with same text after FORWARD_STABILITY_WAIT seconds
    After forwarding we store mapping with timestamp so replies can be validated.
    """
    message = event.message
    text = _get_text(message)

    if not text or not text.startswith('/'):
        return

    # Never forward /start
    stripped = text.split()[0]  # command token (e.g. '/start' or '/help')
    if stripped.lower() == '/start':
        logger.info("Received /start in source group — will NOT forward.")
        return

    try:
        # Wait a short time to avoid ephemeral/accidental commands
        await asyncio.sleep(FORWARD_STABILITY_WAIT)

        # Fetch the message again from the source chat by ID to ensure it still exists
        latest = await client.get_messages(first_group, ids=message.id)
        if not latest:
            logger.info(f"Message id {message.id} appears deleted after stability wait — skipping forward.")
            return
        latest_text = _get_text(latest)
        if latest_text != text:
            logger.info(f"Message id {message.id} text changed after stability wait — skipping forward.")
            return

        # All checks passed — forward/send the command text to the second group
        forwarded = await client.send_message(second_group, text)

        # store mappings with timestamp
        ts = time.time()
        message_map[message.id] = {"forwarded_id": forwarded.id, "ts": ts}
        reverse_map[forwarded.id] = message.id
        bot_status["messages_forwarded"] += 1

        logger.info(f"✓ Forwarded command {message.id} from {first_group} -> {second_group}: {text}")
    except Exception as e:
        logger.exception(f"Error while trying to forward command: {e}")

@client.on(events.NewMessage(chats=second_group))
async def forward_reply(event):
    """
    Forward replies from second group back to first group only when:
      - the message is a reply to a forwarded message AND
      - the reply timestamp is within RESPONSE_WINDOW seconds of the original user message timestamp.
    Non-reply messages are ignored (so random bot messages won't be forwarded).
    """
    message = event.message
    text = _get_text(message)

    # If this message is a reply to something in second_group, try to map back
    if message.reply_to_msg_id:
        original_msg_id = reverse_map.get(message.reply_to_msg_id)
        if original_msg_id:
            mapping = message_map.get(original_msg_id)
            if mapping:
                sent_ts = mapping.get("ts", 0)
                now = time.time()
                age = now - sent_ts
                if age <= RESPONSE_WINDOW:
                    try:
                        # Reply back to the original message in the first group
                        await client.send_message(first_group, text, reply_to=original_msg_id)
                        bot_status["messages_forwarded"] += 1
                        logger.info(f"✓ Forwarded timely reply back to {first_group} (orig_id={original_msg_id}) age={age:.1f}s: {text[:50]}...")
                    except Exception as e:
                        logger.exception(f"Error forwarding reply back to source group: {e}")
                else:
                    logger.info(f"Ignored reply in {second_group} for original {original_msg_id} — arrived after {age:.1f}s (> {RESPONSE_WINDOW}s).")
            else:
                logger.debug(f"No mapping found for original {original_msg_id} — ignoring reply.")
        else:
            logger.debug("Reply in destination group is not to a forwarded message — ignoring.")
        return

    # If not a reply (or mapping not found) — ignore to prevent random messages getting forwarded
    logger.debug("Ignored non-reply/non-mapped message from destination group (prevents random bot messages).")

async def cleanup_task():
    """Periodically remove old mappings to keep memory small."""
    while True:
        try:
            now = time.time()
            to_delete = []
            for orig_id, info in list(message_map.items()):
                if now - info.get("ts", 0) > MAPPING_MAX_AGE:
                    to_delete.append(orig_id)
            for orig_id in to_delete:
                fwd_id = message_map[orig_id].get("forwarded_id")
                message_map.pop(orig_id, None)
                if fwd_id:
                    reverse_map.pop(fwd_id, None)
                logger.debug(f"Cleaned mapping orig={orig_id}, fwd={fwd_id}")
        except Exception as e:
            logger.exception(f"Error during cleanup: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL)

async def start_telegram_bot():
    """Start the Telegram client and cleanup background task"""
    await client.start(phone)
    bot_status["running"] = True
    logger.info("✓ Telegram bot started successfully!")
    logger.info(f"✓ Monitoring group: {first_group}")
    logger.info(f"✓ Forwarding to group: {second_group}")

    # spawn cleanup task
    client.loop.create_task(cleanup_task())

    await client.run_until_disconnected()

# Web server handlers (unchanged except small logging)
async def health_check(request):
    return web.Response(text="OK", status=200)

async def status(request):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Telegram Relay Bot</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            h1 {{ color: #0088cc; }}
            .status {{ padding: 10px; margin: 10px 0; border-radius: 5px; background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
            .info {{ margin: 15px 0; padding: 10px; background: #e7f3ff; border-left: 4px solid #0088cc; }}
        </style>
        <meta http-equiv="refresh" content="30">
    </head>
    <body>
        <div class="container">
            <h1>🤖 Telegram Relay Bot</h1>
            <div class="status">
                ✅ Status: {'Running' if bot_status['running'] else 'Stopped'}
            </div>
            <div class="info">
                <strong>📊 Statistics:</strong><br>
                Messages Forwarded: {bot_status['messages_forwarded']}<br>
                Source Group: {first_group}<br>
                Destination Group: {second_group}
            </div>
            <div class="info">
                <strong>ℹ️ How it works:</strong><br>
                • Commands starting with '/' from the source group are forwarded to the destination group (stability wait applied).<br>
                • Replies in the destination group are forwarded back only if they are replies to the forwarded message and arrive within {RESPONSE_WINDOW} seconds of the original command.<br>
                • Random/non-reply messages in the destination group are ignored (so the bot won't forward unexpected messages).
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
