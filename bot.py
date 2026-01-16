import os
import re
import json
import time
import uuid
import logging
import asyncio
import secrets
from datetime import datetime, timezone, timedelta

from aiohttp import web, ClientSession
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from pymongo import MongoClient

# ============ Config ============

PORT = int(os.getenv("PORT", "10000"))

# Bot credentials
BOT_SESSION_FILE = os.getenv("BOT_SESSION_FILE", "bot_session.session")
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# User account credentials (for forwarding)
USER_SESSION_FILE = os.getenv("USER_SESSION_FILE", "relay_session.session")
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
DESTINATION_GROUP = os.getenv("DESTINATION_GROUP", "darkboxesv3")
DESTINATION_GROUP_2 = os.getenv("DESTINATION_GROUP_2", "nex_chats")  # Second fallback
DESTINATION_GROUP_3 = os.getenv("DESTINATION_GROUP_3", "epicmoders")  # Third fallback
VEHICLE_GROUP = "IntelXGroup"  # For vehicle to number lookups
MANDATORY_CHANNEL = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")

PAYMENT_QR_CODE = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")

FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "3"))
REPLY_TIMEOUT = int(os.getenv("REPLY_TIMEOUT", "45"))

# API endpoints
PHONE_API_URL = "https://daily-binny-ryuioggv-391a9381.koyeb.app/api/lookup"
PHONE_API_KEY = "616bd0f26e364c89"
VEHICLE_API_URL = "https://vehicle-6bh6.onrender.com/vehicle_info"
VEHICLE_API_KEY = "URSLASH123"

# Referral settings
REFERRAL_REWARD = 2  # Credits given to referrer
NEW_USER_CREDITS = 2  # Free trial credits for new users

# ============ Logging ============

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("premium_bot")

# ============ Validate Config ============

if BOT_API_ID == 0 or not BOT_API_HASH:
    logger.error("API_ID and API_HASH must be set!")
    raise ValueError("Missing API_ID or API_HASH")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN must be set!")
    raise ValueError("Missing BOT_TOKEN")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

logger.info("=" * 60)
logger.info("Configuration Check:")
logger.info("BOT API_ID: %s", BOT_API_ID)
logger.info("BOT API_HASH: %s", BOT_API_HASH[:10] + "...")
logger.info("BOT_TOKEN: %s", BOT_TOKEN[:20] + "...")
logger.info("ADMIN_USER_ID: %s", ADMIN_USER_ID)
logger.info("DESTINATION_GROUP: %s", DESTINATION_GROUP)
logger.info("VEHICLE_GROUP: %s", VEHICLE_GROUP)
if USE_USER_ACCOUNT:
    logger.info("USER ACCOUNT: Enabled (Phone: %s)", USER_PHONE)
else:
    logger.info("USER ACCOUNT: Disabled (will use bot to forward)")
logger.info("=" * 60)

# ============ MongoDB ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
api_keys_col = None
referrals_col = None

def init_mongo():
    global mongo_client, db, users_col, payments_col, searches_col, api_keys_col, referrals_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        api_keys_col = db["api_keys"]
        referrals_col = db["referrals"]
        
        users_col.create_index([("user_id", 1)], unique=True)
        users_col.create_index([("referral_code", 1)], unique=True)
        payments_col.create_index([("user_id", 1)])
        searches_col.create_index([("user_id", 1)])
        api_keys_col.create_index([("api_key", 1)], unique=True)
        api_keys_col.create_index([("user_id", 1)])
        referrals_col.create_index([("referrer_id", 1)])
        referrals_col.create_index([("referred_id", 1)])
        
        logger.info("MongoDB connected successfully")
    except Exception as e:
        logger.exception("MongoDB connection failed: %s", e)
        raise

# ============ Referral System ============

def generate_referral_code():
    """Generate unique referral code"""
    return secrets.token_urlsafe(6).upper()

async def get_or_create_referral_code(user_id: int):
    """Get or create referral code for user"""
    try:
        user = await get_user(user_id)
        if user and user.get('referral_code'):
            return user['referral_code']
        
        # Generate new code
        while True:
            code = generate_referral_code()
            existing = await asyncio.get_running_loop().run_in_executor(
                None, users_col.find_one, {"referral_code": code}
            )
            if not existing:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: users_col.update_one(
                        {"user_id": user_id},
                        {"$set": {"referral_code": code}}
                    )
                )
                return code
    except Exception as e:
        logger.exception("Error generating referral code: %s", e)
        return None

async def apply_referral(referred_user_id: int, referral_code: str):
    """Apply referral code when new user joins"""
    try:
        # Find referrer by code
        referrer = await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"referral_code": referral_code.upper()}
        )
        
        if not referrer:
            return False
        
        referrer_id = referrer['user_id']
        
        # Don't allow self-referral
        if referrer_id == referred_user_id:
            return False
        
        # Check if user already used a referral
        user = await get_user(referred_user_id)
        if user.get('referred_by'):
            return False
        
        # Record referral
        referral_doc = {
            "referrer_id": referrer_id,
            "referred_id": referred_user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reward_given": False
        }
        
        await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.insert_one, referral_doc
        )
        
        # Mark user as referred
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referred_user_id},
                {"$set": {"referred_by": referrer_id}}
            )
        )
        
        return True
    except Exception as e:
        logger.exception("Error applying referral: %s", e)
        return False

async def reward_referrer(referred_user_id: int):
    """Give reward to referrer when referred user uses bot"""
    try:
        # Find referral record
        referral = await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.find_one, {"referred_id": referred_user_id, "reward_given": False}
        )
        
        if not referral:
            return False
        
        referrer_id = referral['referrer_id']
        
        # Give credits to referrer
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referrer_id},
                {"$inc": {"searches_remaining": REFERRAL_REWARD}}
            )
        )
        
        # Mark reward as given
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.update_one(
                {"_id": referral['_id']},
                {"$set": {"reward_given": True, "rewarded_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        
        # Notify referrer
        try:
            await bot_client.send_message(
                referrer_id,
                f"🎉 Congratulations!\n\n"
                f"You earned {REFERRAL_REWARD} credits because someone used your referral link!\n\n"
                f"Keep sharing to earn more credits! 💰"
            )
        except Exception as e:
            logger.error(f"Could not notify referrer {referrer_id}: {e}")
        
        return True
    except Exception as e:
        logger.exception("Error rewarding referrer: %s", e)
        return False

async def get_referral_stats(user_id: int):
    """Get referral statistics for user"""
    try:
        total_referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.count_documents({"referrer_id": user_id})
        )
        
        rewarded_referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.count_documents({"referrer_id": user_id, "reward_given": True})
        )
        
        return {
            "total": total_referrals,
            "rewarded": rewarded_referrals,
            "pending": total_referrals - rewarded_referrals
        }
    except Exception as e:
        logger.exception("Error getting referral stats: %s", e)
        return {"total": 0, "rewarded": 0, "pending": 0}

# ============ API Key Management ============

async def create_api_key(user_id: int, name: str = "Default Key"):
    """Create a new API key for a user - uses creator's credit balance"""
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
        await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.insert_one, doc
        )
        return api_key
    except Exception as e:
        logger.exception("Error creating API key: %s", e)
        return None

async def get_api_key_info(api_key: str):
    """Get API key information"""
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.find_one, {"api_key": api_key}
        )
    except Exception as e:
        logger.exception("Error fetching API key: %s", e)
        return None

async def list_user_api_keys(user_id: int):
    """List all API keys for a user"""
    try:
        cursor = api_keys_col.find({"user_id": user_id})
        return await asyncio.get_running_loop().run_in_executor(
            None, list, cursor
        )
    except Exception as e:
        logger.exception("Error listing API keys: %s", e)
        return []

async def delete_api_key(api_key: str, user_id: int):
    """Delete an API key"""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.delete_one(
                {"api_key": api_key, "user_id": user_id}
            )
        )
        return result.deleted_count > 0
    except Exception as e:
        logger.exception("Error deleting API key: %s", e)
        return False

async def increment_api_key_usage(api_key: str):
    """Increment API key usage counter"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.update_one(
                {"api_key": api_key},
                {
                    "$inc": {"searches_used": 1},
                    "$set": {"last_used": datetime.now(timezone.utc).isoformat()}
                }
            )
        )
        return True
    except Exception as e:
        logger.exception("Error incrementing API usage: %s", e)
        return False

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
            "searches_remaining": NEW_USER_CREDITS,  # Give free trial credits
            "plan_expiry": None,
            "total_searches": 0,
            "channel_joined": False,
            "referral_code": None,
            "referred_by": None
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
            "result": result[:500],
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
    """Remove links, usernames, and promotional content from text"""
    if not text:
        return text
    
    patterns = [
        r'https?://[^\s]+',           # HTTP/HTTPS links
        r'www\.[^\s]+',                # www links
        r't\.me/[^\s]+',               # Telegram links
        r'[a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*',  # Domain names
        r'@[\w]{2,32}',                # @usernames
        r'\b[a-zA-Z0-9_]{5,}\b(?=\s|$)'  # Potential usernames
    ]
    
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    
    lines = cleaned.splitlines()
    filtered_lines = []
    promotional = [
        'use these commands', 'join our', 'visit our', '💬 use', 
        'commands in', 'contact us', 'follow us', 'subscribe',
        'click here', 'check out', 'visit us', 'join us'
    ]
    
    for line in lines:
        l = line.strip()
        if not l or any(k in l.lower() for k in promotional):
            continue
        filtered_lines.append(line)
    
    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    
    return cleaned


def format_phone_api_response(data, phone_number: str):
    """Format phone API response into readable text"""
    try:
        result = f"📱 Phone Number Information\n\n"
        result += f"Number: {phone_number}\n\n"
        
        if isinstance(data, dict):
            # Remove unwanted fields
            data.pop('Developer', None)
            data.pop('Powered_By', None)
            data.pop('developer', None)
            data.pop('powered_by', None)
            
            if 'Result' in data and isinstance(data['Result'], list):
                records = data['Result']
                if records:
                    result += f"Found {len(records)} record(s):\n\n"
                    
                    for idx, record in enumerate(records, 1):
                        if len(records) > 1:
                            result += f"━━━ Record {idx} ━━━\n"
                        
                        if 'name' in record and record['name']:
                            result += f"👤 Name: {record['name'].strip()}\n"
                        
                        if 'mobile' in record and record['mobile']:
                            result += f"📱 Mobile: {record['mobile']}\n"
                        
                        if 'alt_mobile' in record and record['alt_mobile']:
                            result += f"📞 Alternate: {record['alt_mobile']}\n"
                        
                        if 'circle' in record and record['circle']:
                            result += f"📡 Circle: {record['circle']}\n"
                        
                        if 'father_name' in record and record['father_name']:
                            result += f"👨 Father: {record['father_name']}\n"
                        
                        if 'address' in record and record['address']:
                            addr = record['address'].replace('!', ', ').strip(', ')
                            result += f"📍 Address: {addr}\n"
                        
                        if 'email' in record and record['email']:
                            result += f"📧 Email: {record['email']}\n"
                        
                        if 'id_number' in record and record['id_number']:
                            result += f"🆔 ID: {record['id_number']}\n"
                        
                        if idx < len(records):
                            result += "\n"
                else:
                    result += "No records found.\n"
            else:
                for key, value in data.items():
                    if key.lower() not in ['status', 'success', 'developer', 'powered_by']:
                        result += f"{key.replace('_', ' ').title()}: {value}\n"
        else:
            result += str(data)
        
        return filter_links_and_usernames(result)
    except Exception as e:
        logger.exception(f"Error formatting phone API response: {e}")
        return f"📱 Phone Number: {phone_number}\n\nData received but formatting failed."


def format_vehicle_api_response(data, vehicle_no: str):
    """Format vehicle API response into readable text"""
    try:
        result = f"🚗 Vehicle Information\n\n"
        result += f"Vehicle Number: {vehicle_no}\n\n"
        
        if isinstance(data, dict):
            data.pop('Developer', None)
            data.pop('Powered_By', None)
            data.pop('developer', None)
            data.pop('powered_by', None)
            
            if 'owner_name' in data and data['owner_name']:
                result += f"👤 Owner: {data['owner_name']}\n"
            
            if 'mobile_number' in data and data['mobile_number']:
                result += f"📱 Mobile: {data['mobile_number']}\n"
            
            if 'father_name' in data and data['father_name']:
                result += f"👨 Father: {data['father_name']}\n"
            
            if 'vehicle_type' in data and data['vehicle_type']:
                result += f"🚙 Type: {data['vehicle_type']}\n"
            
            if 'registration_date' in data and data['registration_date']:
                result += f"📅 Registration: {data['registration_date']}\n"
            
            if 'maker_model' in data and data['maker_model']:
                result += f"🏭 Make/Model: {data['maker_model']}\n"
            
            if 'address' in data and data['address']:
                addr = data['address'].replace('!', ', ').strip(', ')
                result += f"📍 Address: {addr}\n"
            
            if 'state' in data and data['state']:
                result += f"🗺️ State: {data['state']}\n"
            
            skip_keys = ['owner_name', 'mobile_number', 'father_name', 'vehicle_type', 
                        'registration_date', 'maker_model', 'address', 'state',
                        'status', 'success', 'developer', 'powered_by']
            
            for key, value in data.items():
                if key.lower() not in skip_keys and value:
                    result += f"{key.replace('_', ' ').title()}: {value}\n"
        else:
            result += str(data)
        
        return filter_links_and_usernames(result)
    except Exception as e:
        logger.exception(f"Error formatting vehicle API response: {e}")
        return f"🚗 Vehicle Number: {vehicle_no}\n\nData received but formatting failed."


async def fetch_phone_api(phone_number: str):
    """New phone API for phone number lookup"""
    try:
        clean_number = re.sub(r'[^\d]', '', phone_number)
        
        async with ClientSession() as session:
            url = f"{PHONE_API_URL}?key={PHONE_API_KEY}&mobile={clean_number}"
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return format_phone_api_response(data, clean_number)
                else:
                    logger.warning(f"Phone API returned status {response.status}")
                    return None
    except asyncio.TimeoutError:
        logger.error("Phone API timeout")
        return None
    except Exception as e:
        logger.exception(f"Error fetching phone API: {e}")
        return None


async def fetch_vehicle_api(vehicle_no: str):
    """Fallback API for vehicle lookup"""
    try:
        clean_vehicle = vehicle_no.strip().upper()
        
        async with ClientSession() as session:
            url = f"{VEHICLE_API_URL}?key={VEHICLE_API_KEY}&vehicle_no={clean_vehicle}"
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return format_vehicle_api_response(data, clean_vehicle)
                else:
                    logger.warning(f"Vehicle API returned status {response.status}")
                    return None
    except asyncio.TimeoutError:
        logger.error("Vehicle API timeout")
        return None
    except Exception as e:
        logger.exception(f"Error fetching vehicle API: {e}")
        return None

# ============ Command Mapping ============

SEARCH_COMMANDS = {
    "phone": {"cmd": "/num", "name": "📱 Phone Number Info", "groups": ["main", "backup2", "backup3"]},
    "family": {"cmd": "/family", "name": "👨‍👩‍👧‍👦 Family Info", "groups": ["main", "backup2", "backup3"]},
    "aadhar": {"cmd": "/adhar", "name": "🆔 Aadhar Info", "groups": ["main", "backup2", "backup3"]},
    "vehicle": {"cmd": "/vnum", "name": "🚗 Vehicle to Phone", "groups": ["vehicle"]},
    "vehicle_detail": {"cmd": "/vehicle", "name": "🚙 Vehicle Details", "groups": ["main", "backup2", "backup3"]},
    "upi": {"cmd": "/upiinfo", "name": "💳 UPI Info", "groups": ["main", "backup2", "backup3"]},
    "fampay": {"cmd": "/fam", "name": "💰 Fampay Info", "groups": ["main"]},
    "email": {"cmd": "/email", "name": "📧 Email Info", "groups": ["main", "backup2", "backup3"]},
    "telegram": {"cmd": "/tg", "name": "📲 Telegram to Phone", "groups": ["main"]},
    "imei": {"cmd": "/imei", "name": "📱 IMEI Info", "groups": ["main", "backup2", "backup3"]},
    "pak": {"cmd": "/cnic", "name": "🇵🇰 Pakistan Info", "groups": ["main", "backup2", "backup3"]},
    "gst": {"cmd": "/gst", "name": "🏢 GST Info", "groups": ["main"]},
    "insta": {"cmd": "/insta", "name": "📷 Instagram Info", "groups": ["main", "backup2", "backup3"]}
}

PLANS = {
    "plan_5": {"searches": 5, "price": 100, "name": "5 Searches", "days": None},
    "plan_15": {"searches": 15, "price": 200, "name": "15 Searches", "days": None},
    "plan_week": {"searches": -1, "price": 500, "name": "Unlimited (7 Days)", "days": 7}
}

# ============ Bot State ============

user_states = {}
pending_searches = {}

# ============ Telethon Clients ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)

if USE_USER_ACCOUNT:
    user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH)
else:
    user_client = bot_client

DEST_ENTITY = None
DEST_ENTITY_2 = None
DEST_ENTITY_3 = None
VEHICLE_ENTITY = None

async def check_channel_membership(user_id: int):
    try:
        participant = await bot_client.get_permissions(MANDATORY_CHANNEL, user_id)
        return participant is not None
    except Exception as e:
        logger.exception("Error checking channel membership: %s", e)
        return False

# ============ Core Search Function ============

async def perform_search(search_type: str, query: str, user_id: int = None):
    """Core search function with multiple destination group fallback"""
    
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search type"}
    
    command_info = SEARCH_COMMANDS[search_type]
    command = f"{command_info['cmd']} {query}"
    group_types = command_info.get('groups', ['main'])
    
    # Determine which groups to try
    destination_entities = []
    if 'vehicle' in group_types:
        destination_entities = [VEHICLE_ENTITY]
    else:
        if 'main' in group_types and DEST_ENTITY:
            destination_entities.append(DEST_ENTITY)
        if 'backup2' in group_types and DEST_ENTITY_2:
            destination_entities.append(DEST_ENTITY_2)
        if 'backup3' in group_types and DEST_ENTITY_3:
            destination_entities.append(DEST_ENTITY_3)
    
    if not destination_entities:
        destination_entities = [DEST_ENTITY]  # Fallback to main
    
    # Try each destination group
    for idx, dest_entity in enumerate(destination_entities):
        if not dest_entity:
            continue
            
        try:
            forwarded = await user_client.send_message(dest_entity, command)
            logger.info(f"📤 Sent to destination group {idx+1}: {command}")
            
            future = asyncio.get_running_loop().create_future()
            search_id = f"{forwarded.id}_{int(time.time() * 1000)}_{idx}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "group_index": idx
            }
            
            logger.info(f"🔍 Registered search {search_id} in group {idx+1}")
            
            try:
                result = await asyncio.wait_for(future, timeout=REPLY_TIMEOUT)
                cleaned = filter_links_and_usernames(result)
                
                if not cleaned.strip():
                    cleaned = "No results found or data was filtered."
                
                if user_id:
                    await log_search(user_id, search_type, query, cleaned)
                
                return {"success": True, "result": cleaned, "search_type": search_type, "source": f"group_{idx+1}"}
                
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.warning(f"⏱️ Timeout for search in group {idx+1}: {search_type} - {query[:20]}")
                
                # If this was the last group, try API fallback
                if idx == len(destination_entities) - 1:
                    # Try API fallback for phone numbers
                    if search_type in ['phone', 'telegram']:
                        logger.info(f"🔄 Attempting phone API fallback for {query}")
                        api_result = await fetch_phone_api(query)
                        
                        if api_result:
                            if user_id:
                                await log_search(user_id, search_type, query, api_result)
                            return {"success": True, "result": api_result, "search_type": search_type, "source": "api_backup"}
                    
                    # Try API fallback for vehicle numbers
                    elif search_type in ['vehicle', 'vehicle_detail']:
                        logger.info(f"🔄 Attempting vehicle API fallback for {query}")
                        api_result = await fetch_vehicle_api(query)
                        
                        if api_result:
                            if user_id:
                                await log_search(user_id, search_type, query, api_result)
                            return {"success": True, "result": api_result, "search_type": search_type, "source": "api_backup"}
                    
                    return {"success": False, "error": "Request timed out in all groups and no backup available"}
                else:
                    # Continue to next group
                    continue
                
        except Exception as e:
            logger.exception(f"Error performing search in group {idx+1}: %s", e)
            if idx == len(destination_entities) - 1:
                return {"success": False, "error": str(e)}
            continue
    
    return {"success": False, "error": "All destination groups failed"}

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
    buttons.append([Button.inline("🔑 API Keys", "api_menu"), Button.inline("👥 Referrals", "referral_menu")])
    return buttons

def get_api_menu():
    return [
        [Button.inline("➕ Create API Key", "api_create")],
        [Button.inline("📋 List API Keys", "api_list")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_referral_menu():
    return [
        [Button.inline("📊 My Stats", "referral_stats")],
        [Button.inline("🔗 Get Referral Link", "referral_link")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

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

@bot_client.on(events.NewMessage(pattern=r'/start( (.+))?'))
async def start_handler(event):
    user = await event.get_sender()
    user_id = user.id
    
    # Extract referral code if present
    referral_code = None
    if event.pattern_match.group(2):
        referral_code = event.pattern_match.group(2).strip()
    
    user_doc = await get_user(user_id)
    
    # Create new user or update existing
    if not user_doc:
        await create_or_update_user(user_id, user.username, user.first_name)
        
        # Apply referral if provided
        if referral_code:
            success = await apply_referral(user_id, referral_code)
            if success:
                await event.respond(
                    f"🎉 Welcome! You've successfully used a referral code!\n"
                    f"You got {NEW_USER_CREDITS} free trial credits to start with."
                )
    
    user_doc = await get_user(user_id)
    
    if user_id == ADMIN_USER_ID:
        await event.respond(
            f"👋 Welcome Admin!\n\n"
            f"You have full access to all features.\n"
            f"Use the menu below:",
            buttons=get_main_menu()
        )
        return
    
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
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Searches Remaining: {user_doc.get('searches_remaining', 0)}\n\n"
        f"Select an option below:",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_menu$'))
async def referral_menu_callback(event):
    await event.edit(
        "👥 Referral System\n\n"
        f"Earn {REFERRAL_REWARD} credits for each friend who uses your link!\n\n"
        "Share your referral link and when they perform their first search, you get rewarded.",
        buttons=get_referral_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_link$'))
async def referral_link_callback(event):
    user_id = event.sender_id
    
    referral_code = await get_or_create_referral_code(user_id)
    
    if not referral_code:
        await event.answer("❌ Error generating referral code", alert=True)
        return
    
    bot_info = await bot_client.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    await event.edit(
        f"🔗 Your Referral Link\n\n"
        f"`{referral_link}`\n\n"
        f"Share this link with friends!\n"
        f"You'll earn {REFERRAL_REWARD} credits when they use the bot.\n\n"
        f"💡 Tip: Share on social media, groups, or with friends!",
        buttons=[[Button.inline("🔙 Back", "referral_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_stats$'))
async def referral_stats_callback(event):
    user_id = event.sender_id
    
    stats = await get_referral_stats(user_id)
    user_doc = await get_user(user_id)
    
    message = (
        f"📊 Your Referral Statistics\n\n"
        f"👥 Total Referrals: {stats['total']}\n"
        f"✅ Rewarded: {stats['rewarded']}\n"
        f"⏳ Pending: {stats['pending']}\n\n"
        f"💰 Total Earned: {stats['rewarded'] * REFERRAL_REWARD} credits\n"
        f"🔍 Current Balance: {user_doc.get('searches_remaining', 0)} credits"
    )
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "referral_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^api_menu$'))
async def api_menu_callback(event):
    await event.edit(
        "🔑 API Key Management\n\n"
        "Manage your API keys for programmatic access:",
        buttons=get_api_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^api_create$'))
async def api_create_callback(event):
    user_id = event.sender_id
    user_states[user_id] = {"action": "awaiting_api_key_name"}
    
    await event.edit(
        "➕ Create New API Key\n\n"
        "Please send a name for this API key (e.g., 'My App', 'Production Server'):"
    )

@bot_client.on(events.CallbackQuery(pattern='^api_list$'))
async def api_list_callback(event):
    user_id = event.sender_id
    api_keys = await list_user_api_keys(user_id)
    
    if not api_keys:
        await event.answer("You don't have any API keys yet.", alert=True)
        return
    
    message = "📋 Your API Keys:\n\n"
    buttons = []
    
    for key_doc in api_keys:
        created = datetime.fromisoformat(key_doc['created_at']).strftime('%Y-%m-%d')
        status = "🟢 Active" if key_doc.get('active', True) else "🔴 Inactive"
        
        message += f"**{key_doc['name']}**\n"
        message += f"Key: `{key_doc['api_key'][:20]}...`\n"
        message += f"Created: {created}\n"
        message += f"Used: {key_doc.get('searches_used', 0)} times\n"
        message += f"Status: {status}\n\n"
        
        buttons.append([Button.inline(
            f"🗑️ Delete {key_doc['name']}", 
            f"api_delete_{key_doc['api_key']}"
        )])
    
    buttons.append([Button.inline("🔙 Back", "api_menu")])
    
    await event.edit(message, buttons=buttons)

@bot_client.on(events.CallbackQuery(pattern=r'^api_delete_(.+)$'))
async def api_delete_callback(event):
    user_id = event.sender_id
    api_key = event.data.decode().split('_', 2)[2]
    
    success = await delete_api_key(api_key, user_id)
    
    if success:
        await event.answer("✅ API key deleted successfully", alert=True)
        await api_list_callback(event)
    else:
        await event.answer("❌ Failed to delete API key", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^back_main$'))
async def back_main_callback(event):
    await start_handler(event)

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    if user_id == ADMIN_USER_ID:
        user_states[user_id] = {"action": "awaiting_input", "type": search_type}
        try:
            await event.edit(
                f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
                f"Please send the {search_type} to search:"
            )
        except Exception:
            await event.answer()
            await bot_client.send_message(
                user_id,
                f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
                f"Please send the {search_type} to search:"
            )
        return
    
    user_doc = await get_user(user_id)
    
    if not user_doc:
        await event.answer("❌ Error: User not found", alert=True)
        return
    
    searches_remaining = user_doc.get('searches_remaining', 0)
    plan = user_doc.get('plan', 'free')
    plan_expiry = user_doc.get('plan_expiry')
    
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
        try:
            await event.edit(
                "❌ Access Not Granted\n\n"
                "You must buy a premium pack to use this bot.\n\n"
                "Select a plan below:",
                buttons=get_plans_menu()
            )
        except Exception:
            await event.answer("❌ Access Not Granted", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    try:
        await event.edit(
            f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
            f"Searches Remaining: {searches_remaining if searches_remaining > 0 else 'Unlimited'}\n\n"
            f"Please send the {search_type} to search:"
        )
    except Exception:
        await event.answer()
        await bot_client.send_message(
            user_id,
            f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
            f"Searches Remaining: {searches_remaining if searches_remaining > 0 else 'Unlimited'}\n\n"
            f"Please send the {search_type} to search:"
        )

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)$'))
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
    
    try:
        user = await event.get_sender()
        await bot_client.send_message(
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
    
    try:
        await bot_client.send_file(event.sender_id, PAYMENT_QR_CODE, caption="Scan to pay")
    except Exception as e:
        logger.exception("Error sending QR code: %s", e)
        await event.respond("Please pay and send screenshot.")

@bot_client.on(events.CallbackQuery(pattern=r'^approve_(.+)_(.+)$'))
async def approve_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    payment = await asyncio.get_running_loop().run_in_executor(
        None, payments_col.find_one, {"payment_id": payment_id}
    )
    
    if not payment:
        await event.answer("❌ Payment not found", alert=True)
        return
    
    plan_key = payment['plan']
    plan_info = PLANS[plan_key]
    
    if plan_info['searches'] == -1:
        await update_user_plan(target_user_id, "unlimited", 999999, plan_info['days'])
    else:
        user_doc = await get_user(target_user_id)
        current_searches = user_doc.get('searches_remaining', 0)
        await update_user_plan(target_user_id, "paid", current_searches + plan_info['searches'])
    
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
    
    try:
        await bot_client.send_message(
            target_user_id,
            f"✅ Payment Approved!\n\n"
            f"Your {plan_info['name']} plan has been activated.\n"
            f"Use /start to begin searching.",
            buttons=[[Button.inline("🚀 Start Searching", "start")]]
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@bot_client.on(events.CallbackQuery(pattern=r'^reject_(.+)_(.+)$'))
async def reject_payment_callback(event):
    if event.sender_id != ADMIN_USER_ID:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    payment_id = data_parts[1]
    target_user_id = int(data_parts[2])
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: payments_col.update_one(
            {"payment_id": payment_id},
            {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
        )
    )
    
    await event.edit(f"❌ Payment Rejected\n\nPayment ID: {payment_id}")
    
    try:
        await bot_client.send_message(
            target_user_id,
            "❌ Payment Rejected\n\n"
            "Your payment was not approved. Please contact support or try again."
        )
    except Exception as e:
        logger.exception("Error notifying user: %s", e)

@bot_client.on(events.CallbackQuery(pattern='^cancel$'))
async def cancel_callback(event):
    user_id = event.sender_id
    user_states.pop(user_id, None)
    await event.edit(
        "❌ Cancelled\n\nUse /start to begin again.",
        buttons=None
    )

@bot_client.on(events.CallbackQuery(pattern='^start$'))
async def start_button_callback(event):
    await start_handler(event)

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def message_handler(event):
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    # Handle API key name input
    if state.get('action') == 'awaiting_api_key_name':
        key_name = event.text.strip()
        
        if len(key_name) < 3:
            await event.respond("❌ Name must be at least 3 characters. Please try again:")
            return
        
        user_doc = await get_user(user_id)
        
        api_key = await create_api_key(user_id, key_name)
        
        if api_key:
            if user_doc.get('plan') == 'unlimited':
                credits_info = "Unlimited credits ♾️"
            else:
                credits_info = f"{user_doc.get('searches_remaining', 0)} credits remaining"
            
            await event.respond(
                f"✅ API Key Created Successfully!\n\n"
                f"**Name:** {key_name}\n"
                f"**API Key:** `{api_key}`\n"
                f"**Your Credits:** {credits_info}\n\n"
                f"⚠️ **Important:** \n"
                f"• Save this key securely\n"
                f"• API uses YOUR account credits\n"
                f"• Recharge to get more credits\n\n"
                f"**Usage Example:**\n"
                f"```bash\n"
                f"curl -X POST https://your-domain.com/api/search \\\n"
                f"  -H 'X-API-Key: {api_key}' \\\n"
                f"  -H 'Content-Type: application/json' \\\n"
                f"  -d '{{\n"
                f'    "search_type": "phone",\n'
                f'    "query": "1234567890"\n'
                f"  }}'\n"
                f"```",
                buttons=[[Button.inline("🔙 Back to API Menu", "api_menu")]]
            )
        else:
            await event.respond(
                "❌ Failed to create API key. Please try again.",
                buttons=[[Button.inline("🔙 Back to API Menu", "api_menu")]]
            )
        
        user_states.pop(user_id, None)
        return
    
    if state.get('action') == 'awaiting_payment':
        if not event.photo:
            await event.respond("❌ Please send a screenshot image.")
            return
        
        payment_id = state['payment_id']
        plan_key = state['plan']
        plan_info = PLANS[plan_key]
        
        await update_payment_screenshot(payment_id, event.message.id)
        
        try:
            user = await event.get_sender()
            await bot_client.send_file(
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
    
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        status_msg = await event.respond("⏳ Fetching information... Please wait.")
        
        # Check if this is user's first search (for referral reward)
        user_doc = await get_user(user_id)
        is_first_search = user_doc.get('total_searches', 0) == 0 and user_doc.get('referred_by')
        
        # Perform search using core function
        result = await perform_search(search_type, query, user_id)
        
        await status_msg.delete()
        
        if result['success']:
            # Show source if backup was used
            source_info = ""
            if result.get('source') == 'api_backup':
                source_info = " (via backup API)"
            elif result.get('source', '').startswith('group_'):
                group_num = result['source'].split('_')[1]
                if group_num != '1':
                    source_info = f" (via backup group {group_num})"
            
            await event.respond(f"✅ Result{source_info}:\n\n{result['result']}")
            
            # Decrement search count for non-admin users
            if user_id != ADMIN_USER_ID:
                user_doc = await get_user(user_id)
                if user_doc.get('plan') != 'unlimited':
                    await decrement_search(user_id)
                
                # Reward referrer on first search
                if is_first_search:
                    await reward_referrer(user_id)
        else:
            await event.respond(
                "❌ This command is not available right now.\n\n"
                "We're working to bring it back soon. Please try again later."
            )
        
        user_states.pop(user_id, None)

# ============ Message Handler for All Groups ============

@user_client.on(events.NewMessage(chats=[DESTINATION_GROUP, VEHICLE_GROUP]))
async def handle_destination_reply(event):
    message = event.message
    
    text = message.text or message.raw_text
    if not text:
        return
    
    now = time.time()
    
    matched_search = None
    matched_key = None
    
    for search_id, search_info in list(pending_searches.items()):
        if search_info['future'].done():
            continue
        
        if now - search_info.get("timestamp", now) > REPLY_TIMEOUT:
            logger.warning(f"⏱️ Skipping expired search {search_id}")
            continue
        
        query = search_info['query'].strip()
        search_type = search_info['search_type']
        message_text_lower = text.lower()
        
        is_match = False
        
        if search_type in ['phone', 'telegram']:
            clean_query = re.sub(r'[^\d]', '', query)
            clean_msg = re.sub(r'[^\d]', '', text)
            if clean_query and len(clean_query) >= 10 and clean_query in clean_msg:
                is_match = True
                logger.info(f"✅ Phone match found for {clean_query[:4]}****")
                
        elif search_type == 'aadhar':
            clean_query = re.sub(r'[^\d]', '', query)
            if len(clean_query) == 12 and clean_query in re.sub(r'[^\d]', '', text):
                is_match = True
                logger.info(f"✅ Aadhar match found")
                
        elif search_type in ['vehicle', 'vehicle_detail']:
            clean_query = re.sub(r'[^a-z0-9]', '', query.lower())
            clean_msg = re.sub(r'[^a-z0-9]', '', message_text_lower)
            if clean_query and len(clean_query) >= 6 and clean_query in clean_msg:
                is_match = True
                logger.info(f"✅ Vehicle match found for {query}")
                
        elif search_type in ['upi', 'fampay', 'email']:
            if query.lower() in message_text_lower:
                is_match = True
                logger.info(f"✅ {search_type.upper()} match found for {query}")
                
        elif search_type == 'imei':
            clean_query = re.sub(r'[^\d]', '', query)
            if len(clean_query) == 15 and clean_query in re.sub(r'[^\d]', '', text):
                is_match = True
                logger.info(f"✅ IMEI match found")
                
        elif search_type == 'gst':
            clean_query = re.sub(r'[^a-z0-9]', '', query.lower())
            clean_msg = re.sub(r'[^a-z0-9]', '', message_text_lower)
            if clean_query and len(clean_query) >= 10 and clean_query in clean_msg:
                is_match = True
                logger.info(f"✅ GST match found")
        
        elif search_type == 'family':
            clean_query = re.sub(r'[^\d]', '', query)
            clean_msg = re.sub(r'[^\d]', '', text)
            if clean_query and len(clean_query) >= 10 and clean_query in clean_msg:
                is_match = True
                logger.info(f"✅ Family info match found")
        
        elif search_type == 'pak':
            clean_query = re.sub(r'[^\d]', '', query)
            clean_msg = re.sub(r'[^\d]', '', text)
            if clean_query and len(clean_query) >= 10 and clean_query in clean_msg:
                is_match = True
                logger.info(f"✅ Pakistan number match found")
        
        elif search_type == 'insta':
            if query.lower() in message_text_lower:
                is_match = True
                logger.info(f"✅ Instagram match found for {query}")
        
        else:
            if query.lower() in message_text_lower:
                is_match = True
                logger.info(f"✅ Generic match found for {search_type}")
        
        if is_match:
            matched_search = search_info
            matched_key = search_id
            logger.info(f"🎯 Match confirmed for search_id: {search_id}, type: {search_type}")
            break
    
    if not matched_search:
        return
    
    await asyncio.sleep(FETCH_WAIT_TIME)
    
    try:
        # Get the chat entity
        chat = await event.get_chat()
        latest = await user_client.get_messages(chat, ids=message.id)
        if latest:
            latest_text = latest.text or latest.raw_text
            if latest_text:
                if not matched_search['future'].done():
                    logger.info(f"📨 Delivering result to user {matched_search['user_id']}")
                    matched_search['future'].set_result(latest_text)
                    pending_searches.pop(matched_key, None)
                    logger.info(f"✅ Search {matched_key} completed and removed")
    except Exception as e:
        logger.exception("Error handling matched message: %s", e)

# ============ Cleanup Task ============

async def cleanup_old_searches():
    """Remove searches that have been pending too long"""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        to_remove = []
        
        for search_id, info in list(pending_searches.items()):
            age = now - info.get('timestamp', now)
            if age > REPLY_TIMEOUT + 10:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError("Search expired"))
                    except Exception:
                        pass
                to_remove.append(search_id)
        
        for search_id in to_remove:
            pending_searches.pop(search_id, None)
            logger.info(f"🧹 Cleaned up expired search: {search_id}")
        
        if to_remove:
            logger.info(f"🧹 Cleanup: Removed {len(to_remove)} expired searches")

# ============ API Endpoints ============

async def verify_api_key(request):
    """Middleware to verify API key and check creator's credit balance"""
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return web.json_response(
            {"success": False, "error": "Missing API key"},
            status=401
        )
    
    key_info = await get_api_key_info(api_key)
    
    if not key_info:
        return web.json_response(
            {"success": False, "error": "Invalid API key"},
            status=401
        )
    
    if not key_info.get('active', True):
        return web.json_response(
            {"success": False, "error": "API key is inactive"},
            status=401
        )
    
    # Check creator's (user's) current credit balance
    user_id = key_info['user_id']
    user_doc = await get_user(user_id)
    
    if not user_doc:
        return web.json_response(
            {"success": False, "error": "User not found"},
            status=404
        )
    
    # Check if creator has searches remaining in their account
    if user_doc.get('plan') != 'unlimited':
        searches_remaining = user_doc.get('searches_remaining', 0)
        if searches_remaining <= 0:
            return web.json_response(
                {
                    "success": False, 
                    "error": "API creator has no credits remaining. Please recharge your account.",
                    "creator_credits": 0
                },
                status=403
            )
    
    request['api_key_info'] = key_info
    request['user_doc'] = user_doc
    return None

async def api_search_handler(request):
    """Handle API search requests - uses creator's credit balance"""
    
    # Verify API key
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    key_info = request['api_key_info']
    user_doc = request['user_doc']
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON"},
            status=400
        )
    
    search_type = data.get('search_type')
    query = data.get('query')
    
    if not search_type or not query:
        return web.json_response(
            {"success": False, "error": "Missing search_type or query"},
            status=400
        )
    
    if search_type not in SEARCH_COMMANDS:
        return web.json_response(
            {"success": False, "error": f"Invalid search_type. Valid types: {list(SEARCH_COMMANDS.keys())}"},
            status=400
        )
    
    # Perform search using creator's account
    user_id = key_info['user_id']
    result = await perform_search(search_type, query, user_id)
    
    if result['success']:
        # Increment API key usage counter (for statistics)
        await increment_api_key_usage(key_info['api_key'])
        
        # Deduct credit from creator's account (not from API key limit)
        if user_doc.get('plan') != 'unlimited':
            await decrement_search(user_id)
            # Get updated credits after deduction
            updated_user = await get_user(user_id)
            remaining_credits = updated_user.get('searches_remaining', 0)
        else:
            remaining_credits = -1  # Unlimited
        
        return web.json_response({
            "success": True,
            "search_type": search_type,
            "query": query,
            "result": result['result'],
            "source": result.get('source', 'primary'),
            "creator_credits_remaining": remaining_credits
        })
    else:
        return web.json_response(result, status=500)

async def api_info_handler(request):
    """Get API key info and creator's credit balance"""
    
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    key_info = request['api_key_info']
    user_doc = request['user_doc']
    
    # Calculate credits remaining
    if user_doc.get('plan') == 'unlimited':
        credits_remaining = -1  # Unlimited
        plan_status = "Unlimited"
    else:
        credits_remaining = user_doc.get('searches_remaining', 0)
        plan_status = user_doc.get('plan', 'free').upper()
    
    return web.json_response({
        "success": True,
        "api_key_name": key_info['name'],
        "created_at": key_info['created_at'],
        "api_searches_used": key_info.get('searches_used', 0),
        "last_used": key_info.get('last_used'),
        "creator_plan": plan_status,
        "creator_credits_remaining": credits_remaining,
        "note": "API uses creator's account credits. Recharge your account to get more credits."
    })

async def api_types_handler(request):
    """List available search types"""
    return web.json_response({
        "success": True,
        "search_types": {
            key: info['name'] 
            for key, info in SEARCH_COMMANDS.items()
        }
    })

async def health_check(request):
    return web.Response(text="OK", status=200)

# ============ Web Server ============

async def start_web_server():
    app = web.Application()
    
    # Health check
    app.router.add_get("/health", health_check)
    
    # API endpoints
    app.router.add_post("/api/search", api_search_handler)
    app.router.add_get("/api/info", api_info_handler)
    app.router.add_get("/api/types", api_types_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")
    logger.info(f"📡 API endpoints:")
    logger.info(f"   POST /api/search - Perform search")
    logger.info(f"   GET  /api/info - Get API key info")
    logger.info(f"   GET  /api/types - List search types")

# ============ Main ============

async def start_bot():
    global DEST_ENTITY, DEST_ENTITY_2, DEST_ENTITY_3, VEHICLE_ENTITY
    
    try:
        logger.info("🤖 Starting Telegram bot...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot started successfully")
        me = await bot_client.get_me()
        logger.info(f"Bot username: @{me.username}")
        logger.info(f"Bot ID: {me.id}")
        
        if USE_USER_ACCOUNT:
            logger.info("👤 Starting user account client for forwarding...")
            
            if not user_client.is_connected():
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                raise RuntimeError(
                    "❌ User session not authorized. "
                    "Login once locally with start(phone=...) and upload the session file to Render."
                )
            
            logger.info("✅ User account session loaded successfully")

        # Resolve destination group entities
        DEST_ENTITY = await user_client.get_entity(DESTINATION_GROUP)
        logger.info(f"📨 Main destination group resolved: {DESTINATION_GROUP}")
        
        # Resolve backup groups if configured
        if DESTINATION_GROUP_2:
            try:
                DEST_ENTITY_2 = await user_client.get_entity(DESTINATION_GROUP_2)
                logger.info(f"📨 Backup group 2 resolved: {DESTINATION_GROUP_2}")
            except Exception as e:
                logger.warning(f"Could not resolve backup group 2: {e}")
        
        if DESTINATION_GROUP_3:
            try:
                DEST_ENTITY_3 = await user_client.get_entity(DESTINATION_GROUP_3)
                logger.info(f"📨 Backup group 3 resolved: {DESTINATION_GROUP_3}")
            except Exception as e:
                logger.warning(f"Could not resolve backup group 3: {e}")
        
        # Resolve vehicle group
        try:
            VEHICLE_ENTITY = await user_client.get_entity(VEHICLE_GROUP)
            logger.info(f"🚗 Vehicle group resolved: {VEHICLE_GROUP}")
        except Exception as e:
            logger.warning(f"Could not resolve vehicle group: {e}")

        # Initialize MongoDB
        init_mongo()

        # Start background tasks
        asyncio.create_task(cleanup_old_searches())
        asyncio.create_task(start_web_server())

        logger.info("🚀 Bot is fully operational")
        logger.info(f"💰 New users get {NEW_USER_CREDITS} free credits")
        logger.info(f"🎁 Referral reward: {REFERRAL_REWARD} credits per successful referral")

        # Keep running forever
        await asyncio.Event().wait()

    except Exception as e:
        logger.exception("❌ Fatal error while starting bot: %s", e)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
