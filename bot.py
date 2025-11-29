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

async def handle_new_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from new group - forward to existing group"""
    if not update.message or not update.message.text:
        return
    
    new_group_id = update.effective_chat.id
    user_message = update.message.text
    
    try:
        # Forward message to existing group
        sent_msg = await context.bot.send_message(
            chat_id=EXISTING_GROUP_ID,
            text=f"User Query:\n{user_message}"
        )
        
        # Store mapping for reply tracking
        message_map[sent_msg.message_id] = (new_group_id, update.message.message_id)
        
        logger.info(f"Forwarded message from new group to existing group")
        
    except Exception as e:
        logger.error(f"Error forwarding message: {e}")
        await update.message.reply_text("Sorry, there was an error processing your request.")


async def handle_existing_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from existing group - check if it's from friend bot"""
    if not update.message:
        return
    
    # Check if message is from the friend bot
    if update.message.from_user.id != FRIEND_BOT_ID:
        return
    
    # Check if this is a reply to our forwarded message
    if not update.message.reply_to_message:
        return
    
    replied_to_msg_id = update.message.reply_to_message.message_id
    
    # Check if we have a mapping for this message
    if replied_to_msg_id not in message_map:
        return
    
    new_group_id, original_msg_id = message_map[replied_to_msg_id]
    
    try:
        # Get the bot's response text
        bot_response = update.message.text or update.message.caption or ""
        
        # Modify the response (you can customize this modification)
        modified_response = f"🤖 Assistant Response:\n\n{bot_response}"
        
        # Send modified response to new group
        await context.bot.send_message(
            chat_id=new_group_id,
            text=modified_response,
            reply_to_message_id=original_msg_id
        )
        
        logger.info(f"Sent modified response back to new group")
        
        # Clean up mapping
        del message_map[replied_to_msg_id]
        
    except Exception as e:
        logger.error(f"Error sending response: {e}")


async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route messages based on which group they come from"""
    if not update.effective_chat:
        return
    
    chat_id = update.effective_chat.id
    
    if chat_id == EXISTING_GROUP_ID:
        await handle_existing_group_message(update, context)
    else:
        # Assume it's from a new group where users interact
        await handle_new_group_message(update, context)


def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    # Add message handler
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_all_messages
    ))
    
    # Start the bot
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
