import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Configuration
NEW_BOT_TOKEN = "8224146762:AAEJpeFIHmMeG2fjUn7ccMBiupA9Cxuewew"
EXISTING_GROUP_ID = -1003275777221
FRIEND_BOT_ID = 7574815513

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store message mappings: {existing_group_msg_id: (new_group_chat_id, new_group_msg_id)}
message_map = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all incoming messages"""
    try:
        if not update.message:
            return
        
        chat_id = update.effective_chat.id
        message_text = update.message.text or update.message.caption or ""
        
        logger.info(f"📩 Received message from chat {chat_id}: {message_text[:50]}...")
        
        # Case 1: Message from existing group (response from friend bot)
        if chat_id == EXISTING_GROUP_ID:
            logger.info("✓ Message is from EXISTING group")
            
            # Check if message is from friend bot
            if update.message.from_user.id == FRIEND_BOT_ID:
                logger.info(f"✓ Message is from FRIEND BOT (ID: {FRIEND_BOT_ID})")
                
                # Check if it's a reply
                if update.message.reply_to_message:
                    replied_to_msg_id = update.message.reply_to_message.message_id
                    logger.info(f"✓ Friend bot replied to message ID: {replied_to_msg_id}")
                    
                    # Check if we have mapping
                    if replied_to_msg_id in message_map:
                        new_group_id, original_msg_id = message_map[replied_to_msg_id]
                        
                        # Modify response
                        modified_response = f"🤖 Assistant Response:\n\n{message_text}"
                        
                        # Send back to new group
                        await context.bot.send_message(
                            chat_id=new_group_id,
                            text=modified_response,
                            reply_to_message_id=original_msg_id
                        )
                        
                        logger.info(f"✅ Sent response back to new group {new_group_id}")
                        
                        # Clean up
                        del message_map[replied_to_msg_id]
                    else:
                        logger.warning(f"⚠️ No mapping found for message ID {replied_to_msg_id}")
                else:
                    logger.info("⚠️ Friend bot message is not a reply")
            else:
                logger.info(f"⚠️ Message is from user {update.message.from_user.id}, not friend bot")
        
        # Case 2: Message from new group (user query)
        else:
            logger.info(f"✓ Message is from NEW group (ID: {chat_id})")
            
            # Forward to existing group
            sent_msg = await context.bot.send_message(
                chat_id=EXISTING_GROUP_ID,
                text=f"User Query:\n{message_text}"
            )
            
            # Store mapping
            message_map[sent_msg.message_id] = (chat_id, update.message.message_id)
            
            logger.info(f"✅ Forwarded to existing group. Mapping: {sent_msg.message_id} -> ({chat_id}, {update.message.message_id})")
            logger.info(f"📊 Current message_map: {message_map}")
            
    except Exception as e:
        logger.error(f"❌ Error handling message: {e}", exc_info=True)


def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    # Add handler for ALL text messages (including from groups and channels)
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
        handle_message
    ))
    
    # Start the bot
    logger.info("🚀 Bot started successfully!")
    logger.info(f"📌 Existing Group ID: {EXISTING_GROUP_ID}")
    logger.info(f"📌 Friend Bot ID: {FRIEND_BOT_ID}")
    logger.info("🔄 Waiting for messages...")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
