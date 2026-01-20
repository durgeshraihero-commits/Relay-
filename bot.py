"""
Advanced Premium Information Bot - Complete Production Version
Features: All commands, cascading group search, admin panel, API keys, profiles, referrals
"""

import os
import re
import json
import time
import uuid
import logging
import asyncio
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from aiohttp import web, ClientSession
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from telethon.tl.functions.channels import GetParticipantRequest
from pymongo import MongoClient

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
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://user:pass@cluster.mongodb.net/db?retryWrites=true&w=majority")
MONGODB_DBNAME = "tg_bot_db"

WEBSITE = "https://relay-wzlz.onrender.com"
BOT_FOOTER = "Powered by darkboxes_bot\nDeveloped by @darkboxesAdmin"

SEARCH_TIMEOUT_PER_GROUP = 20
MAX_GROUPS = 3
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

if BOT_API_ID == 0 or not BOT_API_HASH or not BOT_TOKEN:
    raise ValueError("Missing critical config")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

# ============ GROUPS CONFIG ============

DESTINATION_GROUPS = [
    {"name": "Main Group", "identifier": -1003596998816, "entity": None, "order": 1},
    {"name": "Backup Group 2", "identifier": "IntelXGroup", "entity": None, "order": 2},
    {"name": "Backup Group 3", "identifier": "nex_chats", "entity": None, "order": 3}
]

# ============ ALL SEARCH COMMANDS ============

SEARCH_COMMANDS = {
    "phone": {"name": "📱 Phone Number", "command": "/num", "desc": "Search phone number info"},
    "vnum": {"name": "🚗 Vehicle to Phone", "command": "/vnum", "desc": "Get owner from vehicle number"},
    "tg": {"name": "📲 Telegram to Phone", "command": "/tg", "desc": "Get phone from telegram username"},
    "imei": {"name": "📱 IMEI Info", "command": "/imei", "desc": "Search IMEI device info"},
    "gst": {"name": "🏢 GST Number", "command": "/gst", "desc": "Search GST details"},
    "aadhar": {"name": "🆔 Aadhar Number", "command": "/aadhar", "desc": "Search aadhar info"},
    "email": {"name": "📧 Email Info", "command": "/email", "desc": "Search email details"},
    "upi": {"name": "💳 UPI ID", "command": "/upiinfo", "desc": "Search UPI info"},
    "insta": {"name": "📷 Instagram", "command": "/insta", "desc": "Search instagram user"},
    "family": {"name": "👨‍👩‍👧‍👦 Family Info", "command": "/familyinfo", "desc": "Get family members"},
}

PLANS = {
    "plan_5": {"name": "5 Searches", "searches": 5, "price": 100, "days": None},
    "plan_15": {"name": "15 Searches", "searches": 15, "price": 200, "days": None},
    "plan_month": {"name": "Unlimited (30 Days)", "searches": -1, "price": 1000, "days": 30}
}

# ============ DATABASE ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
admins_col = None
channels_col = None
api_keys_col = None
referrals_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col, admins_col, channels_col, api_keys_col, referrals_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        admins_col = db["admins"]
        channels_col = db["channels"]
        api_keys_col = db["api_keys"]
        referrals_col = db["referrals"]
        
        users_col.create_index([("user_id", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])
        api_keys_col.create_index([("api_key", 1)], unique=True)
        
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.exception("MongoDB: %s", e)
        raise

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

async def get_all_admins() -> List[int]:
    try:
        admins = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(admins_col.find({}))
        )
        return [ADMIN_USER_ID] + [a['user_id'] for a in admins]
    except:
        return [ADMIN_USER_ID]

async def add_mandatory_channel(channel_identifier: str) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: channels_col.update_one(
                {"identifier": channel_identifier},
                {"$set": {"identifier": channel_identifier, "added_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
        )
        return True
    except:
        return False

async def get_mandatory_channels() -> List[str]:
    try:
        channels = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(channels_col.find({}))
        )
        return [c['identifier'] for c in channels]
    except:
        return []

async def ban_user(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$set": {"banned": True}}
            )
        )
        return True
    except:
        return False

async def unban_user(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$set": {"banned": False}}
            )
        )
        return True
    except:
        return False

async def get_admin_stats() -> Dict:
    try:
        total_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {})
        total_searches = await asyncio.get_running_loop().run_in_executor(None, searches_col.count_documents, {})
        active_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {"total_searches": {"\$gt": 0}})
        premium_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {"plan": {"\$ne": "free"}})
        
        approved_payments = await asyncio.get_running_loop().run_in_executor(None, payments_col.count_documents, {"status": "approved"})
        pending_payments = await asyncio.get_running_loop().run_in_executor(None, payments_col.count_documents, {"status": "pending"})
        
        total_revenue = 0
        try:
            payments = await asyncio.get_running_loop().run_in_executor(None, lambda: list(payments_col.find({"status": "approved"})))
            total_revenue = sum(p.get('amount', 0) for p in payments)
        except:
            pass
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "premium_users": premium_users,
            "total_searches": total_searches,
            "approved_payments": approved_payments,
            "pending_payments": pending_payments,
            "total_revenue": total_revenue
        }
    except:
        return {}

async def broadcast_message(message: str, exclude_id: int = None) -> Dict:
    try:
        users = await asyncio.get_running_loop().run_in_executor(None, lambda: list(users_col.find({"banned": {"\$ne": True}})))
        sent = 0
        failed = 0
        
        for user_doc in users:
            uid = user_doc.get('user_id')
            if exclude_id and uid == exclude_id:
                continue
            
            try:
                await bot_client.send_message(uid, f"{message}\n\n{BOT_FOOTER}")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                failed += 1
        
        return {"sent": sent, "failed": failed}
    except:
        return {"sent": 0, "failed": 0}

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
            "total_revenue": 0,
            "banned": False,
            "referral_code": referral_code,
            "referred_by": None,
            "referral_count": 0,
            "api_keys_count": 0
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

async def log_search(user_id: int, search_type: str, query: str, result_length: int) -> bool:
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "result_length": result_length,
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
            await bot_client.send_message(user_id, f"✅ Payment Approved!\n\nPlan: {plan['name']}\n\n{BOT_FOOTER}")
        except:
            pass
        
        return True
    except:
        return False

# ============ API KEY FUNCTIONS ============

async def create_api_key(user_id: int, name: str) -> Optional[str]:
    try:
        api_key = f"sk_{secrets.token_urlsafe(32)}"
        doc = {
            "api_key": api_key,
            "user_id": user_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "searches_used": 0,
            "active": True,
            "last_used": None
        }
        await asyncio.get_running_loop().run_in_executor(None, api_keys_col.insert_one, doc)
        return api_key
    except:
        return None

async def get_api_keys(user_id: int) -> List[Dict]:
    try:
        keys = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(api_keys_col.find({"user_id": user_id}))
        )
        return keys
    except:
        return []

async def get_api_key_info(api_key: str) -> Optional[Dict]:
    try:
        return await asyncio.get_running_loop().run_in_executor(None, api_keys_col.find_one, {"api_key": api_key})
    except:
        return None

# ============ REFERRAL FUNCTIONS ============

def generate_referral_link(user_id: int, referral_code: str) -> str:
    # Format: https://relay-wzlz.onrender.com/ref?code=ABC123
    return f"{WEBSITE}/ref?code={referral_code}"

async def apply_referral(user_id: int, referral_code: str) -> bool:
    try:
        referrer_doc = await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"referral_code": referral_code.upper()}
        )
        
        if not referrer_doc:
            return False
        
        referrer_id = referrer_doc['user_id']
        if referrer_id == user_id:
            return False
        
        user_doc = await get_user(user_id)
        if user_doc.get('referred_by'):
            return False
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"$set": {"referred_by": referrer_id}}
            )
        )
        
        return True
    except:
        return False

async def reward_referrer(user_id: int) -> bool:
    try:
        user_doc = await get_user(user_id)
        referrer_id = user_doc.get('referred_by')
        
        if not referrer_id:
            return False
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referrer_id},
                {"$inc": {"searches_remaining": REFERRAL_REWARD, "referral_count": 1}}
            )
        )
        
        try:
            await bot_client.send_message(
                referrer_id,
                f"🎉 Referral Reward!\n\nYou earned {REFERRAL_REWARD} credits!\n\n{BOT_FOOTER}"
            )
        except:
            pass
        
        return True
    except:
        return False

# ============ TEXT PROCESSING ============

def is_processing_message(text: str) -> bool:
    if not text or len(text.strip()) < 20:
        return True
    keywords = ['processing', 'please wait', 'fetching', 'loading', 'searching', 'hold on', 'wait', 'trying']
    return any(k in text.lower() for k in keywords)

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    keywords = ['no info', 'not found', 'no data', 'no result', 'invalid', 'not available', 'no record', 'error', 'failed']
    return any(k in text.lower() for k in keywords)

def filter_links(text: str) -> str:
    if not text:
        return text
    patterns = [r'https?://[^\s]+', r'www\.[^\s]+', r't\.me/[^\s]+', r'@[a-zA-Z0-9_]{3,}', r'tg://[^\s]+']
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text).strip()
    return text

def clean_file(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'https?://\S+|www\.\S+|@\w+|#\w+|tg://\S+', '', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines)

def add_footer(text: str) -> str:
    if not text:
        return text
    return f"{text}\n\n{'─' * 40}\n{BOT_FOOTER}"

# ============ STATE ============

user_states = {}
pending_searches = {}

# ============ CLIENTS ============

bot_client = TelegramClient("bot_session.session", BOT_API_ID, BOT_API_HASH)
user_client = TelegramClient("relay_session.session", USER_API_ID, USER_API_HASH) if USE_USER_ACCOUNT else bot_client

# ============ CASCADING SEARCH ============

async def perform_cascading_search(search_type: str, query: str, user_id: int = None) -> Dict:
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search type"}
    
    command = SEARCH_COMMANDS[search_type]['command']
    message = f"{command} {query}"
    
    logger.info(f"🔍 Search: {search_type} = {query}")
    
    for group_idx, group_config in enumerate(sorted(DESTINATION_GROUPS, key=lambda x: x['order'])):
        group_entity = group_config.get('entity')
        if not group_entity:
            logger.warning(f"⚠️ Group {group_config['name']} not resolved")
            continue
        
        try:
            # Send message to group
            sent_msg = await user_client.send_message(group_entity, message)
            logger.info(f"📤 Sent to {group_config['name']}: {message}")
            
            # Create future for result
            future = asyncio.get_running_loop().create_future()
            search_id = f"{sent_msg.id}_{int(time.time() * 1000)}_{group_idx}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "message_id": sent_msg.id,
                "chat_entity": group_entity,
                "group_name": group_config['name'],
                "timeout": SEARCH_TIMEOUT_PER_GROUP
            }
            
            try:
                # Wait for result with timeout
                result_text = await asyncio.wait_for(future, timeout=SEARCH_TIMEOUT_PER_GROUP)
                logger.info(f"✅ Got result from {group_config['name']}")
                
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                
                if result_text and len(result_text.strip()) > 20 and not is_processing_message(result_text) and not is_no_info_message(result_text):
                    cleaned = filter_links(result_text)
                    final = add_footer(cleaned)
                    
                    if user_id:
                        await log_search(user_id, search_type, query, len(cleaned))
                    
                    pending_searches.pop(search_id, None)
                    return {
                        "success": True,
                        "result": final,
                        "search_type": search_type,
                        "source": group_config['name']
                    }
                else:
                    pending_searches.pop(search_id, None)
                    logger.info(f"⚠️ Invalid result from {group_config['name']}, trying next group...")
                    continue
            
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.info(f"⏱️ Timeout from {group_config['name']} ({SEARCH_TIMEOUT_PER_GROUP}s), trying next...")
                continue
        
        except Exception as e:
            logger.exception(f"Search error in {group_config['name']}: {e}")
            pending_searches.pop(search_id, None)
            continue
    
    return {"success": False, "error": "No results from any group. Try another query."}

# ============ KEYBOARDS ============

def main_menu():
    buttons = []
    row = []
    for key, cmd in SEARCH_COMMANDS.items():
        row.append(Button.inline(cmd["name"], f"search_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([
        Button.inline("👤 My Profile", "my_profile"),
        Button.inline("🔑 API Keys", "api_keys_menu")
    ])
    buttons.append([
        Button.inline("👥 Refer", "referral_menu"),
        Button.inline("💰 Plans", "plans_menu")
    ])
    
    return buttons

def admin_menu():
    return [
        [Button.inline("📊 Stats", "admin_stats"), Button.inline("📢 Broadcast", "admin_broadcast")],
        [Button.inline("👥 Ban User", "admin_ban"), Button.inline("✅ Unban User", "admin_unban")],
        [Button.inline("➕ Add Admin", "admin_add_admin"), Button.inline("📺 Add Channel", "admin_add_channel")],
        [Button.inline("💳 Payments", "admin_payments"), Button.inline("🔙 Back", "back_main")]
    ]

def plans_menu():
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([Button.inline(f"{plan['name']} - ₹{plan['price']}", f"buy_{key}")])
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

# ============ HANDLERS ============

@bot_client.on(events.NewMessage(pattern=r'/start'))
async def start_handler(event):
    user = await event.get_sender()
    user_id = user.id
    
    user_doc = await get_user(user_id)
    if not user_doc:
        await create_user(user_id, user.username, user.first_name)
    
    user_doc = await get_user(user_id)
    
    if user_doc.get('banned'):
        await event.respond("❌ You have been banned from using this bot")
        return
    
    admin_check = await is_admin(user_id)
    if admin_check:
        await event.respond(f"👋 Admin {user.first_name}!", buttons=admin_menu())
        return
    
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        f"Select a search type:",
        buttons=main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^my_profile'))
async def my_profile_handler(event):
    user_id = event.sender_id
    user_doc = await get_user(user_id)
    
    if not user_doc:
        await event.answer("User not found", alert=True)
        return
    
    is_admin_check = await is_admin(user_id)
    
    message = (
        f"👤 My Profile\n\n"
        f"👤 Name: {user_doc.get('first_name', 'N/A')}\n"
        f"🆔 User ID: {user_id}\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n"
        f"📅 Joined: {user_doc.get('joined_at', 'N/A')[:10]}\n"
        f"👥 Referrals: {user_doc.get('referral_count', 0)}\n"
        f"🌐 Status: {'👮 Admin' if is_admin_check else 'User'}\n"
    )
    
    if user_doc.get('plan_expiry'):
        message += f"⏰ Expires: {user_doc.get('plan_expiry')[:10]}\n"
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "back_main")]])

@bot_client.on(events.CallbackQuery(pattern='^api_keys_menu'))
async def api_keys_menu_handler(event):
    await event.edit(
        "🔑 API Keys\n\n"
        "Manage your API keys for programmatic access",
        buttons=[
            [Button.inline("➕ Create Key", "api_create_key")],
            [Button.inline("📋 List Keys", "api_list_keys")],
            [Button.inline("📚 Documentation", "api_documentation")],
            [Button.inline("🔙 Back", "back_main")]
        ]
    )

@bot_client.on(events.CallbackQuery(pattern='^api_create_key'))
async def api_create_key_handler(event):
    user_states[event.sender_id] = {"action": "awaiting_api_key_name"}
    await event.edit("➕ Create API Key\n\nSend a name for this API key:")

@bot_client.on(events.CallbackQuery(pattern='^api_list_keys'))
async def api_list_keys_handler(event):
    api_keys = await get_api_keys(event.sender_id)
    
    if not api_keys:
        await event.answer("No API keys", alert=True)
        return
    
    message = f"📋 Your API Keys ({len(api_keys)})\n\n"
    for key in api_keys:
        message += f"**{key['name']}**\n"
        message += f"`{key['api_key'][:25]}...`\n"
        message += f"Created: {key['created_at'][:10]}\n"
        message += f"Used: {key.get('searches_used', 0)} times\n\n"
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "api_keys_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^api_documentation'))
async def api_documentation_handler(event):
    documentation = (
        "📚 API Documentation\n\n"
        "**Base URL**\n"
        "`https://relay-wzlz.onrender.com/api`\n\n"
        "**Endpoint: /search**\n"
        "POST request\n\n"
        "**Headers:**\n"
        "`X-API-Key: your_api_key`\n"
        "`Content-Type: application/json`\n\n"
        "**Request Body:**\n"
        "```json\n"
        "{\n"
        '  "search_type": "phone",\n'
        '  "query": "9876543210"\n'
        "}\n"
        "```\n\n"
        "**Response:**\n"
        "```json\n"
        "{\n"
        '  "success": true,\n'
        '  "result": "Data...",\n'
        '  "credits_remaining": 5\n'
        "}\n"
        "```\n\n"
        "**Search Types:**\n"
        "• phone - Phone number\n"
        "• vnum - Vehicle number\n"
        "• tg - Telegram user\n"
        "• imei - Device IMEI\n"
        "• gst - GST number\n"
        "• aadhar - Aadhar number\n"
        "• email - Email address\n"
        "• upi - UPI ID\n"
        "• insta - Instagram user\n"
        "• family - Family info\n\n"
        "**Terminal Example:**\n"
        "```bash\n"
        "curl -X POST https://relay-wzlz.onrender.com/api/search \\\n"
        "  -H 'X-API-Key: sk_abc123' \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '{\"search_type\": \"phone\", \"query\": \"9876543210\"}'\n"
        "```"
    )
    
    await event.edit(documentation, buttons=[[Button.inline("🔙 Back", "api_keys_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^referral_menu'))
async def referral_menu_handler(event):
    user_doc = await get_user(event.sender_id)
    referral_code = user_doc.get('referral_code', 'N/A')
    referral_link = generate_referral_link(event.sender_id, referral_code)
    
    message = (
        f"👥 Referral System\n\n"
        f"Earn {REFERRAL_REWARD} credits per referral!\n\n"
        f"**Your Code:** `{referral_code}`\n\n"
        f"**Your Link:**\n"
        f"`{referral_link}`\n\n"
        f"👥 Referrals: {user_doc.get('referral_count', 0)}\n"
        f"💰 Earned: {user_doc.get('referral_count', 0) * REFERRAL_REWARD} credits"
    )
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "back_main")]])

@bot_client.on(events.CallbackQuery(pattern='^plans_menu'))
async def plans_menu_handler(event):
    message = "💰 Premium Plans\n\n"
    for key, plan in PLANS.items():
        if plan['searches'] == -1:
            message += f"**{plan['name']}**\n"
            message += f"Unlimited searches for {plan['days']} days\n"
            message += f"Price: ₹{plan['price']}\n\n"
        else:
            message += f"**{plan['name']}**\n"
            message += f"{plan['searches']} searches\n"
            message += f"Price: ₹{plan['price']}\n\n"
    
    await event.edit(message, buttons=plans_menu())

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
        await event.edit("❌ No credits left\n\nBuy a plan to continue:", buttons=plans_menu())
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    await event.edit(f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\nSend the query:")

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_handler(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_')[1]
    
    if plan_key not in PLANS:
        return
    
    plan = PLANS[plan_key]
    payment_id = await create_payment(user_id, plan_key, plan['price'])
    
    if not payment_id:
        await event.answer("Error creating payment", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    await event.edit(
        f"💳 Payment Required\n\n"
        f"Plan: {plan['name']}\n"
        f"Amount: ₹{plan['price']}\n\n"
        f"ID: `{payment_id}`\n\n"
        f"Send payment screenshot",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )

# ============ ADMIN HANDLERS ============

@bot_client.on(events.CallbackQuery(pattern='^admin_stats'))
async def admin_stats_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    stats = await get_admin_stats()
    message = (
        f"📊 Statistics\n\n"
        f"👥 Total Users: {stats.get('total_users', 0)}\n"
        f"🟢 Active: {stats.get('active_users', 0)}\n"
        f"💎 Premium: {stats.get('premium_users', 0)}\n"
        f"🔍 Total Searches: {stats.get('total_searches', 0)}\n\n"
        f"💳 Payments\n"
        f"✅ Approved: {stats.get('approved_payments', 0)}\n"
        f"⏳ Pending: {stats.get('pending_payments', 0)}\n"
        f"💰 Total Revenue: ₹{stats.get('total_revenue', 0)}"
    )
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_broadcast'))
async def admin_broadcast_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_broadcast"}
    await event.edit("📢 Send the message to broadcast:")

@bot_client.on(events.CallbackQuery(pattern='^admin_ban'))
async def admin_ban_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_ban_user_id"}
    await event.edit("🚫 Send User ID to ban:")

@bot_client.on(events.CallbackQuery(pattern='^admin_unban'))
async def admin_unban_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_unban_user_id"}
    await event.edit("✅ Send User ID to unban:")

@bot_client.on(events.CallbackQuery(pattern='^admin_add_admin'))
async def admin_add_admin_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_add_admin_user_id"}
    await event.edit("➕ Send User ID to make admin:")

@bot_client.on(events.CallbackQuery(pattern='^admin_add_channel'))
async def admin_add_channel_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_add_channel"}
    await event.edit("📺 Send channel identifier:\n\n(username or ID)")

@bot_client.on(events.CallbackQuery(pattern='^admin_payments'))
async def admin_payments_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    try:
        pending = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(payments_col.find({"status": "pending"}).limit(5))
        )
        
        if not pending:
            await event.edit("✅ No pending payments", buttons=[[Button.inline("🔙 Back", "admin_menu")]])
            return
        
        message = f"💳 Pending Payments ({len(pending)})\n\n"
        buttons = []
        
        for p in pending:
            plan = PLANS.get(p['plan'], {})
            message += f"User: {p['user_id']}\n"
            message += f"Plan: {plan.get('name', '?')}\n"
            message += f"Amount: ₹{p['amount']}\n"
            message += f"ID: {p['payment_id'][:8]}...\n\n"
            
            buttons.append([
                Button.inline("✅ Approve", f"approve_{p['payment_id']}"),
                Button.inline("❌ Reject", f"reject_{p['payment_id']}")
            ])
        
        buttons.append([Button.inline("🔙 Back", "admin_menu")])
        await event.edit(message, buttons=buttons)
    except:
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^approve_(.+)'))
async def approve_payment_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    payment_id = event.data.decode().split('_')[1]
    
    if await approve_payment(payment_id):
        await event.edit(f"✅ Payment approved: {payment_id}")
    else:
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^reject_(.+)'))
async def reject_payment_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    payment_id = event.data.decode().split('_')[1]
    
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "rejected"}}
            )
        )
        await event.edit(f"❌ Payment rejected: {payment_id}")
    except:
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_handler(event):
    user_states.pop(event.sender_id, None)
    await event.edit("❌ Cancelled", buttons=main_menu())

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main_handler(event):
    user_doc = await get_user(event.sender_id)
    await event.edit(
        f"👋 Welcome {user_doc.get('first_name', 'User')}!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=main_menu()
    )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('action') == 'awaiting_api_key_name':
        key_name = event.text.strip()
        if len(key_name) < 3:
            await event.respond("❌ Minimum 3 characters")
            return
        
        api_key = await create_api_key(user_id, key_name)
        if api_key:
            await event.respond(f"✅ API Key Created!\n\n`{api_key}`\n\nSave this securely!")
        
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_broadcast':
        if not await is_admin(user_id):
            return
        
        message = event.text
        status = await event.respond("📢 Broadcasting...")
        result = await broadcast_message(message, user_id)
        await status.edit(f"✅ Sent: {result['sent']}\n❌ Failed: {result['failed']}")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_ban_user_id':
        if not await is_admin(user_id):
            return
        try:
            target_id = int(event.text.strip())
            await ban_user(target_id)
            await event.respond(f"🚫 User {target_id} banned!")
        except:
            await event.respond("❌ Invalid User ID")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_unban_user_id':
        if not await is_admin(user_id):
            return
        try:
            target_id = int(event.text.strip())
            await unban_user(target_id)
            await event.respond(f"✅ User {target_id} unbanned!")
        except:
            await event.respond("❌ Invalid User ID")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_add_admin_user_id':
        if not await is_admin(user_id):
            return
        try:
            target_id = int(event.text.strip())
            await add_admin(target_id)
            await event.respond(f"➕ User {target_id} is now admin!")
        except:
            await event.respond("❌ Invalid User ID")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_add_channel':
        if not await is_admin(user_id):
            return
        channel_id = event.text.strip()
        await add_mandatory_channel(channel_id)
        await event.respond(f"📺 Channel {channel_id} added!")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        if not query:
            return
        
        status_msg = await event.respond("⏳ Searching...")
        
        result = await perform_cascading_search(search_type, query, user_id)
        
        try:
            await status_msg.delete()
        except:
            pass
        
        if result['success']:
            await event.respond(result['result'])
            
            admin_check = await is_admin(user_id)
            if not admin_check:
                await decrement_search(user_id)
                
                user_doc = await get_user(user_id)
                if user_doc.get('total_searches', 0) == 1 and user_doc.get('referred_by'):
                    await reward_referrer(user_id)
        
        else:
            await event.respond(f"❌ {result.get('error', 'Error')}")
        
        user_states.pop(user_id, None)

    if state.get('action') == 'awaiting_payment':
        if not event.photo:
            await event.respond("❌ Please send an image")
            return
        
        payment_id = state['payment_id']
        plan_key = state['plan']
        plan = PLANS[plan_key]
        
        admins = await get_all_admins()
        
        for admin_id in admins:
            try:
                await bot_client.send_file(
                    admin_id,
                    event.photo,
                    caption=(
                        f"💰 Payment Screenshot\n\n"
                        f"User: {user_id}\n"
                        f"Plan: {plan['name']}\n"
                        f"Amount: ₹{plan['price']}\n"
                        f"Payment ID: {payment_id}"
                    ),
                    buttons=[
                        [
                            Button.inline("✅ Approve", f"approve_{payment_id}"),
                            Button.inline("❌ Reject", f"reject_{payment_id}")
                        ]
                    ]
                )
            except:
                pass
        
        await event.respond("✅ Screenshot received!\n\nWaiting for approval...")
        user_states.pop(user_id, None)

# ============ GROUP HANDLER ============

@user_client.on(events.NewMessage())
async def handle_group_replies(event):
    message = event.message
    now = time.time()
    
    matched_search = None
    matched_key = None
    
    # Find matching search
    for search_id, search_info in list(pending_searches.items()):
        if search_info['future'].done():
            continue
        if now - search_info.get('timestamp', now) > SEARCH_TIMEOUT_PER_GROUP * 10:
            continue
        
        # Only accept direct replies
        if message.reply_to and message.reply_to.reply_to_msg_id == search_info.get('message_id'):
            matched_search = search_info
            matched_key = search_id
            break
        
        # Also accept any new message from same group (fallback)
        if event.chat_id == search_info.get('chat_entity').id and not message.reply_to:
            if search_info['search_type'] in ['tg']:  # Only for certain types
                matched_search = search_info
                matched_key = search_id
                break
    
    if not matched_search:
        return
    
    text = message.text or message.raw_text
    has_file = message.file is not None
    
    if not text and not has_file:
        return
    
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    # Handle file
    if has_file:
        try:
            file_name = (message.file.name if has_file else None) or ""
            
            # Accept .txt and .json files
            if file_name.lower().endswith(('.txt', '.json')):
                logger.info(f"📥 File: {file_name}")
                file_bytes = await message.download_media(bytes)
                
                try:
                    file_text = file_bytes.decode('utf-8')
                except Exception:
                    try:
                        file_text = file_bytes.decode('latin-1')
                    except Exception:
                        file_text = file_bytes.decode('utf-8', errors='ignore')
                
                cleaned = clean_file(file_text)
                
                if cleaned and len(cleaned) > 15:
                    if not matched_search['future'].done():
                        matched_search['future'].set_result(cleaned)
                        pending_searches.pop(matched_key, None)
                        return
        except Exception as e:
            logger.error(f"File error: {e}")
            return
    
    # Handle text
    if text and not has_file:
        if is_processing_message(text):
            return
        
        if is_no_info_message(text):
            return
        
        if len(text.strip()) > 15:
            if not matched_search['future'].done():
                cleaned = filter_links(text)
                matched_search['future'].set_result(cleaned)
                pending_searches.pop(matched_key, None)

# ============ CLEANUP ============

async def cleanup_searches():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        to_remove = []
        
        for search_id, info in list(pending_searches.items()):
            age = now - info.get('timestamp', now)
            timeout = info.get('timeout', SEARCH_TIMEOUT_PER_GROUP)
            
            if age > timeout * 10:  # Allow longer for cascading
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError())
                    except Exception:
                        pass
                to_remove.append(search_id)
        
        for sid in to_remove:
            pending_searches.pop(sid, None)

# ============ WEB SERVER & API ============

async def start_web():
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK")
    
    async def api_search(request):
        try:
            api_key = request.headers.get('X-API-Key')
            if not api_key:
                return web.json_response({"success": False, "error": "Missing API key"}, status=401)
            
            key_info = await get_api_key_info(api_key)
            if not key_info:
                return web.json_response({"success": False, "error": "Invalid API key"}, status=401)
            
            user_id = key_info['user_id']
            user_doc = await get_user(user_id)
            
            if not user_doc or user_doc.get('banned'):
                return web.json_response({"success": False, "error": "User not found or banned"}, status=403)
            
            data = await request.json()
            search_type = data.get('search_type')
            query = data.get('query')
            
            if not search_type or not query:
                return web.json_response({"success": False, "error": "Missing parameters"}, status=400)
            
            if search_type not in SEARCH_COMMANDS:
                return web.json_response({"success": False, "error": "Invalid search type"}, status=400)
            
            result = await perform_cascading_search(search_type, query, user_id)
            
            if result['success']:
                await decrement_search(user_id)
                updated_user = await get_user(user_id)
                
                return web.json_response({
                    "success": True,
                    "result": result['result'],
                    "credits_remaining": updated_user.get('searches_remaining', 0)
                })
            else:
                return web.json_response(result, status=500)
        
        except Exception as e:
            logger.exception(f"API error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    app.router.add_get("/health", health_check)
    app.router.add_post("/api/search", api_search)
    app.router.add_get("/", lambda r: web.Response(text=f"Bot API - {WEBSITE}", content_type="text/plain"))
    
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
            logger.info("👤 Connecting user account...")
            if not user_client.is_connected():
                await user_client.connect()
            if not await user_client.is_user_authorized():
                raise RuntimeError("User not authorized")
            logger.info("✅ User account ready")

        logger.info("📡 Resolving groups...")
        
        for group in sorted(DESTINATION_GROUPS, key=lambda x: x['order']):
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ {group['name']} (Order: {group['order']})")
            except Exception as e:
                logger.warning(f"❌ {group['name']}: {e}")

        init_mongo()
        await add_admin(ADMIN_USER_ID)
        
        asyncio.create_task(cleanup_searches())
        asyncio.create_task(start_web())

        logger.info("=" * 70)
        logger.info("🚀 BOT FULLY OPERATIONAL!")
        logger.info("=" * 70)
        logger.info(f"Search timeout per group: {SEARCH_TIMEOUT_PER_GROUP}s")
        logger.info(f"Max groups: {MAX_GROUPS}")
        logger.info(f"New user credits: {NEW_USER_CREDITS}")
        logger.info(f"Referral reward: {REFERRAL_REWARD} credits")
        logger.info(f"Website: {WEBSITE}")
        logger.info(f"API Port: {PORT}")
        logger.info("=" * 70)

        await asyncio.Event().wait()

    except Exception as e:
        logger.exception("❌ Fatal error: %s", e)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception("❌ Bot crashed: %s", e)
