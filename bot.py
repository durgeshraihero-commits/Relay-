"""
Premium Information Bot - Professional Edition
Smart result detection, premium UI, professional messaging
"""

import os
import sys
import re
import json
import time
import uuid
import logging
import asyncio
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.channels import GetParticipantRequest
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

# ============ CONFIGURATION ============

PORT = int(os.getenv("PORT", "10000"))
BOT_SESSION_FILE = "bot_session.session"
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

USER_SESSION_FILE = "relay_session.session"
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DBNAME = "tg_bot_db"

WEBSITE = "https://relay-wzlz.onrender.com"
BOT_FOOTER = "🔐 Powered by <b>darkboxes_bot</b>\n📱 Dev: @darkboxesAdmin"

SEARCH_TIMEOUT_PER_GROUP = 15
WAIT_FOR_RESULT_TIMEOUT = 30
FETCH_WAIT_TIME = 2

REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2

# ============ LOGGING ============

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger("premium_bot")

# ============ VALIDATION ============

def validate_config():
    errors = []
    if BOT_API_ID == 0:
        errors.append("❌ API_ID not set")
    if not BOT_API_HASH:
        errors.append("❌ API_HASH not set")
    if not BOT_TOKEN:
        errors.append("❌ BOT_TOKEN not set")
    if ADMIN_USER_ID == 0:
        errors.append("❌ ADMIN_USER_ID not set")
    if not MONGODB_URI:
        errors.append("❌ MONGODB_URI not set")
    
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(error)
        return False
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

# ============ GROUPS CONFIG ============

DESTINATION_GROUPS = [
    {"name": "Main Group", "identifier": -1003596998816, "entity": None, "order": 1},
    {"name": "Backup Group 2", "identifier": "darkboxesv3", "entity": None, "order": 2},
    {"name": "Backup Group 3", "identifier": "nex_chats", "entity": None, "order": 3}
]

# ============ SEARCH COMMANDS ============

SEARCH_COMMANDS = {
    "phone": {"name": "📱 Phone Number", "command": "/num", "desc": "Get info from phone number"},
    "vnum": {"name": "🚗 Vehicle Number", "command": "/vnum", "desc": "Get owner from vehicle"},
    "tg": {"name": "📲 Telegram User", "command": "/tg", "desc": "Get phone from Telegram"},
    "imei": {"name": "📱 IMEI Number", "command": "/imei", "desc": "Get device info from IMEI"},
    "gst": {"name": "🏢 GST Number", "command": "/gst", "desc": "Get business info from GST"},
    "aadhar": {"name": "🆔 Aadhar Number", "command": "/aadhar", "desc": "Get info from Aadhar"},
    "email": {"name": "📧 Email Address", "command": "/email", "desc": "Search email details"},
    "upi": {"name": "💳 UPI ID", "command": "/upiinfo", "desc": "Get info from UPI"},
    "insta": {"name": "📷 Instagram User", "command": "/insta", "desc": "Search Instagram profile"},
    "family": {"name": "👨‍👩‍👧‍👦 Family Info", "command": "/familyinfo", "desc": "Get family members info"},
}

PLANS = {
    "plan_5": {"name": "🔍 5 Searches", "searches": 5, "price": 100, "days": None, "desc": "Perfect for trying"},
    "plan_15": {"name": "🔎 15 Searches", "searches": 15, "price": 200, "days": None, "desc": "Great value"},
    "plan_month": {"name": "⚡ Unlimited (30 Days)", "searches": -1, "price": 1000, "days": 30, "desc": "Best deal"}
}

# ============ DATABASE ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
admins_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col, admins_col
    try:
        logger.info("🔌 Connecting to MongoDB...")
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        admins_col = db["admins"]
        
        users_col.create_index([("user_id", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])
        
        logger.info("✅ MongoDB connected")
        return True
    except ServerSelectionTimeoutError:
        logger.error("❌ MongoDB timeout - check URI")
        return False
    except Exception as e:
        logger.exception("MongoDB error: %s", e)
        return False

# ============ ADMIN FUNCTIONS ============

async def is_admin(user_id: int) -> bool:
    if user_id == ADMIN_USER_ID:
        return True
    try:
        admin = await asyncio.get_running_loop().run_in_executor(None, admins_col.find_one, {"user_id": user_id})
        return admin is not None
    except:
        return False

async def add_admin(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: admins_col.update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id, "added_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
        )
        return True
    except:
        return False

async def get_admin_stats() -> Dict:
    try:
        total_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {})
        total_searches = await asyncio.get_running_loop().run_in_executor(None, searches_col.count_documents, {})
        premium_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {"plan": {"\$ne": "free"}})
        approved_payments = await asyncio.get_running_loop().run_in_executor(None, payments_col.count_documents, {"status": "approved"})
        
        total_revenue = 0
        try:
            payments = await asyncio.get_running_loop().run_in_executor(None, lambda: list(payments_col.find({"status": "approved"})))
            total_revenue = sum(p.get('amount', 0) for p in payments)
        except:
            pass
        
        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "total_searches": total_searches,
            "approved_payments": approved_payments,
            "total_revenue": total_revenue
        }
    except:
        return {}

# ============ USER FUNCTIONS ============

async def get_user(user_id: int) -> Optional[Dict]:
    try:
        return await asyncio.get_running_loop().run_in_executor(None, users_col.find_one, {"user_id": user_id})
    except:
        return None

async def create_user(user_id: int, username: str = None, first_name: str = None) -> Optional[Dict]:
    try:
        referral_code = secrets.token_urlsafe(6).upper()
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "plan": "free",
            "searches_remaining": NEW_USER_CREDITS,
            "plan_expiry": None,
            "total_searches": 0,
            "banned": False,
            "referral_code": referral_code,
            "referred_by": None
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one({"user_id": user_id}, {"$setOnInsert": doc}, upsert=True)
        )
        return await get_user(user_id)
    except:
        return None

async def update_user_plan(user_id: int, plan: str, searches: int, days: int = None) -> bool:
    try:
        update_doc = {"plan": plan, "searches_remaining": searches}
        if days:
            update_doc["plan_expiry"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one({"user_id": user_id}, {"$set": update_doc})
        )
        return True
    except:
        return False

async def decrement_search(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": -1, "total_searches": 1}}
            )
        )
        return True
    except:
        return False

async def log_search(user_id: int, search_type: str, query: str) -> bool:
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(None, searches_col.insert_one, doc)
        return True
    except:
        return False

async def create_payment(user_id: int, plan: str, amount: int) -> Optional[str]:
    try:
        payment_id = uuid.uuid4().hex
        doc = {
            "payment_id": payment_id,
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await asyncio.get_running_loop().run_in_executor(None, payments_col.insert_one, doc)
        return payment_id
    except:
        return None

async def approve_payment(payment_id: str) -> bool:
    try:
        payment = await asyncio.get_running_loop().run_in_executor(None, payments_col.find_one, {"payment_id": payment_id})
        if not payment:
            return False
        
        plan_key = payment['plan']
        plan = PLANS[plan_key]
        user_id = payment['user_id']
        
        if plan['searches'] == -1:
            await update_user_plan(user_id, "premium", 999999, plan['days'])
        else:
            user_doc = await get_user(user_id)
            current = user_doc.get('searches_remaining', 0)
            await update_user_plan(user_id, "premium", current + plan['searches'])
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        
        try:
            await bot_client.send_message(
                user_id,
                f"✅ <b>Payment Approved!</b>\n\n"
                f"🎉 Welcome to <b>{plan['name']}</b>\n"
                f"Enjoy unlimited access!\n\n"
                f"{BOT_FOOTER}",
                parse_mode="html"
            )
        except:
            pass
        
        return True
    except:
        return False

# ============ TEXT PROCESSING ============

def is_processing_message(text: str) -> bool:
    if not text or len(text.strip()) < 15:
        return True
    keywords = ['processing', 'please wait', 'searching', 'fetching', 'loading', 'hold on', 'wait', 'trying', 'finding', 'checking']
    return any(k in text.lower() for k in keywords)

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    keywords = ['no info', 'not found', 'no data', 'no result', 'invalid', 'not available', 'error', 'failed', 'doesn\'t exist']
    return any(k in text.lower() for k in keywords)

def has_useful_data(text: str) -> bool:
    """Check if text contains useful data"""
    if not text or len(text.strip()) < 20:
        return False
    
    data_keywords = [
        'name', 'mobile', 'phone', 'address', 'email', 'number',
        'owner', 'father', 'mother', 'family', 'info', 'details',
        'city', 'state', 'country', 'date', 'registered', 'status',
        'username', 'user', 'profile', 'device', 'model', 'imei'
    ]
    
    return any(k in text.lower() for k in data_keywords)

def filter_links(text: str) -> str:
    if not text:
        return text
    patterns = [r'https?://[^\s]+', r'www\.[^\s]+', r't\.me/[^\s]+', r'tg://[^\s]+']
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text

def format_result(text: str, search_type: str) -> str:
    """Format result professionally"""
    if not text:
        return text
    
    cleaned = filter_links(text)
    
    # Add header
    header = f"<b>✅ Search Result - {SEARCH_COMMANDS.get(search_type, {}).get('name', 'Result')}</b>\n\n"
    
    # Add content
    content = f"<pre>{cleaned[:2000]}</pre>\n\n"
    
    # Add footer
    footer = f"<i>{BOT_FOOTER}</i>"
    
    return header + content + footer

# ============ STATE ============

user_states = {}
pending_searches = {}

# ============ CLIENTS ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)
user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH) if USE_USER_ACCOUNT else bot_client

# ============ ADVANCED CASCADING SEARCH ============

async def perform_cascading_search(search_type: str, query: str, user_id: int = None) -> Dict:
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "❌ Invalid search type"}
    
    command = SEARCH_COMMANDS[search_type]['command']
    message = f"{command} {query}"
    
    logger.info(f"🔍 Starting cascading search: {search_type} = {query}")
    
    for attempt, group_config in enumerate(sorted(DESTINATION_GROUPS, key=lambda x: x['order']), 1):
        group_entity = group_config.get('entity')
        if not group_entity:
            logger.warning(f"⚠️ Group {group_config['name']} not resolved")
            continue
        
        try:
            # Send search command
            sent_msg = await user_client.send_message(group_entity, message)
            logger.info(f"📤 [{attempt}/3] Sent to {group_config['name']}: {message}")
            
            # Create future for waiting
            future = asyncio.get_running_loop().create_future()
            search_id = f"{sent_msg.id}_{int(time.time() * 1000)}_{group_config['order']}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "message_id": sent_msg.id,
                "chat_entity": group_entity,
                "group_name": group_config['name'],
                "state": "waiting_for_response",
                "got_processing": False
            }
            
            try:
                # Wait for result with timeout
                result_text = await asyncio.wait_for(future, timeout=SEARCH_TIMEOUT_PER_GROUP)
                logger.info(f"✅ Got result from {group_config['name']}")
                
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                
                # Validate result
                if result_text and len(result_text.strip()) > 20 and has_useful_data(result_text) and not is_no_info_message(result_text):
                    formatted = format_result(result_text, search_type)
                    
                    if user_id:
                        await log_search(user_id, search_type, query)
                    
                    pending_searches.pop(search_id, None)
                    return {
                        "success": True,
                        "result": formatted,
                        "search_type": search_type,
                        "source": group_config['name']
                    }
                else:
                    logger.info(f"⚠️ Invalid result from {group_config['name']}, trying next...")
                    pending_searches.pop(search_id, None)
                    continue
            
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.info(f"⏱️ Timeout from {group_config['name']} ({SEARCH_TIMEOUT_PER_GROUP}s)")
                continue
        
        except Exception as e:
            logger.exception(f"Search error in {group_config['name']}: {e}")
            pending_searches.pop(search_id, None)
            continue
    
    return {"success": False, "error": "❌ No results found\n\nTry:\n• Different query\n• Check spelling\n• Try another search type"}

# ============ KEYBOARDS ============

def main_menu():
    """Professional main menu"""
    buttons = [
        [Button.inline(f"{cmd['name']}", f"search_{key}")] 
        for key, cmd in SEARCH_COMMANDS.items()
    ]
    
    buttons.extend([
        [Button.inline("👤 My Profile", "my_profile")],
        [Button.inline("💰 Premium Plans", "plans_menu")],
        [Button.inline("📞 Support", "support")],
    ])
    
    return buttons

def admin_menu():
    """Admin control panel"""
    return [
        [Button.inline("📊 Statistics", "admin_stats")],
        [Button.inline("💳 Payment Requests", "admin_payments")],
        [Button.inline("📋 Manage Users", "admin_users")],
        [Button.inline("🔙 Back to Main", "back_main")],
    ]

def plans_menu():
    """Premium plans display"""
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([Button.inline(f"{plan['name']} • ₹{plan['price']}", f"buy_{key}")])
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

# ============ HANDLERS ============

@bot_client.on(events.NewMessage(pattern=r'/start'))
async def start_handler(event):
    """Professional start handler"""
    user = await event.get_sender()
    user_id = user.id
    
    user_doc = await get_user(user_id)
    if not user_doc:
        await create_user(user_id, user.username, user.first_name)
    
    user_doc = await get_user(user_id)
    
    if user_doc and user_doc.get('banned'):
        await event.respond(
            "❌ <b>Access Denied</b>\n\n"
            "Your account has been suspended.\n"
            "Contact support for details.",
            parse_mode="html"
        )
        return
    
    admin_check = await is_admin(user_id)
    if admin_check:
        stats = await get_admin_stats()
        await event.respond(
            f"👮 <b>Admin Dashboard</b>\n\n"
            f"📊 <b>Statistics:</b>\n"
            f"└─ 👥 Users: <code>{stats.get('total_users', 0)}</code>\n"
            f"└─ 💎 Premium: <code>{stats.get('premium_users', 0)}</code>\n"
            f"└─ 📈 Searches: <code>{stats.get('total_searches', 0)}</code>\n"
            f"└─ 💰 Revenue: ₹<code>{stats.get('total_revenue', 0)}</code>\n\n"
            f"{BOT_FOOTER}",
            parse_mode="html",
            buttons=admin_menu()
        )
        return
    
    await event.respond(
        f"👋 <b>Welcome to Premium Info Bot!</b>\n\n"
        f"🚀 <b>Your Account Status:</b>\n"
        f"├─ Plan: <b>{user_doc.get('plan', 'free').upper()}</b>\n"
        f"├─ Credits: <code>{user_doc.get('searches_remaining', 0)}</code>\n"
        f"└─ Total Searches: <code>{user_doc.get('total_searches', 0)}</code>\n\n"
        f"📌 <b>Quick Start:</b>\n"
        f"Select a search type and enter your query to get instant results!\n\n"
        f"{BOT_FOOTER}",
        parse_mode="html",
        buttons=main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^admin_stats'))
async def admin_stats(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ Access Denied", alert=True)
        return
    
    stats = await get_admin_stats()
    await event.edit(
        f"📊 <b>Complete Statistics</b>\n\n"
        f"<b>Users:</b>\n"
        f"├─ Total: <code>{stats.get('total_users', 0)}</code>\n"
        f"└─ Premium: <code>{stats.get('premium_users', 0)}</code>\n\n"
        f"<b>Activity:</b>\n"
        f"├─ Total Searches: <code>{stats.get('total_searches', 0)}</code>\n"
        f"└─ Approved Payments: <code>{stats.get('approved_payments', 0)}</code>\n\n"
        f"<b>Revenue:</b>\n"
        f"└─ ₹<code>{stats.get('total_revenue', 0)}</code>",
        parse_mode="html",
        buttons=[[Button.inline("🔙 Back", "admin_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^admin_payments'))
async def admin_payments(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ Access Denied", alert=True)
        return
    
    try:
        pending = list(payments_col.find({"status": "pending"}).limit(10))
        
        if not pending:
            await event.edit(
                "✅ <b>No Pending Payments</b>\n\n"
                "All payments have been processed!",
                parse_mode="html",
                buttons=[[Button.inline("🔙 Back", "admin_menu")]]
            )
            return
        
        message = f"💳 <b>Pending Payments ({len(pending)})</b>\n\n"
        buttons = []
        
        for p in pending:
            plan = PLANS.get(p['plan'], {})
            message += f"<b>User ID:</b> <code>{p['user_id']}</code>\n"
            message += f"<b>Plan:</b> {plan.get('name', 'Unknown')}\n"
            message += f"<b>Amount:</b> ₹{p['amount']}\n"
            message += f"<b>ID:</b> <code>{p['payment_id'][:8]}</code>\n\n"
            
            buttons.append([
                Button.inline("✅ Approve", f"approve_{p['payment_id']}"),
                Button.inline("❌ Reject", f"reject_{p['payment_id']}")
            ])
        
        buttons.append([Button.inline("🔙 Back", "admin_menu")])
        await event.edit(message, parse_mode="html", buttons=buttons)
    except Exception as e:
        logger.error(f"Error: {e}")
        await event.answer("Error loading payments", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_handler(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    user_doc = await get_user(user_id)
    admin_check = await is_admin(user_id)
    
    if user_doc.get('banned'):
        await event.answer("❌ You are banned", alert=True)
        return
    
    if not admin_check and user_doc.get('searches_remaining', 0) <= 0:
        await event.edit(
            f"❌ <b>No Credits Available</b>\n\n"
            f"Your current credits: <code>0</code>\n\n"
            f"💰 <b>Upgrade Now:</b>\n"
            f"Get more credits with premium plans!",
            parse_mode="html",
            buttons=plans_menu()
        )
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    
    cmd = SEARCH_COMMANDS[search_type]
    await event.edit(
        f"🔍 <b>{cmd['name']}</b>\n\n"
        f"<i>{cmd['desc']}</i>\n\n"
        f"💬 Send your query below:\n\n"
        f"Example: <code>9876543210</code>\n\n"
        f"⏱️ This usually takes 10-30 seconds",
        parse_mode="html",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_handler(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_')[1]
    
    if plan_key not in PLANS:
        await event.answer("Invalid plan", alert=True)
        return
    
    plan = PLANS[plan_key]
    payment_id = await create_payment(user_id, plan_key, plan['price'])
    
    if not payment_id:
        await event.answer("Error creating payment", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    if plan['searches'] == -1:
        benefit = f"⚡ Unlimited searches for <b>{plan['days']} days</b>"
    else:
        benefit = f"🔍 <b>{plan['searches']} searches</b>"
    
    await event.edit(
        f"💳 <b>Secure Payment</b>\n\n"
        f"📦 <b>Plan:</b> {plan['name']}\n"
        f"💰 <b>Amount:</b> ₹{plan['price']}\n"
        f"✨ <b>Benefit:</b> {benefit}\n\n"
        f"📋 <b>Payment ID:</b> <code>{payment_id}</code>\n\n"
        f"👇 <b>Steps:</b>\n"
        f"1. Scan the QR code below\n"
        f"2. Send payment\n"
        f"3. Take screenshot of receipt\n"
        f"4. Send it here\n\n"
        f"We'll verify and activate your plan!",
        parse_mode="html",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^my_profile'))
async def my_profile(event):
    user_doc = await get_user(event.sender_id)
    admin_check = await is_admin(event.sender_id)
    
    plan_status = {
        "free": "🆓 Free Account",
        "premium": "💎 Premium Member",
        "lifetime": "👑 Lifetime Access"
    }
    
    await event.edit(
        f"👤 <b>My Profile</b>\n\n"
        f"<b>Account Details:</b>\n"
        f"├─ Name: {user_doc.get('first_name', 'N/A')}\n"
        f"├─ ID: <code>{event.sender_id}</code>\n"
        f"├─ Status: {plan_status.get(user_doc.get('plan', 'free'))}\n"
        f"└─ Joined: {user_doc.get('joined_at', 'N/A')[:10]}\n\n"
        f"<b>Activity:</b>\n"
        f"├─ Credits: <code>{user_doc.get('searches_remaining', 0)}</code>\n"
        f"├─ Total Searches: <code>{user_doc.get('total_searches', 0)}</code>\n"
        f"└─ {'👮 Admin' if admin_check else '📱 Regular User'}\n\n"
        f"{BOT_FOOTER}",
        parse_mode="html",
        buttons=[[Button.inline("🔙 Back", "back_main")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^plans_menu'))
async def plans_menu_handler(event):
    message = (
        f"💰 <b>Premium Plans</b>\n\n"
        f"Upgrade now and get instant access!\n\n"
    )
    
    for key, plan in PLANS.items():
        if plan['searches'] == -1:
            searches = f"⚡ Unlimited ({plan['days']} days)"
        else:
            searches = f"🔍 {plan['searches']} Searches"
        
        message += f"<b>{plan['name']}</b>\n"
        message += f"├─ {searches}\n"
        message += f"├─ ₹{plan['price']}\n"
        message += f"└─ {plan['desc']}\n\n"
    
    message += f"💳 <b>All plans include:</b>\n"
    message += f"✓ Instant results\n"
    message += f"✓ 24/7 support\n"
    message += f"✓ Unlimited updates\n"
    
    await event.edit(message, parse_mode="html", buttons=plans_menu())

@bot_client.on(events.CallbackQuery(pattern='^support'))
async def support_handler(event):
    await event.edit(
        f"📞 <b>Support & Help</b>\n\n"
        f"<b>Need assistance?</b>\n\n"
        f"💬 Contact: @darkboxesAdmin\n"
        f"🌐 Website: https://relay-wzlz.onrender.com\n"
        f"📧 Email: support@darkboxes.com\n\n"
        f"<b>Common Issues:</b>\n"
        f"❓ No results?\n"
        f"└─ Try different spelling or format\n\n"
        f"❓ Payment problems?\n"
        f"└─ Contact admin for manual verification\n\n"
        f"❓ Account suspended?\n"
        f"└─ Reach out to support team\n\n"
        f"<b>Response Time:</b> Within 1-2 hours",
        parse_mode="html",
        buttons=[[Button.inline("🔙 Back", "back_main")]]
    )

@bot_client.on(events.CallbackQuery(pattern=r'^approve_(.+)'))
async def approve_payment(event):
    if not await is_admin(event.sender_id):
        return
    
    payment_id = event.data.decode().split('_')[1]
    if await approve_payment(payment_id):
        await event.answer("✅ Payment approved!", alert=True)
    else:
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^reject_(.+)'))
async def reject_payment(event):
    if not await is_admin(event.sender_id):
        return
    
    payment_id = event.data.decode().split('_')[1]
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "rejected"}}
            )
        )
        await event.answer("❌ Payment rejected", alert=True)
    except:
        pass

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_handler(event):
    user_states.pop(event.sender_id, None)
    await event.edit(
        "❌ <b>Action Cancelled</b>\n\n"
        "Back to main menu",
        parse_mode="html",
        buttons=main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main(event):
    user_doc = await get_user(event.sender_id)
    await event.edit(
        f"👋 <b>Welcome Back!</b>\n\n"
        f"🚀 <b>Your Stats:</b>\n"
        f"├─ Plan: <b>{user_doc.get('plan', 'free').upper()}</b>\n"
        f"├─ Credits: <code>{user_doc.get('searches_remaining', 0)}</code>\n"
        f"└─ Searches Done: <code>{user_doc.get('total_searches', 0)}</code>\n\n"
        f"What would you like to search?",
        parse_mode="html",
        buttons=main_menu()
    )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        if not query:
            await event.respond("❌ Please send a valid query")
            return
        
        # Show searching animation
        status = await event.respond(
            f"🔍 <b>Searching...</b>\n\n"
            f"⏳ Please wait while we fetch data from our servers...\n\n"
            f"This may take up to 30 seconds",
            parse_mode="html"
        )
        
        result = await perform_cascading_search(search_type, query, user_id)
        
        try:
            await status.delete()
        except:
            pass
        
        if result['success']:
            await event.respond(result['result'], parse_mode="html")
            
            admin_check = await is_admin(user_id)
            if not admin_check:
                await decrement_search(user_id)
                user_doc = await get_user(user_id)
                
                if user_doc.get('searches_remaining', 0) <= 3:
                    await event.respond(
                        f"⚠️ <b>Low Credits Alert</b>\n\n"
                        f"You have only <code>{user_doc.get('searches_remaining', 0)}</code> credits left!\n\n"
                        f"💰 Upgrade to premium for unlimited access",
                        parse_mode="html"
                    )
        else:
            await event.respond(
                f"{result.get('error', '❌ Error')}\n\n"
                f"💡 <b>Tips:</b>\n"
                f"• Check your spelling\n"
                f"• Try a different format\n"
                f"• Use correct country codes",
                parse_mode="html"
            )
        
        user_states.pop(user_id, None)

# ============ GROUP HANDLER ============

@user_client.on(events.NewMessage())
async def handle_group_replies(event):
    message = event.message
    now = time.time()
    
    matched_search = None
    matched_key = None
    
    # Find matching search - wait for direct replies only
    for search_id, info in list(pending_searches.items()):
        if info['future'].done():
            continue
        if now - info.get('timestamp', now) > SEARCH_TIMEOUT_PER_GROUP * 5:
            continue
        
        # Check if this is a direct reply to our search message
        if message.reply_to and message.reply_to.reply_to_msg_id == info.get('message_id'):
            matched_search = info
            matched_key = search_id
            break
    
    if not matched_search:
        return
    
    text = message.text or message.raw_text
    if not text:
        return
    
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    # If processing message, wait for next reply
    if is_processing_message(text):
        logger.info(f"⏳ Got processing message: {text[:50]}")
        matched_search['state'] = 'got_processing'
        matched_search['got_processing'] = True
        return  # Don't resolve future, wait for actual result
    
    # If no info message, try next group
    if is_no_info_message(text):
        logger.info(f"❌ Got no-info message")
        if not matched_search['future'].done():
            matched_search['future'].set_exception(TimeoutError("No info"))
            pending_searches.pop(matched_key, None)
        return
    
    # If we have useful data, send it
    if has_useful_data(text) and len(text.strip()) > 20:
        logger.info(f"✅ Got useful data: {len(text)} chars")
        if not matched_search['future'].done():
            cleaned = filter_links(text)
            matched_search['future'].set_result(cleaned)
            pending_searches.pop(matched_key, None)
            return
    
    # For other cases, resolve with the result
    if not matched_search['future'].done() and len(text.strip()) > 15:
        cleaned = filter_links(text)
        matched_search['future'].set_result(cleaned)
        pending_searches.pop(matched_key, None)

# ============ CLEANUP ============

async def cleanup():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        
        for sid in list(pending_searches.keys()):
            info = pending_searches[sid]
            age = now - info.get('timestamp', now)
            
            if age > SEARCH_TIMEOUT_PER_GROUP * 5:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError())
                    except:
                        pass
                pending_searches.pop(sid, None)

# ============ WEB SERVER ============

async def start_web():
    app = web.Application()
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server on port {PORT}")

# ============ MAIN ============

async def start_bot():
    try:
        logger.info("🤖 Starting bot...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot connected")
        
        me = await bot_client.get_me()
        logger.info(f"Bot: @{me.username}")
        
        if USE_USER_ACCOUNT:
            if not user_client.is_connected():
                await user_client.connect()
            if not await user_client.is_user_authorized():
                raise RuntimeError("User not authorized")
            logger.info("✅ User account ready")

        logger.info("📡 Resolving groups...")
        for group in DESTINATION_GROUPS:
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ {group['name']} (Order {group['order']})")
            except Exception as e:
                logger.warning(f"❌ {group['name']}: {e}")

        if not init_mongo():
            return
        
        await add_admin(ADMIN_USER_ID)
        
        asyncio.create_task(cleanup())
        asyncio.create_task(start_web())

        logger.info("=" * 70)
        logger.info("🚀 PREMIUM BOT FULLY OPERATIONAL!")
        logger.info("=" * 70)

        await asyncio.Event().wait()

    except Exception as e:
        logger.exception("Fatal: %s", e)


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Stopped")
    except Exception as e:
        logger.exception("Crash: %s", e)
