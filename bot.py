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
    level=logging.DEBUG  # Changed to DEBUG for more info
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
        chat_type = update.effective_chat.type
        from_user = update.message.from_user
        message_text = update.message.text or update.message.caption or ""
        
        logger.info(f"📩 MESSAGE DETAILS:")
        logger.info(f"   Chat ID: {chat_id}")
        logger.info(f"   Chat Type: {chat_type}")
        logger.info(f"   From User: {from_user.id} (@{from_user.username})")
        logger.info(f"   Message: {message_text[:100]}")
        logger.info(f"   Is Reply: {update.message.reply_to_message is not None}")
        
        # Case 1: Message from existing group
        if chat_id == EXISTING_GROUP_ID:
            logger.info("🎯 This is from EXISTING GROUP")
            
            if from_user.id == FRIEND_BOT_ID:
                logger.info(f"✅ Confirmed: Message from FRIEND BOT")
                
                if update.message.reply_to_message:
                    replied_to_msg_id = update.message.reply_to_message.message_id
                    logger.info(f"✅ Friend bot replied to message ID: {replied_to_msg_id}")
                    logger.info(f"📊 Current message_map: {message_map}")
                    
                    if replied_to_msg_id in message_map:
                        new_group_id, original_msg_id = message_map[replied_to_msg_id]
                        
                        modified_response = f"🤖 Assistant Response:\n\n{message_text}"
                        
                        logger.info(f"📤 Sending response to group {new_group_id}")
                        await context.bot.send_message(
                            chat_id=new_group_id,
                            text=modified_response,
                            reply_to_message_id=original_msg_id
                        )
                        
                        logger.info(f"✅ SUCCESS! Sent response back to new group")
                        del message_map[replied_to_msg_id]
                    else:
                        logger.warning(f"❌ No mapping found for message ID {replied_to_msg_id}")
                        logger.warning(f"Available mappings: {list(message_map.keys())}")
                else:
                    logger.info("⚠️ Friend bot message is NOT a reply - ignoring")
            else:
                logger.info(f"⚠️ Message from user {from_user.id}, not friend bot {FRIEND_BOT_ID}")
        
        # Case 2: Message from new group
        else:
            logger.info(f"🎯 This is from NEW GROUP (ID: {chat_id})")
            
            logger.info(f"📤 Forwarding to existing group {EXISTING_GROUP_ID}...")
            # Send the message exactly as received
            sent_msg = await context.bot.send_message(
                chat_id=EXISTING_GROUP_ID,
                text=message_text
            )
            
            message_map[sent_msg.message_id] = (chat_id, update.message.message_id)
            
            logger.info(f"✅ SUCCESS! Forwarded to existing group")
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
    logger.info("🚀 STARTING BOT")
    logger.info("=" * 60)
    
    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add message handler - catches ALL messages
    application.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND,
        handle_message
    ))
    
    logger.info(f"📌 Configuration:")
    logger.info(f"   Existing Group ID: {EXISTING_GROUP_ID}")
    logger.info(f"   Friend Bot ID: {FRIEND_BOT_ID}")
    logger.info(f"   Handler registered: YES")
    logger.info("=" * 60)
    logger.info("🔄 Bot is now running and waiting for messages...")
    logger.info("   Send a message in any group to test!")
    logger.info("=" * 60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
