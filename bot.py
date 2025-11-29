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
            logger.info(f"   Checking if from friend bot (expected: {FRIEND_BOT_ID}, actual: {from_user.id})")
            
            if from_user.id == FRIEND_BOT_ID:
                logger.info(f"✅ Confirmed: Message from FRIEND BOT")
                logger.info(f"   Message content: '{message_text}'")
                
                if update.message.reply_to_message:
                    replied_to_msg_id = update.message.reply_to_message.message_id
                    replied_to_text = update.message.reply_to_message.text or ""
                    logger.info(f"✅ Friend bot replied to message ID: {replied_to_msg_id}")
                    logger.info(f"   Original message was: '{replied_to_text}'")
                    logger.info(f"📊 Current message_map: {message_map}")
                    
                    if replied_to_msg_id in message_map:
                        new_group_id, original_msg_id = message_map[replied_to_msg_id]
                        
                        # Keep the response as-is, just add a simple header
                        modified_response = f"🤖 Response:\n\n{message_text}"
                        
                        logger.info(f"📤 Sending response to group {new_group_id}")
                        logger.info(f"   Response content: '{modified_response}'")
                        
                        await context.bot.send_message(
                            chat_id=new_group_id,
                            text=modified_response,
                            reply_to_message_id=original_msg_id
                        )
                        
                        logger.info(f"✅ SUCCESS! Sent response back to new group")
                        del message_map[replied_to_msg_id]
                    else:
                        logger.warning(f"❌ No mapping found for message ID {replied_to_msg_id}")
                        logger.warning(f"   Available mappings: {list(message_map.keys())}")
                else:
                    logger.info("⚠️ Friend bot message is NOT a reply - ignoring")
                    logger.info("   (Friend bot must REPLY to the forwarded message)")
            else:
                logger.info(f"⚠️ Message from user {from_user.id}, not friend bot {FRIEND_BOT_ID}")
        
        # Case 2: Message from new group
        else:
            logger.info(f"🎯 This is from NEW GROUP (ID: {chat_id})")
            
            logger.info(f"📤 Forwarding message to existing group {EXISTING_GROUP_ID}...")
            logger.info(f"   Message content: '{message_text}'")
            
            # Try forwarding the original message instead of sending a copy
            try:
                sent_msg = await context.bot.forward_message(
                    chat_id=EXISTING_GROUP_ID,
                    from_chat_id=chat_id,
                    message_id=update.message.message_id
                )
                logger.info(f"✅ Message forwarded! Message ID in existing group: {sent_msg.message_id}")
            except Exception as forward_error:
                logger.warning(f"⚠️ Forward failed: {forward_error}")
                logger.info("   Trying to send as new message instead...")
                # Fallback: send as new message
                sent_msg = await context.bot.send_message(
                    chat_id=EXISTING_GROUP_ID,
                    text=message_text
                )
                logger.info(f"✅ Message sent! Message ID in existing group: {sent_msg.message_id}")
            
            logger.info(f"   Now waiting for friend bot (ID: {FRIEND_BOT_ID}) to reply to this message...")
            
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
    
    # Add message handler for commands (messages starting with /)
    application.add_handler(MessageHandler(
        filters.COMMAND,
        handle_message
    ))
    
    # Add message handler for all other messages
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
