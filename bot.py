from telethon import TelegramClient, events
import asyncio
import os
from aiohttp import web

# Your API credentials (use environment variables for security)
api_id = int(os.getenv('API_ID', '36246931'))
api_hash = os.getenv('API_HASH', 'e9708f05bedf286d69abed0da7f44580')
phone = os.getenv('PHONE', '+917667280752')

# Group usernames/IDs
first_group = os.getenv('FIRST_GROUP', 'eticalosinter')  # Source group (commands from here)
second_group = os.getenv('SECOND_GROUP', 'ethicalosinter23')  # Destination group (forward commands to here)

# Initialize the client
client = TelegramClient('relay_session', api_id, api_hash)

# Dictionary to track message mappings (original_msg_id -> forwarded_msg_id)
message_map = {}
reverse_map = {}  # forwarded_msg_id -> original_msg_id

# Bot status
bot_status = {"running": False, "messages_forwarded": 0}

@client.on(events.NewMessage(chats=first_group))
async def forward_command(event):
    """Forward messages starting with '/' from first group to second group"""
    message = event.message
    
    # Check if message starts with '/'
    if message.text and message.text.startswith('/'):
        try:
            # Forward the message to the second group
            forwarded = await client.send_message(
                second_group,
                message.text
            )
            
            # Store the mapping
            message_map[message.id] = forwarded.id
            reverse_map[forwarded.id] = message.id
            bot_status["messages_forwarded"] += 1
            
            print(f"✓ Forwarded command from first group: {message.text}")
        except Exception as e:
            print(f"Error forwarding command: {e}")

@client.on(events.NewMessage(chats=second_group))
async def forward_reply(event):
    """Forward replies from second group back to first group"""
    message = event.message
    
    # Check if this is a reply to a forwarded message
    if message.reply_to_msg_id:
        original_msg_id = reverse_map.get(message.reply_to_msg_id)
        
        if original_msg_id:
            try:
                # Send the reply back to the first group
                await client.send_message(
                    first_group,
                    message.text,
                    reply_to=original_msg_id
                )
                bot_status["messages_forwarded"] += 1
                print(f"✓ Forwarded reply back to first group: {message.text[:50]}...")
            except Exception as e:
                print(f"Error forwarding reply: {e}")
    # Also forward non-reply messages that might be responses
    elif not message.text.startswith('/'):
        try:
            await client.send_message(
                first_group,
                f"📩 Response from bot:\n{message.text}"
            )
            bot_status["messages_forwarded"] += 1
            print(f"✓ Forwarded response to first group")
        except Exception as e:
            print(f"Error forwarding response: {e}")

async def start_telegram_bot():
    """Start the Telegram client"""
    await client.start(phone)
    bot_status["running"] = True
    print("✓ Telegram bot started successfully!")
    print(f"✓ Monitoring group: {first_group}")
    print(f"✓ Forwarding to group: {second_group}")
    await client.run_until_disconnected()

# Web server handlers
async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="OK", status=200)

async def status(request):
    """Status page showing bot information"""
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
            h1 {{
                color: #0088cc;
            }}
            .status {{
                padding: 10px;
                margin: 10px 0;
                border-radius: 5px;
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }}
            .info {{
                margin: 15px 0;
                padding: 10px;
                background: #e7f3ff;
                border-left: 4px solid #0088cc;
            }}
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
                • Messages starting with '/' in {first_group} are forwarded to {second_group}<br>
                • Replies in {second_group} are sent back to {first_group}<br>
                • This page refreshes every 30 seconds
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def start_web_server():
    """Start the web server"""
    app = web.Application()
    app.router.add_get('/', status)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', status)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Get port from environment variable (Render provides this)
    port = int(os.getenv('PORT', 10000))
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✓ Web server started on port {port}")
    print(f"✓ Access at http://0.0.0.0:{port}")
    
    # Keep the server running
    await asyncio.Event().wait()

async def main():
    """Main function to run both web server and Telegram bot"""
    # Start both tasks concurrently
    await asyncio.gather(
        start_web_server(),
        start_telegram_bot()
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✓ Bot stopped by user")
    except Exception as e:
        print(f"Error: {e}")
