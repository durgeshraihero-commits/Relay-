import os
import re
import json
import time
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta

from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from pymongo import MongoClient

# ============ Config ============

PORT = int(os.getenv("PORT", "10000"))

SESSION_FILE = os.getenv("SESSION_FILE", "bot_session.session")
TELETHON_API_ID = int(os.getenv("API_ID", "0"))
TELETHON_API_HASH = os.getenv("API_HASH", "").strip()  # Strip whitespace
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()  # Strip whitespace

# Validate required configs
if TELETHON_API_ID == 0 or not TELETHON_API_HASH:
    logger.error("=" * 60)
    logger.error("CONFIGURATION ERROR!")
    logger.error("=" * 60)
    logger.error("API_ID and API_HASH must be set!")
    logger.error("Current API_ID: %s", TELETHON_API_ID)
    logger.error("Current API_HASH: %s", TELETHON_API_HASH[:10] + "..." if TELETHON_API_HASH else "NOT SET")
    logger.error("")
    logger.error("To get these credentials:")
    logger.error("1. Go to https://my.telegram.org")
    logger.error("2. Log in with your phone number")
    logger.error("3. Click 'API development tools'")
    logger.error("4. Create an app and copy api_id and api_hash")
    logger.error("=" * 60)
    raise ValueError("Missing API_ID or API_HASH")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN must be set! Get it from @BotFather")
    raise ValueError("Missing BOT_TOKEN")

logger.info("=" * 60)
logger.info("Configuration Check:")
logger.info("API_ID: %s", TELETHON_API_ID)
logger.info("API_HASH: %s", TELETHON_API_HASH[:10] + "..." if len(TELETHON_API_HASH) > 10 else "TOO SHORT")
logger.info("BOT_TOKEN: %s", BOT_TOKEN[:10] + "..." if len(BOT_TOKEN) > 10 else "TOO SHORT")
logger.info("ADMIN_USER_ID: %s", ADMIN_USER_ID)
logger.info("DESTINATION_GROUP: %s", DESTINATION_GROUP)
logger.info("=" * 60)

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))  # Your Telegram user ID
DESTINATION_GROUP = int(os.getenv("DESTINATION_GROUP", "-1003585142645"))  # Where to forward commands (use channel ID)
MANDATORY_CHANNEL = os.getenv("MANDATORY_CHANNEL", "@yourchannel")  # Channel users must join

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")

PAYMENT_QR_CODE = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")  # Your payment QR code URL

FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))
REPLY_TIMEOUT = int(os.getenv("REPLY_TIMEOUT", "30"))

# ============ Logging ============

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("premium_bot")

# ============ MongoDB ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        
        users_col.create_index([("user_id", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])
        searches_col.create_index([("user_id", 1)])
        
        logger.info("MongoDB connected successfully")
    except Exception as e:
        logger.exception("MongoDB connection failed: %s", e)
        raise

# ============ User Management ============

async def get_user(user_id: int):
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"user_id": user_id}
        )
    except Exception as e:
        logger.exception("Error fetching user: %s", e)
        return None

async def create_or_update_user(user_id: int, username: str = None, first_name: str = None):
    try:
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "plan": "free",
            "searches_remaining": 0,
            "plan_expiry": None,
            "total_searches": 0,
            "channel_joined": False
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$setOnInsert": doc},
                upsert=True
            )
        )
        return await get_user(user_id)
    except Exception as e:
        logger.exception("Error creating user: %s", e)
        return None

async def update_user_plan(user_id: int, plan: str, searches: int, days: int = None):
    try:
        update_doc = {
            "plan": plan,
            "searches_remaining": searches
        }
        if days:
            update_doc["plan_expiry"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        else:
            update_doc["plan_expiry"] = None
            
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$set": update_doc}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error updating user plan: %s", e)
        return False

async def decrement_search(user_id: int):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": -1, "total_searches": 1}}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error decrementing search: %s", e)
        return False

async def log_search(user_id: int, search_type: str, query: str, result: str):
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "result": result[:500],  # Store first 500 chars
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(
            None, searches_col.insert_one, doc
        )
    except Exception as e:
        logger.exception("Error logging search: %s", e)

async def create_payment_request(user_id: int, plan: str, amount: int):
    try:
        doc = {
            "payment_id": uuid.uuid4().hex,
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_file_id": None,
            "approved_at": None
        }
        result = await asyncio.get_running_loop().run_in_executor(
            None, payments_col.insert_one, doc
        )
        return doc["payment_id"]
    except Exception as e:
        logger.exception("Error creating payment: %s", e)
        return None

async def update_payment_screenshot(payment_id: str, file_id: str):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"screenshot_file_id": file_id, "screenshot_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error updating payment screenshot: %s", e)
        return False

# ============ Text Cleaning ============

def filter_links_and_usernames(text: str):
    if not text:
        return text
    
    patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r't\.me/[^\s]+',
        r'[a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*',
        r'@[\w]{2,32}',
        r'\b[a-zA-Z0-9_]{5,}\b(?=\s|$)'  # Remove standalone usernames
    ]
    
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    
    # Remove promotional lines
    lines = cleaned.splitlines()
    filtered_lines = []
    promotional = ['use these commands', 'join our', 'visit our', '💬 use', 'commands in']
    
    for line in lines:
        l = line.strip()
        if not l or any(k in l.lower() for k in promotional):
            continue
        filtered_lines.append(line)
    
    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    
    return cleaned

# ============ Command Mapping ============

SEARCH_COMMANDS = {
    "phone": {"cmd": "/num", "name": "Phone Number Info"},
    "family": {"cmd": "/familyinfo", "name": "Family Info"},
    "aadhar": {"cmd": "/aadhar", "name": "Aadhar Info"},
    "vehicle": {"cmd": "/vnum", "name": "Vehicle to Phone"},
    "upi": {"cmd": "/upi", "name": "UPI Info"},
    "fampay": {"cmd": "/fampay", "name": "Fampay Info"},
    "email": {"cmd": "/email", "name": "Email Info"},
    "telegram": {"cmd": "/tg", "name": "Telegram to Phone"},
    "imei": {"cmd": "/imei", "name": "IMEI Info"},
    "pak": {"cmd": "/pak", "name": "Pakistan Info"},
    "gst": {"cmd": "/gst", "name": "GST Info"}
}

PLANS = {
    "plan_5": {"searches": 5, "price": 100, "name": "5 Searches", "days": None},
    "plan_15": {"searches": 15, "price": 200, "name": "15 Searches", "days": None},
    "plan_week": {"searches": -1, "price": 500, "name": "Unlimited (7 Days)", "days": 7}
}

# ============ Bot State ============

user_states = {}
pending_searches = {}

# ============ Telethon Client ============

client = TelegramClient(SESSION_FILE, TELETHON_API_ID, TELETHON_API_HASH)

async def check_channel_membership(user_id: int):
    try:
        participant = await client.get_permissions(MANDATORY_CHANNEL, user_id)
        return participant is not None
    except Exception as e:
        logger.exception("Error checking channel membership: %s", e)
        return False

# ============ Keyboard Menus ============

def get_main_menu():
    buttons = []
    row = []
    for key, info in SEARCH_COMMANDS.items():
        row.append(Button.inline(info["name"], f"search_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return buttons

def get_plans_menu():
    buttons = []
    for plan_key, plan_info in PLANS.items():
        buttons.append([Button.inline(
            f"{plan_info['name']} - ₹{plan_info['price']}", 
            f"buy_{plan_key}"
        )])
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

def get_payment_approval_buttons(payment_id: str, user_id: int):
    return [
        [
            Button.inline("✅ Approve", f"approve_{payment_id}_{user_id}"),
            Button.inline("❌ Reject", f"reject_{payment_id}_{user_id}")
        ]
    ]

# ============ Bot Event Handlers ============

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    user_id = user.id
    
    await create_or_update_user(user_id, user.username, user.first_name)
    
    # Check if user is admin
    if user_id == ADMIN_USER_ID:
        await event.respond(
            f"👋 Welcome Admin!\n\n"
            f"You have full access to all features.\n"
            f"Use the menu below to perform searches:",
            buttons=get_main_menu()
        )
        return
    
    # Check channel membership
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.respond(
            f"👋 Welcome to Premium Info Bot!\n\n"
            f"To use this bot, you must first join our channel:\n"
            f"{MANDATORY_CHANNEL}\n\n"
            f"After joining, click /start again.",
            buttons=[[Button.url("Join Channel", f"https://t.me/{MANDATORY_CHANNEL.replace('@', '')}")]]
        )
        return
    
    # Update channel joined status
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    user_doc = await get_user(user_id)
    
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select a search type below:",
        buttons=get_main_menu()
    )

@client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    # Check if admin
    if user_id == ADMIN_USER_ID:
        user_states[user_id] = {"action": "awaiting_input", "type": search_type}
        await event.edit(
            f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
            f"Please send the {search_type} to search:"
        )
        return
    
    # Check user plan
    user_doc = await get_user(user_id)
    
    if not user_doc:
        await event.answer("❌ Error: User not found", alert=True)
        return
    
    # Check if user has searches remaining
    searches_remaining = user_doc.get('searches_remaining', 0)
    plan = user_doc.get('plan', 'free')
    plan_expiry = user_doc.get('plan_expiry')
    
    # Check if unlimited plan expired
    if plan == 'unlimited' and plan_expiry:
        expiry_dt = datetime.fromisoformat(plan_expiry)
        if expiry_dt < datetime.now(timezone.utc):
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"plan": "free", "searches_remaining": 0}}
                )
            )
            searches_remaining = 0
    
    if searches_remaining <= 0 and plan != 'unlimited':
        await event.edit(
            "❌ Access Not Granted\n\n"
            "You must buy a premium pack to use this bot.\n\n"
            "Select a plan below:",
            buttons=get_plans_menu()
        )
        return
    
    # User has access
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    await event.edit(
        f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
        f"Searches Remaining: {searches_remaining if searches_remaining > 0 else 'Unlimited'}\n\n"
        f"Please send the {search_type} to search:"
    )

@client.on(events.CallbackQuery(pattern=r'^buy_(.+)$'))
async def buy_plan_callback(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_', 1)[1]
    
    if plan_key not in PLANS:
        await event.answer("❌ Invalid plan", alert=True)
        return
    
    plan_info = PLANS[plan_key]
    payment_id = await create_payment_request(user_id, plan_key, plan_info['price'])
    
    if not payment_id:
        await event.answer("❌ Error creating payment request", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    # Notify admin
    try:
        user = await event.get_sender()
        await client.send_message(
            ADMIN_USER_ID,
            f"💰 New Payment Request\n\n"
            f"User: {user.first_name} (@{user.username or 'N/A'})\n"
            f"User ID: {user_id}\n"
            f"Plan: {plan_info['name']}\n"
            f"Amount: ₹{plan_info['price']}\n"
            f"Payment ID: {payment_id}\n\n"
            f"Waiting for payment screenshot..."
        )
    except Exception as e:
        logger.exception("Error notifying admin: %s", e)
    
    await event.edit(
        f"💳 Payment Required\n\n"
        f"Plan: {plan_info['name']}\n"
        f"Amount: ₹{plan_info['price']}\n\n"
        f"Please scan the QR code below and send the payment screenshot:\n\n"
        f"Payment ID: `{payment_id}`",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )
    
    # Send QR code
    try:
        await client.send_file(event.sender_id, PAYMENT_QR_CODE, caption="Scan to pay")
    except Exception as e:
        logger.exception("Error sending QR code: %s", e)
        await event.respond("Please pay to the UPI ID and send screenshot.")

@client.on(events.CallbackQuery(pattern=r'^approve_(.+)_(.+)$'))
async def approve_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    # Get payment details
    payment = await asyncio.get_running_loop().run_in_executor(
        None, payments_col.find_one, {"payment_id": payment_id}
    )
    
    if not payment:
        await event.answer("❌ Payment not found", alert=True)
        return
    
    plan_key = payment['plan']
    plan_info = PLANS[plan_key]
    
    # Update user plan
    if plan_info['searches'] == -1:
        await update_user_plan(target_user_id, "unlimited", 999999, plan_info['days'])
    else:
        user_doc = await get_user(target_user_id)
        current_searches = user_doc.get('searches_remaining', 0)
        await update_user_plan(target_user_id, "paid", current_searches + plan_info['searches'])
    
    # Update payment status
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: payments_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}}
        )
    )
    
    await event.edit(
        f"✅ Payment Approved\n\n"
        f"Payment ID: {payment_id}\n"
        f"User ID: {target_user_id}\n"
        f"Plan: {plan_info['name']}"
    )
    
    # Notify user
    try:
        await client.send_message(
            target_user_id,
            f"✅ Payment Approved!\n\n"
            f"Your {plan_info['name']} plan has been activated.\n"
            f"Use /start to begin searching.",
            buttons=[[Button.inline("🚀 Start Searching", "start")]]
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@client.on(events.CallbackQuery(pattern=r'^reject_(.+)_(.+)$'))
async def reject_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    # Update payment status
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: payments_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
        )
    )
    
    await event.edit(f"❌ Payment Rejected\n\nPayment ID: {payment_id}")
    
    # Notify user
    try:
        await client.send_message(
            target_user_id,
            "❌ Payment Rejected\n\n"
            "Your payment was not approved. Please contact support or try again."
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@client.on(events.CallbackQuery(pattern='^cancel$'))
async def cancel_callback(event):
    user_id = event.sender_id
    user_states.pop(user_id, None)
    await event.edit(
        "❌ Cancelled\n\nUse /start to begin again.",
        buttons=None
    )

@client.on(events.CallbackQuery(pattern='^start$'))
async def start_button_callback(event):
    await start_handler(event)

@client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    # Handle payment screenshot
    if state.get('action') == 'awaiting_payment':
        if not event.photo:
            await event.respond("❌ Please send a screenshot image.")
            return
        
        payment_id = state['payment_id']
        plan_key = state['plan']
        plan_info = PLANS[plan_key]
        
        # Save screenshot
        file = await event.download_media(bytes)
        
        # Update payment with screenshot
        await update_payment_screenshot(payment_id, event.message.id)
        
        # Forward to admin
        try:
            user = await event.get_sender()
            await client.send_file(
                ADMIN_USER_ID,
                event.photo,
                caption=f"💰 Payment Screenshot Received\n\n"
                        f"User: {user.first_name} (@{user.username or 'N/A'})\n"
                        f"User ID: {user_id}\n"
                        f"Plan: {plan_info['name']}\n"
                        f"Amount: ₹{plan_info['price']}\n"
                        f"Payment ID: {payment_id}",
                buttons=get_payment_approval_buttons(payment_id, user_id)
            )
        except Exception as e:
            logger.exception("Error forwarding to admin: %s", e)
        
        await event.respond(
            "✅ Payment screenshot received!\n\n"
            "Your payment is being reviewed. You'll be notified once approved."
        )
        
        user_states.pop(user_id, None)
        return
    
    # Handle search input
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        command_info = SEARCH_COMMANDS[search_type]
        command = f"{command_info['cmd']} {query}"
        
        # Send "fetching" message
        status_msg = await event.respond("⏳ Fetching information... Please wait.")
        
        try:
            # Forward to destination group
            forwarded = await client.send_message(DESTINATION_GROUP, command)
            
            # Store pending search
            future = asyncio.get_running_loop().create_future()
            pending_searches[forwarded.id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "original_msg": event.message.id
            }
            
            # Wait for response
            try:
                result = await asyncio.wait_for(future, timeout=REPLY_TIMEOUT)
                
                # Clean result
                cleaned = filter_links_and_usernames(result)
                
                if not cleaned.strip():
                    cleaned = "❌ No results found or data was filtered."
                
                # Delete status message
                await status_msg.delete()
                
                # Send result
                await event.respond(f"✅ Result:\n\n{cleaned}")
                
                # Decrement searches (if not admin and not unlimited)
                if user_id != ADMIN_USER_ID:
                    user_doc = await get_user(user_id)
                    if user_doc.get('plan') != 'unlimited':
                        await decrement_search(user_id)
                
                # Log search
                await log_search(user_id, search_type, query, cleaned)
                
            except asyncio.TimeoutError:
                await status_msg.delete()
                await event.respond("❌ Request timed out. Please try again.")
                
        except Exception as e:
            logger.exception("Error processing search: %s", e)
            await status_msg.delete()
            await event.respond("❌ An error occurred. Please try again.")
        
        user_states.pop(user_id, None)

@client.on(events.NewMessage(chats=DESTINATION_GROUP))
async def handle_destination_reply(event):
    message = event.message
    
    if not message.reply_to_msg_id:
        return
    
    search_info = pending_searches.get(message.reply_to_msg_id)
    
    if not search_info:
        return
    
    # Wait a bit for message to stabilize
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    # Get latest message
    try:
        latest = await client.get_messages(DESTINATION_GROUP, ids=message.id)
        if latest and latest.text:
            if not search_info['future'].done():
                search_info['future'].set_result(latest.text)
    except Exception as e:
        logger.exception("Error handling reply: %s", e)

# ============ Web Server ============

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# ============ Main ============

async def start_bot():
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Bot started successfully")
    await client.run_until_disconnected()

async def main():
    init_mongo()
    await asyncio.gather(
        start_web_server(),
        start_bot()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception:
        logger.exception("Fatal error")
