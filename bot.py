"""
Premium Information Bot - Complete Version
Full features with proper indentation
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
PROCESSING_WAIT_EXTRA = 8

PHONE_API_URL = "https://daily-binny-ryuioggv-391a9381.koyeb.app/api/lookup"
PHONE_API_KEY = "616bd0f26e364c89"
VEHICLE_API_URL = "https://vehicle-6bh6.onrender.com/vehicle_info"
VEHICLE_API_KEY = "URSLASH123"

REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2
BOT_FOOTER = "🔐 Powered by darkboxes_bot\n📱 Developed by darkboxesAdmin"

# ============ LOGGING ============

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("premium_bot")

# ============ VALIDATION ============

if BOT_API_ID == 0 or not BOT_API_HASH:
    raise ValueError("Missing API_ID or API_HASH")
if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

# ============ GROUPS CONFIG ============

DESTINATION_GROUPS = [
    {"name": "Main", "identifier": -1003596998816, "timeout": GROUP_TIMEOUT, "entity": None},
    {"name": "Backup 2", "identifier": "darkboxesv3", "timeout": GROUP_TIMEOUT, "entity": None},
    {"name": "Backup 3", "identifier": "nex_chats", "timeout": GROUP_TIMEOUT, "entity": None}
]

FAMILY_GROUP = {"name": "Family", "identifier": -1003596998816, "timeout": GROUP_TIMEOUT, "entity": None}
TELEGRAM_BOT = {"name": "TG Bot", "identifier": "@Dirgeshrai8090_bot", "timeout": GROUP_TIMEOUT, "entity": None}
TELEGRAM_USERNAME_GROUP = {"name": "TG User", "identifier": "darkboxesv3", "timeout": GROUP_TIMEOUT, "entity": None}
MOVIE_BOT = {"name": "Movie", "identifier": "@iPapkornD2bot", "timeout": 120, "entity": None}
VEHICLE_GROUP = {"name": "Vehicle", "identifier": "IntelXGroup", "timeout": GROUP_TIMEOUT, "entity": None}

# ============ SEARCH COMMANDS ============

SEARCH_COMMANDS = {
    "phone": {"name": "📱 Phone", "type": "group", "commands": {0: "/num", 1: "/num", 2: "/num"}},
    "family": {"name": "👨‍👩‍👧‍👦 Family", "type": "family_group", "commands": {0: "/familyinfo"}},
    "aadhar": {"name": "🆔 Aadhar", "type": "group", "commands": {0: "/aadhar", 1: "/adh", 2: "/aadhar"}},
    "vehicle": {"name": "🚗 Vehicle", "type": "vehicle_group", "commands": {0: "/vnum"}},
    "movies": {"name": "🎬 Movies", "type": "movie_bot", "commands": {0: ""}},
    "telegram": {"name": "📲 Telegram", "type": "telegram_bot", "commands": {0: "/tg"}},
}

PLANS = {
    "plan_5": {"searches": 5, "price": 100, "name": "5 Searches"},
    "plan_15": {"searches": 15, "price": 200, "name": "15 Searches"},
    "plan_week": {"searches": -1, "price": 500, "name": "Unlimited (7 Days)", "days": 7}
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
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        admins_col = db["admins"]
        
        users_col.create_index([("user_id", 1)], unique=True)
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
            None, lambda: admins_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
        )
        return True
    except:
        return False

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
            "channel_joined": False
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one({"user_id": user_id}, {"$setOnInsert": doc}, upsert=True)
        )
        return await get_user(user_id)
    except:
        return None

async def update_user_plan(user_id: int, plan: str, searches: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one({"user_id": user_id}, {"$set": {"plan": plan, "searches_remaining": searches}})
        )
        return True
    except:
        return False

async def decrement_search(user_id: int) -> bool:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one({"user_id": user_id}, {"$inc": {"searches_remaining": -1, "total_searches": 1}})
        )
        return True
    except:
        return False

async def log_search(user_id: int, search_type: str, query: str, result: str) -> bool:
    try:
        doc = {"user_id": user_id, "search_type": search_type, "query": query, "result": result[:500], "timestamp": datetime.now(timezone.utc).isoformat()}
        await asyncio.get_running_loop().run_in_executor(None, searches_col.insert_one, doc)
        return True
    except:
        return False

# ============ TEXT PROCESSING ============

def is_processing_message(text: str) -> bool:
    if not text or len(text.strip()) < 20:
        return True
    keywords = ['processing', 'please wait', 'fetching', 'loading', 'searching']
    return any(k in text.lower() for k in keywords)

def is_no_info_message(text: str) -> bool:
    if not text:
        return False
    keywords = ['no info', 'not found', 'no data', 'no result', 'invalid', 'not available']
    return any(k in text.lower() for k in keywords)

def filter_links_and_usernames(text: str) -> str:
    if not text:
        return text
    patterns = [r'https?://[^\s]+', r'www\.[^\s]+', r't\.me/[^\s]+', r'@[a-zA-Z0-9_]{3,32}']
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text).strip()
    return text

def clean_file_content(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'https?://\S+|www\.\S+|@\w+|#\w+', '', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines)

def add_footer(result: str) -> str:
    if not result:
        return result
    return f"{result}\n\n{'─' * 40}\n{BOT_FOOTER}"

# ============ STATE ============

user_states = {}
pending_searches = {}
interactive_sessions = {}

# ============ CLIENTS ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)
user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH) if USE_USER_ACCOUNT else bot_client

# ============ CHECK CHANNEL ============

async def check_channel_membership(user_id: int) -> bool:
    try:
        channel = await bot_client.get_entity(MANDATORY_CHANNEL)
        try:
            await bot_client(GetParticipantRequest(channel, user_id))
            return True
        except:
            return False
    except:
        return False

# ============ SEARCH FUNCTION ============

async def perform_search(search_type: str, query: str, user_id: int = None) -> Dict:
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search"}
    
    command_info = SEARCH_COMMANDS[search_type]
    search_dest_type = command_info.get('type', 'group')
    
    if search_dest_type == 'movie_bot':
        return await perform_movie_search(query, user_id)
    elif search_dest_type == 'telegram_bot':
        return await perform_telegram_search(query, user_id)
    
    if search_dest_type == 'family_group':
        destinations = [FAMILY_GROUP]
    elif search_dest_type == 'vehicle_group':
        destinations = [VEHICLE_GROUP]
    else:
        destinations = DESTINATION_GROUPS
    
    for idx, dest_config in enumerate(destinations):
        dest_entity = dest_config.get('entity')
        if not dest_entity:
            continue
        
        command_prefix = command_info['commands'].get(idx)
        if not command_prefix:
            continue
        
        command = f"{command_prefix} {query}"
        base_timeout = dest_config.get('timeout', GROUP_TIMEOUT)
        
        try:
            forwarded = await user_client.send_message(dest_entity, command)
            logger.info(f"📤 Sent: {command}")
            
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
                result_text = await asyncio.wait_for(future, timeout=base_timeout)
                
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                
                if result_text and len(result_text.strip()) > 20 and not is_processing_message(result_text) and not is_no_info_message(result_text):
                    cleaned = filter_links_and_usernames(result_text)
                    final_result = add_footer(cleaned)
                    
                    if user_id:
                        await log_search(user_id, search_type, query, cleaned)
                    
                    pending_searches.pop(search_id, None)
                    return {"success": True, "result": final_result, "search_type": search_type}
                else:
                    pending_searches.pop(search_id, None)
                    continue
            
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                continue
        
        except Exception as e:
            logger.warning(f"Search error: {e}")
            pending_searches.pop(search_id, None)
            continue
    
    return {"success": False, "error": "No result found"}

async def perform_movie_search(query: str, user_id: int) -> Dict:
    bot_entity = MOVIE_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Movie bot not available"}
    
    try:
        await user_client.send_message(bot_entity, query)
        await asyncio.sleep(5)
        
        messages = await user_client.get_messages(bot_entity, limit=20)
        
        for msg in messages:
            if msg.buttons:
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "movie",
                    "query": query
                }
                
                user_buttons = []
                for row_idx, row in enumerate(msg.buttons):
                    button_row = []
                    for col_idx, button in enumerate(row):
                        if hasattr(button, 'text'):
                            button_row.append(Button.inline(button.text, f"relay_movie_{row_idx}_{col_idx}"))
                    if button_row:
                        user_buttons.append(button_row)
                
                return {"success": False, "needs_interaction": True, "message": msg.text or "Select:", "buttons": user_buttons}
            
            if msg.text and len(msg.text.strip()) > 30:
                if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                    result = filter_links_and_usernames(msg.text)
                    final = add_footer(result)
                    return {"success": True, "result": final}
        
        return {"success": False, "error": "No response"}
    except Exception as e:
        logger.exception(f"Movie search error: {e}")
        return {"success": False, "error": str(e)}

async def perform_telegram_search(query: str, user_id: int) -> Dict:
    bot_entity = TELEGRAM_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Telegram bot not available"}
    
    try:
        await user_client.send_message(bot_entity, f"/tg {query}")
        await asyncio.sleep(3)
        
        messages = await user_client.get_messages(bot_entity, limit=15)
        
        for msg in messages:
            if msg.buttons:
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "telegram",
                    "query": query
                }
                
                user_buttons = []
                for row_idx, row in enumerate(msg.buttons):
                    button_row = []
                    for col_idx, button in enumerate(row):
                        if hasattr(button, 'text'):
                            button_row.append(Button.inline(button.text, f"relay_tg_{row_idx}_{col_idx}"))
                    if button_row:
                        user_buttons.append(button_row)
                
                return {"success": False, "needs_interaction": True, "message": msg.text or "Select:", "buttons": user_buttons}
            
            if msg.text and len(msg.text.strip()) > 30:
                if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                    result = filter_links_and_usernames(msg.text)
                    final = add_footer(result)
                    await log_search(user_id, "telegram", query, result)
                    return {"success": True, "result": final}
        
        return {"success": False, "error": "No response"}
    except Exception as e:
        logger.exception(f"Telegram search error: {e}")
        return {"success": False, "error": str(e)}

# ============ KEYBOARDS ============

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

def get_admin_menu():
    return [[Button.inline("📢 Broadcast", "admin_broadcast")], [Button.inline("📊 Stats", "admin_stats")], [Button.inline("🔙 Back", "back_main")]]

def get_plans_menu():
    buttons = []
    for plan_key, plan_info in PLANS.items():
        buttons.append([Button.inline(f"{plan_info['name']} - ₹{plan_info['price']}", f"buy_{plan_key}")])
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
        await event.respond("👋 Welcome Admin!", buttons=get_admin_menu())
        return
    
    is_member = await check_channel_membership(user_id)
    if not is_member:
        await event.respond(
            f"👋 Join to use bot\n\n@{MANDATORY_CHANNEL.replace('@', '')}",
            buttons=[[Button.url("📢 Join", f"https://t.me/{MANDATORY_CHANNEL.replace('@', '')}")], [Button.inline("✅ Joined", "check_membership")]]
        )
        return
    
    user_doc = await get_user(user_id)
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^admin_stats'))
async def admin_stats(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    
    total_users = await asyncio.get_running_loop().run_in_executor(None, users_col.count_documents, {})
    total_searches = await asyncio.get_running_loop().run_in_executor(None, searches_col.count_documents, {})
    
    await event.edit(f"📊 Stats\n\n👥 Users: {total_users}\n🔍 Searches: {total_searches}", buttons=[[Button.inline("🔙 Back", "back_main")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_broadcast'))
async def broadcast_handler(event):
    if not await is_admin(event.sender_id):
        await event.answer("❌ No access", alert=True)
        return
    user_states[event.sender_id] = {"action": "awaiting_broadcast"}
    await event.edit("📢 Send message:")

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_handler(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    user_doc = await get_user(user_id)
    admin_check = await is_admin(user_id)
    
    if not admin_check and user_doc.get('searches_remaining', 0) <= 0:
        await event.edit("❌ No credits", buttons=get_plans_menu())
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    await event.edit(f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\nSend query:")

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_handler(event):
    user_id = event.sender_id
    plan_key = event.data.decode().split('_')[1]
    
    if plan_key not in PLANS:
        return
    
    plan_info = PLANS[plan_key]
    payment_id = uuid.uuid4().hex
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    await event.edit(
        f"💳 Amount: ₹{plan_info['price']}\n\nScan & send screenshot\n\nID: `{payment_id}`",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_handler(event):
    user_states.pop(event.sender_id, None)
    await event.edit("❌ Cancelled")

@bot_client.on(events.CallbackQuery(pattern='^check_membership'))
async def check_membership_handler(event):
    user_id = event.sender_id
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.answer("❌ Not joined", alert=True)
        return
    
    user_doc = await get_user(user_id)
    user = await event.get_sender()
    
    await event.edit(
        f"✅ Welcome {user.first_name}!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main_handler(event):
    user = await event.get_sender()
    user_id = user.id
    user_doc = await get_user(user_id)
    
    await event.edit(
        f"👋 Welcome!\n\n📊 Plan: {user_doc.get('plan', 'free').upper()}\n🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=get_main_menu()
    )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    if state.get('action') == 'awaiting_broadcast':
        admin_check = await is_admin(user_id)
        if not admin_check:
            return
        
        message = event.text
        users = await asyncio.get_running_loop().run_in_executor(None, lambda: list(users_col.find({})))
        
        sent = 0
        for user_doc in users:
            try:
                await bot_client.send_message(user_doc['user_id'], message)
                sent += 1
            except:
                pass
        
        await event.respond(f"✅ Sent to {sent} users")
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
async def relay_button_handler(event):
    user_id = event.sender_id
    
    if user_id not in interactive_sessions:
        await event.answer("❌ Expired", alert=True)
        return
    
    session = interactive_sessions[user_id]
    dest_message = session['dest_message']
    dest_entity = session['dest_entity']
    search_type = session['type']
    
    try:
        callback_data = event.data.decode()
        
        if callback_data.startswith('relay_tg_'):
            parts = callback_data.split('_')
            row_idx = int(parts[2])
            col_idx = int(parts[3])
            
            if row_idx < len(dest_message.buttons) and col_idx < len(dest_message.buttons[row_idx]):
                await event.answer("⏳ Fetching...")
                await dest_message.click(row_idx, col_idx)
        
        elif callback_data.startswith('relay_movie_'):
            parts = callback_data.split('_')
            row_idx = int(parts[2])
            col_idx = int(parts[3])
            
            if row_idx < len(dest_message.buttons) and col_idx < len(dest_message.buttons[row_idx]):
                await event.answer("⏳ Fetching...")
                await dest_message.click(row_idx, col_idx)
        
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
                        await event.answer("✅ File received!")
                        
                        if msg.text:
                            result = filter_links_and_usernames(msg.text)
                            final = add_footer(result)
                            await bot_client.send_message(user_id, final)
                        
                        await bot_client.forward_messages(user_id, msg)
                        return
                    
                    if msg.text and len(msg.text.strip()) >= 30:
                        if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                            interactive_sessions.pop(user_id, None)
                            result = filter_links_and_usernames(msg.text)
                            final = add_footer(result)
                            await event.answer("✅ Result!")
                            await bot_client.send_message(user_id, final)
                            return
            
            except Exception as e:
                logger.warning(f"Check error: {e}")
        
        await event.answer("❌ No response", alert=True)
        interactive_sessions.pop(user_id, None)
    
    except Exception as e:
        logger.exception(f"Relay error: {e}")
        await event.answer("❌ Error", alert=True)
        interactive_sessions.pop(user_id, None)

# ============ GROUP MESSAGE HANDLER ============

@user_client.on(events.NewMessage())
async def handle_all_replies(event):
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
    file_name = (message.file.name if has_file else None) or ""
    
    if not text and not has_file:
        return
    
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    if has_file:
        try:
            if file_name.lower().endswith('.txt'):
                logger.info(f"📥 Downloading: {file_name}")
                file_bytes = await message.download_media(bytes)
                
                try:
                    file_text = file_bytes.decode('utf-8')
                except Exception:
                    try:
                        file_text = file_bytes.decode('latin-1')
                    except Exception:
                        file_text = file_bytes.decode('utf-8', errors='ignore')
                
                cleaned_file_text = clean_file_content(file_text)
                
                if cleaned_file_text and len(cleaned_file_text) > 15:
                    if not matched_search['future'].done():
                        logger.info(f"✅ File delivered")
                        matched_search['future'].set_result(cleaned_file_text)
                        pending_searches.pop(matched_key, None)
                        return
        except Exception as e:
            logger.error(f"File error: {e}")
            return
    
    if text and not has_file:
        if is_processing_message(text):
            return
        
        if is_no_info_message(text):
            return
        
        if not matched_search['future'].done():
            cleaned_text = filter_links_and_usernames(text)
            logger.info(f"✅ Text delivered")
            matched_search['future'].set_result(cleaned_text)
            pending_searches.pop(matched_key, None)

# ============ CLEANUP ============

async def cleanup_old_searches():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        to_remove = []
        
        for search_id, info in list(pending_searches.items()):
            age = now - info.get('timestamp', now)
            if age > REPLY_TIMEOUT:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError("Expired"))
                    except Exception:
                        pass
                to_remove.append(search_id)
        
        for search_id in to_remove:
            pending_searches.pop(search_id, None)

# ============ WEB SERVER ============

async def start_web_server():
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Server on port {PORT}")

# ============ MAIN ============

async def start_bot():
    try:
        logger.info("🤖 Starting...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot started")
        
        me = await bot_client.get_me()
        logger.info(f"@{me.username}")
        
        if USE_USER_ACCOUNT:
            logger.info("👤 User account...")
            if not user_client.is_connected():
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                raise RuntimeError("Not authorized")
            
            logger.info("✅ Ready")

        logger.info("📡 Resolving groups...")
        
        for idx, group in enumerate(DESTINATION_GROUPS):
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ {group['name']}")
            except Exception as e:
                logger.warning(f"❌ {group['name']}: {e}")
        
        try:
            FAMILY_GROUP['entity'] = await user_client.get_entity(FAMILY_GROUP['identifier'])
            logger.info(f"✅ Family")
        except Exception as e:
            logger.warning(f"Family: {e}")
        
        try:
            TELEGRAM_BOT['entity'] = await user_client.get_entity(TELEGRAM_BOT['identifier'])
            logger.info(f"✅ Telegram Bot")
        except Exception as e:
            logger.warning(f"Telegram: {e}")
        
        try:
            MOVIE_BOT['entity'] = await user_client.get_entity(MOVIE_BOT['identifier'])
            logger.info(f"✅ Movie")
        except Exception as e:
            logger.warning(f"Movie: {e}")

        init_mongo()
        await add_admin(ADMIN_USER_ID)
        
        asyncio.create_task(cleanup_old_searches())
        asyncio.create_task(start_web_server())

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
