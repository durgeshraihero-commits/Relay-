from telethon import TelegramClient, events
import asyncio
import os

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
            print(f"✓ Forwarded response to first group")
        except Exception as e:
            print(f"Error forwarding response: {e}")

async def main():
    # Start the client
    await client.start(phone)
    print("✓ Client started successfully!")
    print(f"✓ Monitoring group: {first_group}")
    print(f"✓ Forwarding to group: {second_group}")
    print("✓ Bot is running... Press Ctrl+C to stop")
    
    # Keep the client running
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✓ Bot stopped by user")
    except Exception as e:
        print(f"Error: {e}")
