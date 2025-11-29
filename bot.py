import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

NEW_BOT_TOKEN = "8224146762:AAEJpeFIHmMeG2fjUn7ccMBiupA9Cxuewew"
EXISTING_GROUP_ID = -1003275777221

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

message_map = {}

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from users"""
    try:
        if update.effective_chat.id == EXISTING_GROUP_ID:
            return
            
        user_message = update.message.text.strip()
        original_chat_id = update.effective_chat.id
        original_msg_id = update.message.message_id
        
        logger.info(f"📩 User: {user_message}")
        
        # Send to existing group
        sent_msg = await context.bot.send_message(
            chat_id=EXISTING_GROUP_ID,
            text=user_message
        )
        
        message_map[sent_msg.message_id] = (original_chat_id, original_msg_id)
        
        await update.message.reply_text("✅ Sent! Waiting for response...", reply_to_message_id=original_msg_id)
        logger.info(f"✅ Message sent to group")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")

async def handle_group_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle responses"""
    try:
        if (update.effective_chat.id == EXISTING_GROUP_ID and 
            update.message.reply_to_message):
            
            replied_msg_id = update.message.reply_to_message.message_id
            
            if replied_msg_id in message_map:
                chat_id, msg_id = message_map[replied_msg_id]
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🤖 Response:\n\n{update.message.text}",
                    reply_to_message_id=msg_id
                )
                
                del message_map[replied_msg_id]
                logger.info("✅ Response forwarded!")
                
    except Exception as e:
        logger.error(f"❌ Response error: {e}")

def main():
    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.Chat(EXISTING_GROUP_ID), 
        handle_user_message
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(EXISTING_GROUP_ID),
        handle_group_response
    ))
    
    logger.info("🚀 Simple Bot Started!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
