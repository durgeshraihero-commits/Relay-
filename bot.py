import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Configuration
NEW_BOT_TOKEN = "8224146762:AAEJpeFIHmMeG2fjUn7ccMBiupA9Cxuewew"
EXISTING_GROUP_ID = -1003275777221
FRIEND_BOT_ID = 7574815513

# Setup logging - MORE VERBOSE
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Reduce httpx noise
logging.getLogger("httpx").setLevel(logging.WARNING)

# Store message mappings
message_map = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages"""
    try:
        logger.info("=" * 60)
        logger.info("🎯 HANDLER TRIGGERED!")

        if not update.message: 
            logger.warning("⚠️ No message in update")
            return
            
        chat_id = update.effective_chat.id
        from_user = update.message.from_user
        message_text = update.message.text or update.message.caption or ""

        logger.info(f"📩 MESSAGE: '{message_text}'")
        logger.info(f"📊 From: {from_user.id} (Bot: {from_user.is_bot})")
        logger.info(f"📍 Chat: {chat_id}")

        # Case 1: Message from existing group (check for friend bot responses)
        if chat_id == EXISTING_GROUP_ID:
            logger.info("🎯 This is from EXISTING GROUP")
            
            # Check if message is from friend bot
            if from_user.id == FRIEND_BOT_ID:
                logger.info("✅ Confirmed: Message from FRIEND BOT")
                
                if update.message.reply_to_message:
                    replied_to_msg_id = update.message.reply_to_message.message_id
                    logger.info(f"🔗 Friend bot replied to message ID: {replied_to_msg_id}")
                    
                    if replied_to_msg_id in message_map:
                        new_group_id, original_msg_id = message_map[replied_to_msg_id]
                        modified_response = f"🤖 Response:\n\n{message_text}"
                        
                        logger.info(f"📤 Sending back to new group: {new_group_id}")
                        await context.bot.send_message(
                            chat_id=new_group_id,
                            text=modified_response,
                            reply_to_message_id=original_msg_id
                        )
                        logger.info("✅ SUCCESS! Response sent to new group")
                        del message_map[replied_to_msg_id]
                    else:
                        logger.warning(f"❌ No mapping found for message ID {replied_to_msg_id}")
                else:
                    logger.warning("⚠️ Friend bot message is not a reply - ignoring")
            
            # Also handle if humans reply to our messages
            elif update.message.reply_to_message:
                replied_to_msg_id = update.message.reply_to_message.message_id
                if replied_to_msg_id in message_map:
                    logger.info(f"👤 Human replied to our message")
                    new_group_id, original_msg_id = message_map[replied_to_msg_id]
                    response_text = f"👤 {from_user.first_name}:\n{message_text}"
                    
                    await context.bot.send_message(
                        chat_id=new_group_id,
                        text=response_text,
                        reply_to_message_id=original_msg_id
                    )

        # Case 2: Message from new group (forward to existing group WITH PROPER COMMAND)
        else:
            logger.info(f"🎯 This is from NEW GROUP (ID: {chat_id})")
            
            # Extract command and value from user message
            user_message = message_text.strip()
            
            # Determine which command to use based on the input
            command_to_use = None
            value = None
            
            if user_message.isdigit() and len(user_message) >= 10:
                # If it's just numbers, use /num command
                command_to_use = "/num"
                value = user_message
            elif ' ' in user_message:
                # If user already included a command, use it as is
                parts = user_message.split(' ', 1)
                if parts[0].startswith('/'):
                    command_to_use = parts[0]
                    value = parts[1] if len(parts) > 1 else ""
                else:
                    # Default to /num for any other text
                    command_to_use = "/num"
                    value = user_message
            else:
                # Default to /num command
                command_to_use = "/num"
                value = user_message
            
            # Format the message to trigger friend bot
            trigger_message = f"{command_to_use} {value}".strip()
            
            logger.info(f"🎯 Using command: '{command_to_use}'")
            logger.info(f"📤 Sending to existing group: '{trigger_message}'")
            
            # Send the command that will trigger the friend bot
            sent_msg = await context.bot.send_message(
                chat_id=EXISTING_GROUP_ID,
                text=trigger_message
            )
            
            # Store the mapping
            message_map[sent_msg.message_id] = (chat_id, update.message.message_id)
            logger.info(f"✅ Forwarded! Message ID in existing group: {sent_msg.message_id}")
            logger.info(f"📊 Created mapping: {sent_msg.message_id} -> ({chat_id}, {update.message.message_id})")
            logger.info(f"📊 Total mappings: {len(message_map)}")

    except Exception as e:
        logger.error(f"❌ ERROR: {e}", exc_info=True)
    
    logger.info("=" * 60)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"❌ Exception while handling an update: {context.error}", exc_info=context.error)

def main():
    """Start the bot"""
    logger.info("=" * 60)
    logger.info("🚀 STARTING BOT - FRIEND BOT COMMAND VERSION")
    logger.info("=" * 60)

    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add message handler for all messages (including commands)
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    
    logger.info(f"📌 Configuration:")
    logger.info(f" Existing Group ID: {EXISTING_GROUP_ID}")
    logger.info(f" Friend Bot ID: {FRIEND_BOT_ID}")
    logger.info(f" Supported commands: /num, /aadhar, /familyinfo")
    logger.info("=" * 60)
    logger.info("🔄 Bot is now running...")
    logger.info("=" * 60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
