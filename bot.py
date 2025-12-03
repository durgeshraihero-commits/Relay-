from telethon import TelegramClient, events
import asyncio
import os
from aiohttp import web
import logging
import json
import re

# --- config from env ---
api_id = int(os.getenv('API_ID', '36246931'))
api_hash = os.getenv('API_HASH', 'e9708f05bedf286d69abed0da7f44580')
phone = os.getenv('PHONE', '+917667280752')

first_group = os.getenv('FIRST_GROUP', 'eticalosinter')        # source
second_group = os.getenv('SECOND_GROUP', 'ethicalosinter23')   # destination 1
third_group = os.getenv('THIRD_GROUP', 'IntelXGroup')          # destination 2 (for 2/ commands)

# --- init ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger("relay_bot")

client = TelegramClient('relay_session', api_id, api_hash)

# mapping original_msg_id (in first_group) -> forwarded_msg_id (in second_group)
message_map = {}
# reverse mapping forwarded_msg_id -> original_msg_id
reverse_map = {}

# mapping for third group
message_map_third = {}
reverse_map_third = {}

# Track which messages from third group have already been forwarded
# Key: reply_to_msg_id, Value: count of replies forwarded
forwarded_from_third = {}

bot_status = {"running": False, "messages_forwarded": 0}

# Helper: safe get text (message.text can be None)
def _get_text(msg):
    return msg.text if msg and getattr(msg, "text", None) is not None else ""

def remove_footer(text):
    """Remove the footer line from JSON responses"""
    try:
        # Try to parse as JSON
        data = json.loads(text)
        # Remove footer if it exists
        if isinstance(data, dict) and "footer" in data:
            del data["footer"]
        # Return cleaned JSON
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, Exception):
        # If not JSON, try simple text replacement
        lines = text.split('\n')
        filtered_lines = [line for line in lines if '"footer"' not in line and '@frappeash' not in line]
        return '\n'.join(filtered_lines)

@client.on(events.NewMessage(chats=first_group))
async def forward_command(event):
    """
    Forward messages starting with '/' or '2/' from first group to appropriate destination group
    - For regular '/' commands: wait 5 seconds and verify message unchanged
    - For '2/' commands: forward immediately to third group (no delay)
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
        # Remove '2' prefix but keep the '/'
        clean_command = '/' + text[2:]
    
    # Never forward /start
    stripped = clean_command.split()[0]  # command token (e.g. '/start' or '/help')
    if stripped.lower() == '/start':
        logger.info("Received /start in source group — will NOT forward.")
        return

    try:
        # Wait 5 seconds and re-check that the message exists and hasn't changed (for both groups)
        await asyncio.sleep(5)
        # Fetch the message again from the source chat by ID
        latest = await client.get_messages(first_group, ids=message.id)

        # If message was deleted or content changed, skip forwarding
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
            message_map_third[message.id] = forwarded.id
            reverse_map_third[forwarded.id] = message.id
        else:
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
    Forward up to the maximum number of replies expected for each command.
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

    # Check reply count for this message
    reply_info = forwarded_from_third.get(message.reply_to_msg_id)
    if not reply_info:
        logger.debug(f"No reply tracking info found for message {message.reply_to_msg_id}")
        return
    
    # Check if we've already forwarded the maximum number of replies
    if reply_info['count'] >= reply_info['max']:
        logger.debug(f"Already forwarded {reply_info['count']}/{reply_info['max']} replies for message {message.reply_to_msg_id}, skipping.")
        return

    # Clean the response by removing footer
    cleaned_text = remove_footer(text)

    try:
        # Reply back to the original message in the first group with cleaned text
        await client.send_message(first_group, cleaned_text, reply_to=original_msg_id)
        
        # Increment the reply count
        forwarded_from_third[message.reply_to_msg_id]['count'] += 1
        
        bot_status["messages_forwarded"] += 1
        logger.info(f"✓ Forwarded reply {reply_info['count'] + 1}/{reply_info['max']} back to {first_group} from third group: {cleaned_text[:50]}...")
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

# Web server handlers
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
            <h1>🤖 Telegram Multi-Group Relay Bot</h1>
            <div class="status">
                ✅ Status: {'Running' if bot_status['running'] else 'Stopped'}
            </div>
            <div class="info">
                <strong>📊 Statistics:</strong><br>
                Messages Forwarded: {bot_status['messages_forwarded']}<br>
                Source Group: {first_group}<br>
                Destination Group 1: {second_group}<br>
                Destination Group 2 (IntelX): {third_group}
            </div>
            <div class="info">
                <strong>ℹ️ How it works:</strong><br>
                • Messages starting with '/' in {first_group} are forwarded to {second_group} after 5 second verification<br>
                • Messages starting with '2/' in {first_group} are forwarded to {third_group} (as '/command') after 5 second verification<br>
                • '/start' is never forwarded<br>
                • From {third_group}: Most commands get ONE reply, '/vnum' gets TWO replies (footer removed)<br>
                • From {second_group}: All replies are forwarded back
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
