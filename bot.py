from telethon import TelegramClient, events
import asyncio
import os
from aiohttp import web
from datetime import datetime, timedelta

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

# Dictionary to track command timestamps (forwarded_msg_id -> timestamp)
command_timestamps = {}

# Time window for forwarding responses (in seconds)
TIME_WINDOW = 30

# Bot status
bot_status = {"running": False, "messages_forwarded": 0, "messages_ignored": 0}

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
            
            # Store the mapping and timestamp
            message_map[message.id] = forwarded.id
            reverse_map[forwarded.id] = message.id
            command_timestamps[forwarded.id] = datetime.now()
            bot_status["messages_forwarded"] += 1
            
            print(f"✓ Forwarded command from first group: {message.text}")
        except Exception as e:
            print(f"Error forwarding command: {e}")

@client.on(events.NewMessage(chats=second_group))
async def forward_reply(event):
    """Forward replies from second group back to first group (only within 30 seconds)"""
    message = event.message
    current_time = datetime.now()
    
    # Check if this is a reply to a forwarded message
    if message.reply_to_msg_id:
        original_msg_id = reverse_map.get(message.reply_to_msg_id)
        command_time = command_timestamps.get(message.reply_to_msg_id)
        
        if original_msg_id and command_time:
            # Check if response is within 30 seconds of command
            time_diff = (current_time - command_time).total_seconds()
            
            if time_diff <= TIME_WINDOW:
                try:
                    # Send the reply back to the first group
                    await client.send_message(
                        first_group,
                        message.text,
                        reply_to=original_msg_id
                    )
                    bot_status["messages_forwarded"] += 1
                    print(f"✓ Forwarded reply back to first group (after {time_diff:.1f}s): {message.text[:50]}...")
                except Exception as e:
                    print(f"Error forwarding reply: {e}")
            else:
                bot_status["messages_ignored"] += 1
                print(f"✗ Ignored late reply (after {time_diff:.1f}s): {message.text[:50]}...")
                
                # Clean up old timestamp to save memory
                del command_timestamps[message.reply_to_msg_id]
        else:
            bot_status["messages_ignored"] += 1
            print(f"✗ Ignored reply - no matching command found")
    else:
        # Check if there are any recent commands (within 30 seconds)
        recent_command = None
        for forwarded_id, timestamp in list(command_timestamps.items()):
            time_diff = (current_time - timestamp).total_seconds()
            
            if time_diff <= TIME_WINDOW:
                recent_command = forwarded_id
                break
            else:
                # Clean up old timestamps
                del command_timestamps[forwarded_id]
        
        # Only forward non-reply messages if there's a recent command
        if recent_command and not message.text.startswith('/'):
            original_msg_id = reverse_map.get(recent_command)
            command_time = command_timestamps.get(recent_command)
            time_diff = (current_time - command_time).total_seconds()
            
            try:
                await client.send_message(
                    first_group,
                    f"📩 Response from bot:\n{message.text}"
                )
                bot_status["messages_forwarded"] += 1
                print(f"✓ Forwarded response to first group (after {time_diff:.1f}s)")
            except Exception as e:
                print(f"Error forwarding response: {e}")
        else:
            bot_status["messages_ignored"] += 1
            print(f"✗ Ignored random message - no recent command: {message.text[:50]}...")

async def start_telegram_bot():
    """Start the Telegram client"""
    await client.start(phone)
    bot_status["running"] = True
    print("✓ Telegram bot started successfully!")
    print(f"✓ Monitoring group: {first_group}")
    print(f"✓ Forwarding to group: {second_group}")
    print(f"✓ Time window: {TIME_WINDOW} seconds")
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
            .stats {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 10px;
                margin: 15px 0;
            }}
            .stat-box {{
                padding: 15px;
                background: #f8f9fa;
                border-radius: 5px;
                text-align: center;
            }}
            .stat-number {{
                font-size: 24px;
                font-weight: bold;
                color: #0088cc;
            }}
            .stat-label {{
                font-size: 12px;
                color: #666;
                margin-top: 5px;
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
            <div class="stats">
                <div class="stat-box">
                    <div class="stat-number">{bot_status['messages_forwarded']}</div>
                    <div class="stat-label">Messages Forwarded</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number">{bot_status['messages_ignored']}</div>
                    <div class="stat-label">Messages Ignored</div>
                </div>
            </div>
            <div class="info">
                <strong>📊 Configuration:</strong><br>
                Source Group: {first_group}<br>
                Destination Group: {second_group}<br>
                Time Window: {TIME_WINDOW} seconds
            </div>
            <div class="info">
                <strong>ℹ️ How it works:</strong><br>
                • Messages starting with '/' in {first_group} are forwarded to {second_group}<br>
                • Bot responses in {second_group} are forwarded back ONLY if they arrive within {TIME_WINDOW} seconds<br>
                • Random messages from the bot (without recent commands) are ignored<br>
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
