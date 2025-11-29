import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
import asyncio

# ===== CONFIGURATION =====
NEW_BOT_TOKEN = "8224146762:AAEJpeFIHmMeG2fjUn7ccMBiupA9Cxuewew"
EXISTING_GROUP_ID = -1003275777221

# ✅ YOUR API CREDENTIALS
API_ID = 36246931
API_HASH = "c9708f05badf286d69abcd0de7f44580"
PHONE_NUMBER = "+917667280752"  # ⚠️ Replace with your actual phone number

# ===== SETUP LOGGING =====
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== STORAGE =====
message_map = {}
telethon_client = None

# ===== TELETHON SETUP =====
async def setup_telethon():
    """Initialize Telethon client with user account"""
    global telethon_client
    
    logger.info("🔐 Starting Telethon client...")
    telethon_client = TelegramClient('user_session', API_ID, API_HASH)
    
    try:
        await telethon_client.start(phone=PHONE_NUMBER)
        
        # Check if we're authenticated
        me = await telethon_client.get_me()
        logger.info(f"✅ Telethon authenticated as: {me.first_name} (@{me.username})")
        return telethon_client
        
    except Exception as e:
        logger.error(f"❌ Telethon setup failed: {e}")
        return None

async def send_via_user_account(message_text):
    """Send message using user account (bypasses bot restrictions)"""
    try:
        if not telethon_client:
            logger.error("❌ Telethon client not available")
            return None
            
        # Send message as user (not as bot)
        sent_message = await telethon_client.send_message(
            entity=EXISTING_GROUP_ID,
            message=message_text
        )
        
        logger.info(f"✅ User account sent: {message_text}")
        return sent_message.id
        
    except Exception as e:
        logger.error(f"❌ Telethon send error: {e}")
        return None

# ===== BOT HANDLERS =====
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from users in new group"""
    try:
        # Ignore messages from existing group
        if update.effective_chat.id == EXISTING_GROUP_ID:
            return
            
        user_message = update.message.text.strip()
        original_chat_id = update.effective_chat.id
        original_msg_id = update.message.message_id
        
        logger.info(f"📩 User message: {user_message}")
        
        # Step 1: Send processing notification to user
        await update.message.reply_text(
            "🔄 Processing your request...",
            reply_to_message_id=original_msg_id
        )
        
        # Step 2: Send message via user account to trigger friend bot
        user_msg_id = await send_via_user_account(user_message)
        
        if user_msg_id:
            # Store mapping for response tracking
            message_map[user_msg_id] = (original_chat_id, original_msg_id)
            logger.info(f"✅ Friend bot triggered! Waiting for response...")
        else:
            await update.message.reply_text(
                "❌ Failed to process request. Please try again.",
                reply_to_message_id=original_msg_id
            )
        
    except Exception as e:
        logger.error(f"❌ Handler error: {e}")

async def handle_group_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle responses from friend bot in existing group"""
    try:
        if update.effective_chat.id != EXISTING_GROUP_ID:
            return
            
        message_text = update.message.text or ""
        sender_id = update.effective_user.id
        
        logger.info(f"📨 Message in group from {sender_id}: {message_text[:50]}...")
        
        # Check if this is a reply to our user-account message
        if update.message.reply_to_message:
            replied_msg_id = update.message.reply_to_message.message_id
            
            if replied_msg_id in message_map:
                original_chat_id, original_msg_id = message_map[replied_msg_id]
                
                logger.info(f"✅ Forwarding response to user...")
                
                # Send response back to user
                await context.bot.send_message(
                    chat_id=original_chat_id,
                    text=f"🤖 Response:\n\n{message_text}",
                    reply_to_message_id=original_msg_id
                )
                
                # Clean up
                del message_map[replied_msg_id]
                logger.info("✅ Response delivered to user!")
        else:
            # Also check if the message itself is from friend bot (direct response)
            # This handles cases where friend bot responds without replying
            for msg_id, (chat_id, orig_msg_id) in list(message_map.items()):
                # If we detect friend bot response and it matches recent messages
                if sender_id == 7574815513:  # Your friend bot ID
                    logger.info(f"✅ Direct response from friend bot detected!")
                    
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🤖 Response:\n\n{message_text}",
                        reply_to_message_id=orig_msg_id
                    )
                    
                    del message_map[msg_id]
                    logger.info("✅ Direct response delivered!")
                    break
                
    except Exception as e:
        logger.error(f"❌ Response handler error: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

# ===== MAIN =====
async def main():
    """Start the automated bot system"""
    logger.info("🚀 Starting Automated Bridge Bot...")
    logger.info("📱 Setting up user account connection...")
    
    # Setup Telethon (user account)
    client = await setup_telethon()
    if not client:
        logger.error("❌ Failed to setup Telethon. Please check API credentials.")
        return
    
    # Setup python-telegram-bot
    application = Application.builder().token(NEW_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.Chat(EXISTING_GROUP_ID), 
        handle_user_message
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(EXISTING_GROUP_ID),
        handle_group_response
    ))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot system started successfully!")
    logger.info("🎯 How it works:")
    logger.info("   1. User sends message in NEW group")
    logger.info("   2. Your personal account sends it to EXISTING group") 
    logger.info("   3. Friend bot responds to your personal account")
    logger.info("   4. Response is automatically forwarded to user")
    logger.info("=" * 50)
    
    # Run the bot
    await application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
