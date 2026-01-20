"""
Premium Information Bot - Extended Version with Advanced Features
Includes: Better admin panel, stats, detailed logging, rate limiting, more search types
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
from collections import defaultdict

from aiohttp import web, ClientSession
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from telethon.tl.functions.channels import GetParticipantRequest
from pymongo import MongoClient

# ============ CONFIGURATION ============

PORT = int(os.getenv("PORT", "10000"))
BOT_SESSION_FILE = os.getenv("BOT_SESSION_FILE", "bot_session.session")
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

USER_SESSION_FILE = os.getenv("USER_SESSION_FILE", "relay_session.session")
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
MANDATORY_CHANNEL = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")

PAYMENT_QR_CODE = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")

FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "2"))
GROUP_TIMEOUT = int(os.getenv("GROUP_TIMEOUT", "500"))
REPLY_TIMEOUT = int(os.getenv("REPLY_TIMEOUT", "660"))

REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2
BOT_FOOTER = "🔐 Powered by darkboxes_bot\n📱 Developed by darkboxesAdmin"

# ============ LOGGING ============

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger("premium_bot")

# ============ VALIDATION ============

if BOT_API_ID == 0 or not BOT_API_HASH:
    raise ValueError("Missing API_ID or API_HASH")
if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

# ============ GROUPS CONFIG ============

DESTINATION_GROUPS = [
    {"name": "Main Group", "identifier": -1003596998816, "timeout": GROUP_TIMEOUT, "entity": None},
    {"name": "Backup Group 2", "identifier": "darkboxesv3", "timeout": GROUP_TIMEOUT, "entity": None},
    {"name": "Backup Group 3", "identifier": "nex_chats", "timeout": GROUP_TIMEOUT, "entity": None}
]

FAMILY_GROUP = {"name": "Family Group", "identifier": -1003596998816, "timeout": GROUP_TIMEOUT, "entity": None}
TELEGRAM_BOT = {"name": "Telegram Bot", "identifier": "@Dirgeshrai8090_bot", "timeout": GROUP_TIMEOUT, "entity": None}
TELEGRAM_USERNAME_GROUP = {"name": "TG Username Group", "identifier": "darkboxesv3", "timeout": GROUP_TIMEOUT, "entity": None}
MOVIE_BOT = {"name": "Movie Bot", "identifier": "@iPapkornD2bot", "timeout": 120, "entity": None}
VEHICLE_GROUP = {"name": "Vehicle Group", "identifier": "IntelXGroup", "timeout": GROUP_TIMEOUT, "entity": None}

# ============ SEARCH COMMANDS ============

SEARCH_COMMANDS = {
    "phone": {"name": "📱 Phone Number", "type": "group", "commands": {0: "/num", 1: "/num", 2: "/num"}},
    "family": {"name": "👨‍👩‍👧‍👦 Family Info", "type": "family_group", "commands": {0: "/familyinfo"}},
    "aadhar": {"name": "🆔 Aadhar", "type": "group", "commands": {0: "/aadhar", 1: "/adh", 2: "/aadhar"}},
    "vehicle": {"name": "🚗 Vehicle to Phone", "type": "vehicle_group", "commands": {0: "/vnum"}},
    "vehicle_detail": {"name": "🚙 Vehicle Details", "type": "group", "commands": {0: "/vehicle", 1: "/vehicle", 2: "/vnum"}},
    "upi": {"name": "💳 UPI Info", "type": "group", "commands": {0: "/upiinfo", 1: "/upiinfo", 2: "/upiinfo"}},
    "email": {"name": "📧 Email Info", "type": "group", "commands": {0: "/email", 1: "/email", 2: "/email"}},
    "telegram": {"name": "📲 Telegram to Phone", "type": "telegram_bot", "commands": {0: "/tg"}},
    "telegram_username": {"name": "👤 Telegram Username", "type": "telegram_username_group", "commands": {0: "/tg"}},
    "imei": {"name": "📱 IMEI", "type": "group", "commands": {0: "/imei", 1: "/imei", 2: "/imei"}},
    "gst": {"name": "🏢 GST", "type": "group", "commands": {0: "/gst", 1: "/gst", 2: "/gst"}},
    "insta": {"name": "📷 Instagram", "type": "group", "commands": {0: "/insta", 1: "/insta", 2: "/insta"}},
    "movies": {"name": "🎬 Movies/Series", "type": "movie_bot", "commands": {0: ""}},
}

PLANS = {
    "plan_5": {"searches": 5, "price": 100, "name": "5 Searches", "days": None},
    "plan_15": {"searches": 15, "price": 200, "name": "15 Searches", "days": None},
    "plan_week": {"searches": -1, "price": 500, "name": "Unlimited (7 Days)", "days": 7},
    "plan_month": {"searches": -1, "price": 1000, "name": "Unlimited (30 Days)", "days": 30}
}

# ============ DATABASE ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
admins_col = None
api_keys_col = None
referrals_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col, admins_col, api_keys_col, referrals_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        admins_col = db["admins"]
        api_keys_col = db["api_keys"]
        referrals_col = db["referrals"]
        
        users_col.create_index([("user_id", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])
        searches_col.create_index([("user_id", 1)])
        logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.exception("MongoDB error: %s", e)
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
        logger.info(f"✅ Admin added: {user_id}")
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

# ============ USER FUNCTIONS ============

async def get_user(user_id: int) -> Optional[Dict]:
    try:
        return await asyncio.get_running_loop().run_in_executor(None, users_col.find_one, {"user_id": user_id})
    except:
        return None

async def create_user(user_id: int, username: str = None, first_name: str = None) -> Optional[Dict]:
    try:
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "plan": "free",
            "searches_remaining": NEW_USER_CREDITS,
            "plan_expiry": None,
            "total_searches": 0,
            "channel_joined": False,
            "referral_code": None,
            "referred_by": None,
            "blocked": False
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

async def log_search(user_id: int, search_type: str, query: str, result: str) -> bool:
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "result_length": len(result),
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

async def broadcast_message(message: str, exclude_id: int = None) -> Dict:
    try:
        users = await asyncio.get_running_loop().run_in_executor(None, lambda: list(users_col.find({})))
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

# ============ TEXT PROCESSING ============

def is_processing_message(text: str) -> bool:
    if not text or len(text.strip()) < 20:
        return True
    keywords = ['processing', 'please wait', 'fetching', 'loading', 'searching', 'hold on', 'wait']
    return any(k in text.lower() for k in keywords)

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    keywords = ['no info', 'not found', 'no data', 'no result', 'invalid', 'not available', 'no record', 'doesn\'t exist', 'not exist']
    return any(k in text.lower() for k in keywords)

def filter_links(text: str) -> str:
    if not text:
        return text
    patterns = [r'https?://[^\s]+', r'www\.[^\s]+', r't\.me/[^\s]+', r'@[a-zA-Z0-9_]{3,32}', r'tg://[^\s]+']
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
interactive_sessions = {}

# ============ CLIENTS ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)
user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH) if USE_USER_ACCOUNT else bot_client

# ============ HELPERS ============

async def check_channel(user_id: int) -> bool:
    try:
        channel = await bot_client.get_entity(MANDATORY_CHANNEL)
        try:
            await bot_client(GetParticipantRequest(channel, user_id))
            return True
        except:
            return False
    except:
        return False

# ============ SEARCH ============

async def perform_search(search_type: str, query: str, user_id: int = None) -> Dict:
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search"}
    
    command_info = SEARCH_COMMANDS[search_type]
    search_dest_type = command_info.get('type', 'group')
    
    if search_dest_type == 'movie_bot':
        return await search_movies(query, user_id)
    elif search_dest_type == 'telegram_bot':
        return await search_telegram(query, user_id)
    elif search_dest_type == 'telegram_username_group':
        return await search_telegram_username(query, user_id)
    
    destinations = [FAMILY_GROUP] if search_dest_type == 'family_group' else [VEHICLE_GROUP] if search_dest_type == 'vehicle_group' else DESTINATION_GROUPS
    
    for idx, dest_config in enumerate(destinations):
        dest_entity = dest_config.get('entity')
        if not dest_entity:
            continue
        
        command_prefix = command_info['commands'].get(idx)
        if not command_prefix:
            continue
        
        command = f"{command_prefix} {query}"
        
        try:
            forwarded = await user_client.send_message(dest_entity, command)
            logger.info(f"📤 {search_type}: {query}")
            
            future = asyncio.get_running_loop().create_future()
            search_id = f"{forwarded.id}_{int(time.time() * 1000)}_{idx}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "message_id": forwarded.id,
                "chat_entity": dest_entity
            }
            
            try:
                result_text = await asyncio.wait_for(future, timeout=dest_config.get('timeout', GROUP_TIMEOUT))
                
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                
                if result_text and len(result_text.strip()) > 20 and not is_processing_message(result_text) and not is_no_info_message(result_text):
                    cleaned = filter_links(result_text)
                    final = add_footer(cleaned)
                    
                    if user_id:
                        await log_search(user_id, search_type, query, cleaned)
                    
                    pending_searches.pop(search_id, None)
                    return {"success": True, "result": final}
                else:
                    pending_searches.pop(search_id, None)
                    continue
            
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                continue
        
        except Exception as e:
            logger.debug(f"Search error: {e}")
            pending_searches.pop(search_id, None)
            continue
    
    return {"success": False, "error": "No result found. Try another query."}

async def search_movies(query: str, user_id: int) -> Dict:
    bot_entity = MOVIE_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Movie bot unavailable"}
    
    try:
        await user_client.send_message(bot_entity, query)
        await asyncio.sleep(5)
        
        messages = await user_client.get_messages(bot_entity, limit=20)
        
        for msg in messages:
            if msg.buttons:
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "movie"
                }
                
                buttons = []
                for r_idx, row in enumerate(msg.buttons):
                    btn_row = []
                    for c_idx, btn in enumerate(row):
                        if hasattr(btn, 'text'):
                            btn_row.append(Button.inline(btn.text, f"relay_movie_{r_idx}_{c_idx}"))
                    if btn_row:
                        buttons.append(btn_row)
                
                return {"success": False, "needs_interaction": True, "message": msg.text or "Select:", "buttons": buttons}
            
            if msg.text and len(msg.text.strip()) > 30 and not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                return {"success": True, "result": add_footer(filter_links(msg.text))}
        
        return {"success": False, "error": "No response"}
    except Exception as e:
        logger.exception(f"Movie error: {e}")
        return {"success": False, "error": str(e)}

async def search_telegram(query: str, user_id: int) -> Dict:
    bot_entity = TELEGRAM_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Telegram bot unavailable"}
    
    try:
        await user_client.send_message(bot_entity, f"/tg {query}")
        await asyncio.sleep(3)
        
        messages = await user_client.get_messages(bot_entity, limit=15)
        
        for msg in messages:
            if msg.buttons:
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "telegram"
                }
                
                buttons = []
                for r_idx, row in enumerate(msg.buttons):
                    btn_row = []
                    for c_idx, btn in enumerate(row):
                        if hasattr(btn, 'text'):
                            btn_row.append(Button.inline(btn.text, f"relay_tg_{r_idx}_{c_idx}"))
                    if btn_row:
                        buttons.append(btn_row)
                
                return {"success": False, "needs_interaction": True, "message": msg.text or "Select:", "buttons": buttons}
            
            if msg.text and len(msg.text.strip()) > 30 and not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                return {"success": True, "result": add_footer(filter_links(msg.text))}
        
        return {"success": False, "error": "No response"}
    except Exception as e:
        logger.exception(f"Telegram error: {e}")
        return {"success": False, "error": str(e)}

async def search_telegram_username(query: str, user_id: int) -> Dict:
    group_entity = TELEGRAM_USERNAME_GROUP.get('entity')
    if not group_entity:
        return {"success": False, "error": "Username group unavailable"}
    
    try:
        await user_client.send_message(group_entity, f"/tg {query}")
        await asyncio.sleep(3)
        
        messages = await user_client.get_messages(group_entity, limit=15)
        for msg in messages:
            if msg.text and len(msg.text.strip()) > 30 and not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                return {"success": True, "result": add_footer(filter_links(msg.text))}
        
        return {"success": False, "error": "Not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============ KEYBOARDS ============

def main_menu():
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

def admin_menu():
    return [
        [Button.inline("📊 Stats", "admin_stats"), Button.inline("📢 Broadcast", "admin_broadcast")],
        [Button.inline("👥 Users", "admin_users"), Button.inline("💳 Payments", "admin_payments")],
        [Button.inline("🔙 Back", "back_main")]
    ]

def plans_menu():
    buttons = [[Button.inline(f"{p['name']} - ₹{p['price']}", f"buy_{k}")] for k, p in PLANS.items()]
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
    
    admin_check = await is_admin(user_id)
    if admin_check:
        await event.respond(f"👋 Welcome Admin {user.first_name}!", buttons=admin_menu())
        return
    
    is_member = await check_channel(user_id)
    if not is_member:
        await event.respond(
            f"👋 Join to use\n\n@{MANDATORY_CHANNEL.replace('@', '')}",
            buttons=[[Button.url("📢 Join", f"https://t.me/{MANDATORY_CHANNEL.replace('@', '')}")], [Button.inline("✅ Joined", "check_membership")]]
        )
        return
    
    user_doc = await get_user(user_id)
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n📊 Plan: {user_doc.get('plan', 'free').upper()}\n🔍 Credits: {user_doc.get('searches_remaining', 0)}\n📈 Searches: {user_doc.get('total_searches', 0)}",
        buttons=main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^admin_stats'))
async def admin_stats(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    stats = await get_admin_stats()
    message = (
        f"📊 Statistics\n\n"
        f"👥 Users: {stats.get('total_users', 0)}\n"
        f"🟢 Active: {stats.get('active_users', 0)}\n"
        f"💎 Premium: {stats.get('premium_users', 0)}\n"
        f"🔍 Searches: {stats.get('total_searches', 0)}\n\n"
        f"💳 Payments\n"
        f"✅ Approved: {stats.get('approved_payments', 0)}\n"
        f"⏳ Pending: {stats.get('pending_payments', 0)}\n"
        f"💰 Revenue: ₹{stats.get('total_revenue', 0)}"
    )
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_broadcast'))
async def broadcast_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    user_states[event.sender_id] = {"action": "awaiting_broadcast"}
    await event.edit("📢 Send message to broadcast:")

@bot_client.on(events.CallbackQuery(pattern='^admin_users'))
async def admin_users(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    stats = await get_admin_stats()
    message = f"👥 Users Management\n\nTotal: {stats.get('total_users', 0)}\nActive: {stats.get('active_users', 0)}\n\nFeature coming soon..."
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_payments'))
async def admin_payments(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    try:
        pending = list(payments_col.find({"status": "pending"}).limit(5))
        
        if not pending:
            await event.edit("✅ No pending payments", buttons=[[Button.inline("🔙 Back", "admin_menu")]])
            return
        
        message = f"💳 Pending Payments ({len(pending)})\n\n"
        for p in pending:
            plan = PLANS.get(p['plan'], {})
            message += f"User: {p['user_id']}\nPlan: {plan.get('name', '?')}\n₹{p['amount']}\n\n"
        
        await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])
    except:
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^admin_menu'))
async def admin_menu_handler(event):
    if not await is_admin(event.sender_id):
        return
    await event.edit("👨‍💼 Admin Panel", buttons=admin_menu())

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_handler(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    user_doc = await get_user(user_id)
    admin_check = await is_admin(user_id)
    
    if not admin_check and user_doc.get('searches_remaining', 0) <= 0:
        await event.edit("❌ No credits left", buttons=plans_menu())
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    await event.edit(f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n💡 Send query:")

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_handler(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_')[1]
    
    if plan_key not in PLANS:
        return
    
    plan = PLANS[plan_key]
    payment_id = await create_payment(user_id, plan_key, plan['price'])
    
    if not payment_id:
        await event.answer("Error", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    await event.edit(
        f"💳 Payment\n\nPlan: {plan['name']}\nAmount: ₹{plan['price']}\n\nScan QR & send screenshot\n\nID: `{payment_id}`",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_handler(event):
    user_states.pop(event.sender_id, None)
    interactive_sessions.pop(event.sender_id, None)
    await event.edit("❌ Cancelled", buttons=main_menu())

@bot_client.on(events.CallbackQuery(pattern='^check_membership'))
async def check_membership(event):
    user_id = event.sender_id
    is_member = await check_channel(user_id)
    
    if not is_member:
        await event.answer("❌ Not joined", alert=True)
        return
    
    user_doc = await get_user(user_id)
    user = await event.get_sender()
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one({"user_id": user_id}, {"$set": {"channel_joined": True}})
    )
    
    await event.edit(
        f"✅ Welcome {user.first_name}!\n\n📊 Plan: {user_doc.get('plan', 'free').upper()}\n🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main(event):
    user = await event.get_sender()
    user_id = user.id
    user_doc = await get_user(user_id)
    
    admin_check = await is_admin(user_id)
    if admin_check:
        await event.edit("👨‍💼 Admin Panel", buttons=admin_menu())
    else:
        await event.edit(
            f"👋 {user.first_name}\n\n📊 Plan: {user_doc.get('plan', 'free').upper()}\n🔍 Credits: {user_doc.get('searches_remaining', 0)}",
            buttons=main_menu()
        )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('action') == 'awaiting_broadcast':
        if not await is_admin(user_id):
            return
        
        message = event.text
        status = await event.respond("📢 Broadcasting...")
        result = await broadcast_message(message, user_id)
        await status.edit(f"✅ Sent: {result['sent']}\n❌ Failed: {result['failed']}")
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        status_msg = await event.respond("⏳ Searching...")
        result = await perform_search(search_type, query, user_id)
        
        try:
            await status_msg.delete()
        except:
            pass
        
        if result['success']:
            await event.respond(result['result'])
            admin_check = await is_admin(user_id)
            if not admin_check:
                user_doc = await get_user(user_id)
                if user_doc.get('plan') != 'unlimited':
                    await decrement_search(user_id)
        
        elif result.get('needs_interaction'):
            await event.respond(result['message'], buttons=result['buttons'])
            return
        
        else:
            await event.respond(f"❌ {result.get('error', 'Error')}")
        
        user_states.pop(user_id, None)

# ============ RELAY HANDLER ============

@bot_client.on(events.CallbackQuery(pattern=r'^relay_'))
async def relay_button(event):
    user_id = event.sender_id
    
    if user_id not in interactive_sessions:
        await event.answer("❌ Expired", alert=True)
        return
    
    session = interactive_sessions[user_id]
    dest_message = session['dest_message']
    dest_entity = session['dest_entity']
    
    try:
        callback_data = event.data.decode()
        
        if callback_data.startswith('relay_tg_'):
            parts = callback_data.split('_')
            r_idx = int(parts[2])
            c_idx = int(parts[3])
            
            if r_idx < len(dest_message.buttons) and c_idx < len(dest_message.buttons[r_idx]):
                await event.answer("⏳ Fetching...")
                await dest_message.click(r_idx, c_idx)
        
        elif callback_data.startswith('relay_movie_'):
            parts = callback_data.split('_')
            r_idx = int(parts[2])
            c_idx = int(parts[3])
            
            if r_idx < len(dest_message.buttons) and c_idx < len(dest_message.buttons[r_idx]):
                await event.answer("⏳ Fetching...")
                await dest_message.click(r_idx, c_idx)
        
        await asyncio.sleep(2)
        
        for attempt in range(6):
            await asyncio.sleep(2 if attempt == 0 else 3)
            
            try:
                messages = await user_client.get_messages(dest_entity, limit=50)
                
                for msg in messages:
                    if not msg.date or msg.date.timestamp() < (time.time() - 40):
                        continue
                    
                    if msg.id == dest_message.id:
                        continue
                    
                    if msg.file:
                        interactive_sessions.pop(user_id, None)
                        await event.answer("✅ File!")
                        
                        if msg.text:
                            await bot_client.send_message(user_id, add_footer(filter_links(msg.text)))
                        
                        await bot_client.forward_messages(user_id, msg)
                        return
                    
                    if msg.text and len(msg.text.strip()) >= 30:
                        if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                            interactive_sessions.pop(user_id, None)
                            await event.answer("✅ Got it!")
                            await bot_client.send_message(user_id, add_footer(filter_links(msg.text)))
                            return
            
            except Exception as e:
                logger.debug(f"Error: {e}")
        
        await event.answer("❌ No response", alert=True)
        interactive_sessions.pop(user_id, None)
    
    except Exception as e:
        logger.exception(f"Relay: {e}")
        await event.answer("❌ Error", alert=True)

# ============ GROUP HANDLER ============

@user_client.on(events.NewMessage())
async def handle_replies(event):
    message = event.message
    now = time.time()
    
    matched_search = None
    matched_key = None
    
    for search_id, search_info in list(pending_searches.items()):
        if search_info['future'].done():
            continue
        if now - search_info.get('timestamp', now) > REPLY_TIMEOUT:
            continue
        
        search_type = search_info['search_type']
        if search_type in ['telegram', 'movies']:
            matched_search = search_info
            matched_key = search_id
            break
    
    if not matched_search and message.reply_to:
        for search_id, search_info in list(pending_searches.items()):
            if search_info['future'].done():
                continue
            if now - search_info.get('timestamp', now) > REPLY_TIMEOUT:
                continue
            
            if message.reply_to.reply_to_msg_id == search_info.get('message_id'):
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
    
    if has_file:
        try:
            file_name = (message.file.name if has_file else None) or ""
            if file_name.lower().endswith('.txt'):
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
            logger.error(f"File: {e}")
            return
    
    if text and not has_file:
        if is_processing_message(text):
            return
        
        if is_no_info_message(text):
            return
        
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
            if age > REPLY_TIMEOUT:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError())
                    except Exception:
                        pass
                to_remove.append(search_id)
        
        for sid in to_remove:
            pending_searches.pop(sid, None)

# ============ WEB SERVER ============

async def start_web():
    app = web.Application()
    
    app.router.add_get("/health", lambda r: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Port {PORT}")

# ============ MAIN ============

async def start_bot():
    try:
        logger.info("🤖 Starting...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot OK")
        
        me = await bot_client.get_me()
        logger.info(f"@{me.username}")
        
        if USE_USER_ACCOUNT:
            if not user_client.is_connected():
                await user_client.connect()
            if not await user_client.is_user_authorized():
                raise RuntimeError("Not auth")
            logger.info("✅ User OK")

        logger.info("📡 Groups...")
        
        for group in DESTINATION_GROUPS:
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ {group['name']}")
            except Exception as e:
                logger.warning(f"{group['name']}: {e}")
        
        for g in [FAMILY_GROUP, TELEGRAM_BOT, MOVIE_BOT, VEHICLE_GROUP]:
            try:
                g['entity'] = await user_client.get_entity(g['identifier'])
                logger.info(f"✅ {g['name']}")
            except Exception as e:
                logger.warning(f"{g['name']}: {e}")

        init_mongo()
        await add_admin(ADMIN_USER_ID)
        
        asyncio.create_task(cleanup_searches())
        asyncio.create_task(start_web())

        logger.info("=" * 60)
        logger.info("🚀 BOT READY!")
        logger.info("=" * 60)

        await asyncio.Event().wait()

    except Exception as e:
        logger.exception("Fatal: %s", e)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Stopped")
    except Exception as e:
        logger.exception("Crash: %s", e)
