from telethon import TelegramClient, events
import asyncio
import os
from aiohttp import web
import logging

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

# mapping original_msg_id (in first_group) -> forwarded_msg_id (in second_group)
message_map = {}
# reverse mapping forwarded_msg_id -> original_msg_id
reverse_map = {}

bot_status = {"running": False, "messages_forwarded": 0}

# Helper: safe get text (message.text can be None)
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

@client.on(events.NewMessage(chats=first_group))
async def forward_command(event):
    """
    Forward messages starting with '/' from first group to second group
    BUT only if:
      - the command is not '/start'
      - the same message still exists and has the same text 2 seconds later
    """
    message = event.message
    text = _get_text(message)

    # Only proceed if there's text and it starts with '/'
    if not text or not text.startswith('/'):
        return

    # Never forward /start
    stripped = text.split()[0]  # command token (e.g. '/start' or '/help')
    if stripped.lower() == '/start':
        logger.info("Received /start in source group — will NOT forward.")
        return

    try:
        # Wait 2 seconds and re-check that the message exists and hasn't changed
        await asyncio.sleep(2)
        # Fetch the message again from the source chat by ID
        latest = await client.get_messages(first_group, ids=message.id)

        # If message was deleted or content changed, skip forwarding
        if not latest:
            logger.info(f"Message id {message.id} appears deleted after 2s — skipping forward.")
            return

        latest_text = _get_text(latest)
        if latest_text != text:
            logger.info(f"Message id {message.id} text changed after 2s — skipping forward.")
            return

        # All checks passed — forward/send the command text to the second group
        forwarded = await client.send_message(second_group, text)
        # store mappings
        message_map[message.id] = forwarded.id
        reverse_map[forwarded.id] = message.id
        bot_status["messages_forwarded"] += 1

        logger.info(f"✓ Forwarded command from {first_group} -> {second_group}: {text}")
    except Exception as e:
        logger.exception(f"Error while trying to forward command: {e}")

@client.on(events.NewMessage(chats=second_group))
async def forward_reply(event):
    """
    Forward replies from second group back to first group.
    If the message in second_group is a reply to a forwarded message, reply to the original message ID.
    Also forward non-command responses back as "Response from bot:" (skip commands).
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
        # Either no text or it's a command — ignore
        logger.debug("Ignored message from second_group (either command or empty).")

async def start_telegram_bot():
    """Start the Telegram client"""
    await client.start(phone)
    bot_status["running"] = True
    logger.info("✓ Telegram bot started successfully!")
    logger.info(f"✓ Monitoring group: {first_group}")
    logger.info(f"✓ Forwarding to group: {second_group}")
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
                • Messages starting with '/' in {first_group} are forwarded to {second_group} only if they still exist after 2 seconds.<br>
                • '/start' is never forwarded.<br>
                • Replies in {second_group} are sent back to {first_group} (when mapping exists).
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
