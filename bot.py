"""
Premium Information Bot with Advanced Features
- Phone/Family/Vehicle/UPI/Email/Aadhar/GST/Instagram/IMEI/Telegram/Movie searches
- Admin panel with broadcast, statistics, and admin management
- Referral system with rewards
- API key management for developers
- Payment system with screenshot verification
- Interactive button handling for movie and telegram bots
- TXT file support for all search types
- Family member extraction
- Smart result validation
- Cascading fallback system
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
from typing import Dict, List, Optional, Tuple

from aiohttp import web, ClientSession
from telethon import TelegramClient, events, Button
from telethon.tl.types import User
from telethon.tl.functions.channels import GetParticipantRequest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

# ============ Configuration ============

PORT = int(os.getenv("PORT", "10000"))

# Bot credentials
BOT_SESSION_FILE = os.getenv("BOT_SESSION_FILE", "bot_session.session")
BOT_API_ID = int(os.getenv("API_ID", "0"))
BOT_API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# User account credentials for forwarding
USER_SESSION_FILE = os.getenv("USER_SESSION_FILE", "relay_session.session")
USER_API_ID = int(os.getenv("USER_API_ID", "0"))
USER_API_HASH = os.getenv("USER_API_HASH", "").strip()
USER_PHONE = os.getenv("USER_PHONE", "").strip()

# Admin and channel settings
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
MANDATORY_CHANNEL = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")

# Database
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://prarthanaray147_db_user:fMuTkgFsaHa5NRIy@cluster0.txn8bv3.mongodb.net/tg_bot_db?retryWrites=true&w=majority")
MONGODB_DBNAME = os.getenv("MONGODB_DBNAME", "tg_bot_db")

# Payment
PAYMENT_QR_CODE = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")

# Timeouts
FETCH_WAIT_TIME = int(os.getenv("FETCH_WAIT_TIME", "2"))
GROUP_TIMEOUT = int(os.getenv("GROUP_TIMEOUT", "500"))
REPLY_TIMEOUT = int(os.getenv("REPLY_TIMEOUT", "660"))
PROCESSING_WAIT_EXTRA = 8

# API endpoints
PHONE_API_URL = "https://daily-binny-ryuioggv-391a9381.koyeb.app/api/lookup"
PHONE_API_KEY = "616bd0f26e364c89"
VEHICLE_API_URL = "https://vehicle-6bh6.onrender.com/vehicle_info"
VEHICLE_API_KEY = "URSLASH123"

# Credits and rewards
REFERRAL_REWARD = 2
NEW_USER_CREDITS = 2

# Bot branding
BOT_FOOTER = "🔐 Powered by darkboxes_bot\n📱 Developed by darkboxesAdmin"

# ============ Logging Setup ============

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger("premium_bot")

# ============ Configuration Validation ============

if BOT_API_ID == 0 or not BOT_API_HASH:
    logger.error("API_ID and API_HASH must be set!")
    raise ValueError("Missing API_ID or API_HASH")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN must be set!")
    raise ValueError("Missing BOT_TOKEN")

USE_USER_ACCOUNT = USER_API_ID != 0 and USER_API_HASH and USER_PHONE

logger.info("=" * 80)
logger.info("🚀 PREMIUM INFORMATION BOT - STARTING UP")
logger.info("=" * 80)
logger.info("Configuration:")
logger.info(f"  Bot API_ID: {BOT_API_ID}")
logger.info(f"  Bot API_HASH: {BOT_API_HASH[:10]}...")
logger.info(f"  Admin User ID: {ADMIN_USER_ID}")
logger.info(f"  Mandatory Channel: @{MANDATORY_CHANNEL.replace('@', '')}")
if USE_USER_ACCOUNT:
    logger.info(f"  User Account: Enabled (Phone: {USER_PHONE})")
else:
    logger.info(f"  User Account: Disabled")
logger.info("=" * 80)

# ============ Destination Groups Configuration ============

DESTINATION_GROUPS = [
    {
        "name": "Main Group",
        "identifier": -1003596998816,
        "timeout": GROUP_TIMEOUT,
        "entity": None
    },
    {
        "name": "Backup Group 2",
        "identifier": "darkboxesv3",
        "timeout": GROUP_TIMEOUT,
        "entity": None
    },
    {
        "name": "Backup Group 3",
        "identifier": "nex_chats",
        "timeout": GROUP_TIMEOUT,
        "entity": None
    }
]

FAMILY_GROUP = {
    "name": "Family Info Group",
    "identifier": -1003596998816,
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

TELEGRAM_BOT = {
    "name": "Telegram Lookup Bot",
    "identifier": "@Dirgeshrai8090_bot",
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

TELEGRAM_USERNAME_GROUP = {
    "name": "Telegram Username Group",
    "identifier": "darkboxesv3",
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

MOVIE_BOT = {
    "name": "Movie/Series Bot",
    "identifier": "@iPapkornD2bot",
    "timeout": 120,
    "entity": None
}

VEHICLE_GROUP = {
    "name": "Vehicle Group",
    "identifier": "IntelXGroup",
    "timeout": GROUP_TIMEOUT,
    "entity": None
}

# ============ Search Commands Configuration ============

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Number Info",
        "type": "group",
        "commands": {
            0: "/num",
            1: "/num",
            2: "/num"
        }
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Info",
        "type": "family_group",
        "commands": {
            0: "/familyinfo"
        }
    },
    "aadhar": {
        "name": "🆔 Aadhar Info",
        "type": "group",
        "commands": {
            0: "/aadhar",
            1: "/adh",
            2: "/aadhar"
        }
    },
    "vehicle": {
        "name": "🚗 Vehicle to Phone",
        "type": "vehicle_group",
        "commands": {
            0: "/vnum"
        }
    },
    "vehicle_detail": {
        "name": "🚙 Vehicle Details",
        "type": "group",
        "commands": {
            0: "/vehicle",
            1: "/vehicle",
            2: "/vnum"
        }
    },
    "upi": {
        "name": "💳 UPI Info",
        "type": "group",
        "commands": {
            0: "/upiinfo",
            1: "/upiinfo",
            2: "/upiinfo"
        }
    },
    "fampay": {
        "name": "💰 Fampay Info",
        "type": "group",
        "commands": {
            0: "/fam",
            1: "/fam",
            2: "/fam"
        }
    },
    "email": {
        "name": "📧 Email Info",
        "type": "group",
        "commands": {
            0: "/email",
            1: "/email",
            2: "/email"
        }
    },
    "telegram": {
        "name": "📲 Telegram to Phone",
        "type": "telegram_bot",
        "commands": {
            0: "/tg"
        }
    },
    "telegram_username": {
        "name": "👤 Telegram Username Info",
        "type": "telegram_username_group",
        "commands": {
            0: "/tg"
        }
    },
    "imei": {
        "name": "📱 IMEI Info",
        "type": "group",
        "commands": {
            0: "/imei",
            1: "/imei",
            2: "/imei"
        }
    },
    "pak": {
        "name": "🇵🇰 Pakistan Info",
        "type": "group",
        "commands": {
            0: "/cnic",
            1: "/cnic",
            2: "/cnic"
        }
    },
    "gst": {
        "name": "🏢 GST Info",
        "type": "group",
        "commands": {
            0: "/gst",
            1: "/gst",
            2: "/gst"
        }
    },
    "insta": {
        "name": "📷 Instagram Info",
        "type": "group",
        "commands": {
            0: "/insta",
            1: "/insta",
            2: "/insta"
        }
    },
    "movies": {
        "name": "🎬 Movies/Web Series",
        "type": "movie_bot",
        "commands": {
            0: ""
        }
    }
}

# ============ Premium Plans ============

PLANS = {
    "plan_5": {
        "searches": 5,
        "price": 100,
        "name": "5 Searches",
        "days": None,
        "description": "5 searches - perfect for trying out"
    },
    "plan_15": {
        "searches": 15,
        "price": 200,
        "name": "15 Searches",
        "days": None,
        "description": "15 searches - great value"
    },
    "plan_week": {
        "searches": -1,
        "price": 500,
        "name": "Unlimited (7 Days)",
        "days": 7,
        "description": "Unlimited searches for 7 days"
    }
}

# ============ MongoDB Setup ============

mongo_client = None
db = None
users_col = None
payments_col = None
searches_col = None
api_keys_col = None
referrals_col = None
admins_col = None
broadcasts_col = None
settings_col = None

def init_mongo():
    """Initialize MongoDB connection and collections"""
    global mongo_client, db, users_col, payments_col, searches_col, api_keys_col, referrals_col, admins_col, broadcasts_col, settings_col
    try:
        mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client[MONGODB_DBNAME]
        
        users_col = db["users"]
        payments_col = db["payments"]
        searches_col = db["searches"]
        api_keys_col = db["api_keys"]
        referrals_col = db["referrals"]
        admins_col = db["admins"]
        broadcasts_col = db["broadcasts"]
        settings_col = db["settings"]
        
        # Create indexes
        try:
            users_col.create_index([("user_id", 1)], unique=True)
            users_col.create_index([("referral_code", 1)], unique=True, sparse=True)
            payments_col.create_index([("user_id", 1)])
            searches_col.create_index([("user_id", 1)])
            api_keys_col.create_index([("api_key", 1)], unique=True)
            api_keys_col.create_index([("user_id", 1)])
            referrals_col.create_index([("referrer_id", 1)])
            referrals_col.create_index([("referred_id", 1)])
            admins_col.create_index([("user_id", 1)], unique=True)
            broadcasts_col.create_index([("timestamp", 1)])
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
        
        logger.info("✅ MongoDB connected successfully")
    except Exception as e:
        logger.exception("❌ MongoDB connection failed: %s", e)
        raise

# ============ Admin Management System ============

async def add_admin(user_id: int) -> bool:
    """Add a user as admin"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: admins_col.update_one(
                {"user_id": user_id},
                {"\$set": {
                    "user_id": user_id,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "added_by": ADMIN_USER_ID
                }},
                upsert=True
            )
        )
        logger.info(f"✅ Admin added: {user_id}")
        return True
    except Exception as e:
        logger.exception("Error adding admin: %s", e)
        return False

async def remove_admin(user_id: int) -> bool:
    """Remove admin privileges from a user"""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, admins_col.delete_one, {"user_id": user_id}
        )
        if result.deleted_count > 0:
            logger.info(f"✅ Admin removed: {user_id}")
            return True
        return False
    except Exception as e:
        logger.exception("Error removing admin: %s", e)
        return False

async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    try:
        if user_id == ADMIN_USER_ID:
            return True
        
        admin = await asyncio.get_running_loop().run_in_executor(
            None, admins_col.find_one, {"user_id": user_id}
        )
        return admin is not None
    except Exception as e:
        logger.exception("Error checking admin: %s", e)
        return user_id == ADMIN_USER_ID

async def get_all_admins() -> List[int]:
    """Get list of all admins"""
    try:
        admins = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(admins_col.find({}, {"user_id": 1}))
        )
        return [ADMIN_USER_ID] + [admin['user_id'] for admin in admins]
    except Exception as e:
        logger.exception("Error getting admins: %s", e)
        return [ADMIN_USER_ID]

async def get_admin_stats() -> Dict:
    """Get admin statistics"""
    try:
        total_users = await asyncio.get_running_loop().run_in_executor(
            None, users_col.count_documents, {}
        )
        
        total_searches = await asyncio.get_running_loop().run_in_executor(
            None, searches_col.count_documents, {}
        )
        
        active_users = await asyncio.get_running_loop().run_in_executor(
            None, users_col.count_documents, {"total_searches": {"\$gt": 0}}
        )
        
        premium_users = await asyncio.get_running_loop().run_in_executor(
            None, users_col.count_documents, {"plan": {"\$ne": "free"}}
        )
        
        approved_payments = await asyncio.get_running_loop().run_in_executor(
            None, payments_col.count_documents, {"status": "approved"}
        )
        
        pending_payments = await asyncio.get_running_loop().run_in_executor(
            None, payments_col.count_documents, {"status": "pending"}
        )
        
        total_revenue = 0
        try:
            payments = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(payments_col.find({"status": "approved"}))
            )
            total_revenue = sum(payment.get('amount', 0) for payment in payments)
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
    except Exception as e:
        logger.exception("Error getting admin stats: %s", e)
        return {
            "total_users": 0,
            "active_users": 0,
            "premium_users": 0,
            "total_searches": 0,
            "approved_payments": 0,
            "pending_payments": 0,
            "total_revenue": 0
        }

async def broadcast_message(message: str, exclude_user_id: int = None) -> Dict:
    """Broadcast message to all users"""
    try:
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(users_col.find({}))
        )
        
        sent = 0
        failed = 0
        
        # Add footer to broadcast
        final_message = f"{message}\n\n{BOT_FOOTER}"
        
        for user_doc in users:
            user_id = user_doc.get('user_id')
            
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            try:
                await bot_client.send_message(user_id, final_message)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.debug(f"Could not send to {user_id}: {e}")
        
        # Log broadcast
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, broadcasts_col.insert_one, {
                    "message": message,
                    "sent_to": sent,
                    "failed": failed,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sent_by": exclude_user_id
                }
            )
        except:
            pass
        
        logger.info(f"📢 Broadcast: Sent {sent}, Failed {failed}")
        return {"sent": sent, "failed": failed}
    except Exception as e:
        logger.exception("Error broadcasting: %s", e)
        return {"sent": 0, "failed": 0}

# ============ Referral System ============

def generate_referral_code() -> str:
    """Generate unique referral code"""
    return secrets.token_urlsafe(6).upper()

async def get_or_create_referral_code(user_id: int) -> Optional[str]:
    """Get or create referral code for user"""
    try:
        user = await get_user(user_id)
        if user and user.get('referral_code'):
            return user['referral_code']
        
        while True:
            code = generate_referral_code()
            existing = await asyncio.get_running_loop().run_in_executor(
                None, users_col.find_one, {"referral_code": code}
            )
            if not existing:
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: users_col.update_one(
                        {"user_id": user_id},
                        {"\$set": {"referral_code": code}}
                    )
                )
                return code
    except Exception as e:
        logger.exception("Error generating referral code: %s", e)
        return None

async def apply_referral(referred_user_id: int, referral_code: str) -> bool:
    """Apply referral code to new user"""
    try:
        referrer = await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"referral_code": referral_code.upper()}
        )
        
        if not referrer:
            return False
        
        referrer_id = referrer['user_id']
        if referrer_id == referred_user_id:
            return False
        
        user = await get_user(referred_user_id)
        if user.get('referred_by'):
            return False
        
        await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.insert_one, {
                "referrer_id": referrer_id,
                "referred_id": referred_user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reward_given": False
            }
        )
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referred_user_id},
                {"\$set": {"referred_by": referrer_id}}
            )
        )
        
        logger.info(f"✅ Referral applied: {referrer_id} -> {referred_user_id}")
        return True
    except Exception as e:
        logger.exception("Error applying referral: %s", e)
        return False

async def reward_referrer(referred_user_id: int) -> bool:
    """Give referral reward to referrer"""
    try:
        referral = await asyncio.get_running_loop().run_in_executor(
            None, referrals_col.find_one, {"referred_id": referred_user_id, "reward_given": False}
        )
        
        if not referral:
            return False
        
        referrer_id = referral['referrer_id']
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": referrer_id},
                {"\$inc": {"searches_remaining": REFERRAL_REWARD}}
            )
        )
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: referrals_col.update_one(
                {"_id": referral['_id']},
                {"\$set": {"reward_given": True, "rewarded_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        
        try:
            await bot_client.send_message(
                referrer_id,
                f"🎉 Congratulations!\n\n"
                f"You earned {REFERRAL_REWARD} credits because someone used your referral link!\n\n"
                f"Keep sharing to earn more! 💰"
            )
        except:
            pass
        
        logger.info(f"💰 Referral reward: {referrer_id} earned {REFERRAL_REWARD}")
        return True
    except Exception as e:
        logger.exception("Error rewarding referrer: %s", e)
        return False

async def get_referral_stats(user_id: int) -> Dict:
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
            "pending": total_referrals - rewarded_referrals,
            "earnings": rewarded_referrals * REFERRAL_REWARD
        }
    except Exception as e:
        logger.exception("Error getting referral stats: %s", e)
        return {"total": 0, "rewarded": 0, "pending": 0, "earnings": 0}

# ============ API Key Management ============

async def create_api_key(user_id: int, name: str = "Default Key") -> Optional[str]:
    """Create new API key"""
    try:
        api_key = f"sk_{secrets.token_urlsafe(32)}"
        doc = {
            "api_key": api_key,
            "user_id": user_id,
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "searches_used": 0,
            "active": True,
            "last_used": None,
            "total_requests": 0
        }
        await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.insert_one, doc
        )
        logger.info(f"✅ API key created for {user_id}")
        return api_key
    except Exception as e:
        logger.exception("Error creating API key: %s", e)
        return None

async def get_api_key_info(api_key: str) -> Optional[Dict]:
    """Get API key information"""
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, api_keys_col.find_one, {"api_key": api_key}
        )
    except Exception as e:
        logger.exception("Error fetching API key: %s", e)
        return None

async def list_user_api_keys(user_id: int) -> List[Dict]:
    """List all API keys for user"""
    try:
        keys = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(api_keys_col.find({"user_id": user_id}))
        )
        return keys
    except Exception as e:
        logger.exception("Error listing API keys: %s", e)
        return []

async def delete_api_key(api_key: str, user_id: int) -> bool:
    """Delete API key"""
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

async def increment_api_key_usage(api_key: str) -> bool:
    """Increment API key usage counter"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: api_keys_col.update_one(
                {"api_key": api_key},
                {
                    "\$inc": {"searches_used": 1, "total_requests": 1},
                    "\$set": {"last_used": datetime.now(timezone.utc).isoformat()}
                }
            )
        )
        return True
    except Exception as e:
        logger.exception("Error incrementing API usage: %s", e)
        return False

# ============ User Management ============

async def get_user(user_id: int) -> Optional[Dict]:
    """Get user by ID"""
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, users_col.find_one, {"user_id": user_id}
        )
    except Exception as e:
        logger.exception("Error fetching user: %s", e)
        return None

async def create_or_update_user(user_id: int, username: str = None, first_name: str = None) -> Optional[Dict]:
    """Create or update user"""
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
            "last_activity": datetime.now(timezone.utc).isoformat(),
            "blocked": False
        }
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"\$setOnInsert": doc},
                upsert=True
            )
        )
        logger.info(f"✅ User created/updated: {user_id}")
        return await get_user(user_id)
    except Exception as e:
        logger.exception("Error creating user: %s", e)
        return None

async def update_user_plan(user_id: int, plan: str, searches: int, days: int = None) -> bool:
    """Update user plan"""
    try:
        update_doc = {
            "plan": plan,
            "searches_remaining": searches,
            "last_activity": datetime.now(timezone.utc).isoformat()
        }
        if days:
            update_doc["plan_expiry"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        else:
            update_doc["plan_expiry"] = None
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"\$set": update_doc}
            )
        )
        logger.info(f"✅ Plan updated for {user_id}: {plan}")
        return True
    except Exception as e:
        logger.exception("Error updating user plan: %s", e)
        return False

async def decrement_search(user_id: int) -> bool:
    """Decrement user search count"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {
                    "\$inc": {"searches_remaining": -1, "total_searches": 1},
                    "\$set": {"last_activity": datetime.now(timezone.utc).isoformat()}
                }
            )
        )
        return True
    except Exception as e:
        logger.exception("Error decrementing search: %s", e)
        return False

async def log_search(user_id: int, search_type: str, query: str, result: str) -> bool:
    """Log user search"""
    try:
        doc = {
            "user_id": user_id,
            "search_type": search_type,
            "query": query,
            "result": result[:1000],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result_length": len(result)
        }
        await asyncio.get_running_loop().run_in_executor(
            None, searches_col.insert_one, doc
        )
        return True
    except Exception as e:
        logger.exception("Error logging search: %s", e)
        return False

async def create_payment_request(user_id: int, plan: str, amount: int) -> Optional[str]:
    """Create payment request"""
    try:
        doc = {
            "payment_id": uuid.uuid4().hex,
            "user_id": user_id,
            "plan": plan,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_file_id": None,
            "approved_at": None,
            "rejected_at": None
        }
        result = await asyncio.get_running_loop().run_in_executor(
            None, payments_col.insert_one, doc
        )
        logger.info(f"💳 Payment request created: {doc['payment_id']}")
        return doc["payment_id"]
    except Exception as e:
        logger.exception("Error creating payment: %s", e)
        return None

async def update_payment_screenshot(payment_id: str, file_id: str) -> bool:
    """Update payment with screenshot"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"\$set": {"screenshot_file_id": file_id, "screenshot_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        return True
    except Exception as e:
        logger.exception("Error updating payment screenshot: %s", e)
        return False

async def check_telegram_daily_limit(user_id: int) -> bool:
    """Check if user has exceeded daily telegram search limit"""
    try:
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        
        count = await asyncio.get_running_loop().run_in_executor(
            None, lambda: searches_col.count_documents({
                "user_id": user_id,
                "search_type": {"\$in": ["telegram", "telegram_username"]},
                "timestamp": {"\$gte": today_start.isoformat()}
            })
        )
        return count >= 1
    except Exception as e:
        logger.exception("Error checking telegram daily limit: %s", e)
        return False

async def get_telegram_search_reset_time(user_id: int) -> str:
    """Get telegram search reset time"""
    try:
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        tomorrow_start = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=timezone.utc)
        time_diff = tomorrow_start - datetime.now(timezone.utc)
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)
        return f"{hours}h {minutes}m"
    except:
        return "24h"

async def get_user_search_history(user_id: int, limit: int = 10) -> List[Dict]:
    """Get user search history"""
    try:
        searches = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(
                searches_col.find({"user_id": user_id})
                .sort("timestamp", -1)
                .limit(limit)
            )
        )
        return searches
    except Exception as e:
        logger.exception("Error getting search history: %s", e)
        return []

async def block_user(user_id: int) -> bool:
    """Block user from using bot"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"\$set": {"blocked": True}}
            )
        )
        logger.info(f"🚫 User blocked: {user_id}")
        return True
    except Exception as e:
        logger.exception("Error blocking user: %s", e)
        return False

async def unblock_user(user_id: int) -> bool:
    """Unblock user"""
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: users_col.update_one(
                {"user_id": user_id},
                {"\$set": {"blocked": False}}
            )
        )
        logger.info(f"✅ User unblocked: {user_id}")
        return True
    except Exception as e:
        logger.exception("Error unblocking user: %s", e)
        return False

# ============ Response Detection & Validation ============

def is_processing_message(text: str) -> bool:
    """Check if message is a processing/loading message"""
    if not text:
        return False
    
    text_lower = text.lower()
    processing_keywords = [
        'processing', 'please wait', 'fetching', 'loading', 'searching',
        'retrieving', 'hold on', 'wait a moment', 'in progress', 'gathering data',
        'working on it', '⏳', '🔍', 'searching for', 'processing your request',
        'checking', 'verifying', 'validating'
    ]
    
    if len(text.strip()) < 20:
        return True
    
    for keyword in processing_keywords:
        if keyword in text_lower:
            return True
    
    if text.strip().startswith('/'):
        return True
    
    return False

def is_no_info_message(text: str) -> bool:
    """Check if message is a no-info/error message"""
    if not text:
        return False
    
    text_lower = text.lower()
    no_info_keywords = [
        'no info', 'no information', 'not found', 'no data', 'no result', 'no record',
        'invalid', 'doesn\'t exist', 'does not exist', 'not available', 'no details',
        'unable to find', 'could not find', 'couldn\'t find', 'no match', 'not exist',
        'no information found', 'no result found', 'no records found', 'to reduce spam',
        'must have joined', 'must join', 'join all channels', 'join our channel',
        'verify your account', 'admin to verify', 'need to join', 'required to join',
        'subscription required', 'access denied', 'error', 'failed', 'invalid input',
        'no such user', 'user not found', 'doesn\'t exist', 'not a valid'
    ]
    
    return any(keyword in text_lower for keyword in no_info_keywords)

def is_valid_result(text: str, search_type: str) -> bool:
    """Validate if text is a valid search result"""
    if not text:
        return False
    
    if is_processing_message(text):
        return False
    
    if is_no_info_message(text):
        return False
    
    if len(text.strip()) < 20:
        return False
    
    # Family search specific validation
    if search_type == 'family':
        text_lower = text.lower()
        family_patterns = [
            'father', 'mother', 'son', 'daughter', 'brother', 'sister',
            'wife', 'husband', 'self', '(m)', '(f)', '(male)', '(female)',
            'relative', 'member', 'family'
        ]
        
        lines = text.strip().split('\n')
        member_count = sum(1 for line in lines if any(pattern in line.lower() for pattern in family_patterns))
        
        if member_count >= 1:
            logger.info(f"✅ Family search valid: {member_count} members")
            return True
        
        if any(line.strip().startswith(('•', '-', '*')) for line in lines):
            logger.info(f"✅ Family search valid: formatted list")
            return True
    
    # General data indicators
    data_indicators = [
        'name', 'mobile', 'phone', 'address', 'email', 'father', 'owner',
        'vehicle', 'registration', 'chassis', 'model', 'manufacturer',
        'policy', 'insurance', 'aadhar', 'upi', 'telegram', 'instagram',
        'gst', 'status', 'found', 'count', 'records', 'data', 'info',
        'number', 'date', 'city', 'state', 'country', 'age', 'gender'
    ]
    
    text_lower = text.lower()
    indicator_count = sum(1 for indicator in data_indicators if indicator in text_lower)
    
    if indicator_count >= 1:
        logger.info(f"✅ Valid result: {indicator_count} data indicators")
        return True
    
    return False

# ============ Text Processing & Cleaning ============

def filter_links_and_usernames(text: str) -> str:
    """Remove links and usernames from text"""
    if not text:
        return text

    patterns = [
        r'https?://[^\s]+',
        r'www\.[^\s]+',
        r't\.me/[^\s]+',
        r'@[a-zA-Z0-9_]{3,32}',
        r'telegram\.me/[^\s]+',
        r'tg://[^\s]+',
        r'#[a-zA-Z0-9_]+',
    ]

    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)

    lines = cleaned.splitlines()
    safe_lines = []

    for line in lines:
        l = line.strip()
        if l:
            safe_lines.append(line)

    cleaned = "\n".join(safe_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()

    return cleaned

def clean_file_content(text: str) -> str:
    """Clean content downloaded from files"""
    if not text:
        return text
    
    # Remove URLs
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r't\.me/\S+', '', text)
    text = re.sub(r'tg://\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'#\w+', '', text)
    
    # Remove promotional lines
    promotional = [
        'powered by', 'developed by', 'designed by', 'created by',
        'follow us', 'subscribe', 'join us', 'contact', 'admin',
        'for more', 'click here', 'visit', 'telegram', 'copyright'
    ]
    
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(keyword in line.lower() for keyword in promotional):
            continue
        if line.startswith('=') or line.startswith('--'):
            continue
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()

def extract_family_members(text: str) -> str:
    """Extract family member information from text"""
    if not text:
        return text
    
    lines = text.splitlines()
    family_members = []
    
    family_keywords = [
        'father', 'mother', 'son', 'daughter', 'brother', 'sister',
        'wife', 'husband', 'self', 'not available', 'unknown', 'member'
    ]
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            continue
        
        # Skip headers and metadata
        if any(keyword in stripped.lower() for keyword in [
            'family report', 'head:', 'rc no:', 'generated', 'tar',
            'mobile info', 'created', 'updated', 'last modified'
        ]):
            continue
        
        # Accept family member lines
        if stripped.startswith(('•', '-', '*', '→', '▪')) or \
           any(keyword in stripped.lower() for keyword in family_keywords):
            family_members.append(stripped)
    
    if family_members:
        logger.info(f"👨‍👩‍👧 Extracted {len(family_members)} family members")
        return '\n'.join(family_members)
    
    # If no formatted members found, return original
    return text

def add_footer(result: str) -> str:
    """Add bot footer to results"""
    if not result:
        return result
    return f"{result}\n\n{'─' * 40}\n{BOT_FOOTER}"

def format_phone_api_response(data: Dict, phone_number: str) -> Optional[str]:
    """Format phone API response"""
    try:
        result = f"📱 Phone Number Information\n\nNumber: {phone_number}\n\n"

        if isinstance(data, dict):
            # Remove metadata
            for key in ['Developer', 'Powered_By', 'developer', 'powered_by', 'success', 'status']:
                data.pop(key, None)

            if 'Result' in data and isinstance(data['Result'], list):
                records = data['Result']
                if records:
                    result += f"Found {len(records)} record(s):\n\n"

                    for idx, record in enumerate(records, 1):
                        if len(records) > 1:
                            result += f"━━━ Record {idx} ━━━\n"

                        if record.get('name'):
                            result += f"👤 Name: {record['name'].strip()}\n"
                        if record.get('mobile'):
                            result += f"📱 Mobile: {record['mobile']}\n"
                        if record.get('alt_mobile'):
                            result += f"📞 Alt Mobile: {record['alt_mobile']}\n"
                        if record.get('circle'):
                            result += f"📡 Circle: {record['circle']}\n"
                        if record.get('father_name'):
                            result += f"👨 Father: {record['father_name']}\n"
                        if record.get('address'):
                            addr = record['address'].replace('!', ', ').strip(', ')
                            result += f"🏠 Address: {addr}\n"
                        if record.get('email'):
                            result += f"📧 Email: {record['email']}\n"
                        if record.get('operator'):
                            result += f"📡 Operator: {record['operator']}\n"

                        if idx < len(records):
                            result += "\n"
                else:
                    result += "No records found.\n"
            else:
                for key, value in data.items():
                    if key.lower() not in ['status', 'success']:
                        result += f"{key.replace('_', ' ').title()}: {value}\n"
        
        return filter_links_and_usernames(result)

    except Exception as e:
        logger.exception(f"Error formatting phone API response: {e}")
        return None

def format_vehicle_api_response(data: Dict, vehicle_no: str) -> Optional[str]:
    """Format vehicle API response"""
    try:
        result = f"🚗 VEHICLE DETAILS: {vehicle_no}\n\n"

        if not isinstance(data, dict):
            return None

        for k in ['Developer', 'Powered_By', 'developer', 'powered_by', 'success', 'status']:
            data.pop(k, None)

        # Owner information
        if data.get('owner_name') or data.get('mobile_number'):
            if data.get('owner_name'):
                result += f"👤 Owner: {data['owner_name']}\n"
            if data.get('mobile_number'):
                result += f"📱 Mobile: {data['mobile_number']}\n"
        
        # Address
        if data.get('address'):
            addr = data['address'].replace('!', ', ').strip(', ')
            result += f"🏠 Address: {addr}\n"
        
        # Vehicle specs
        if data.get('manufacturer'):
            result += f"🔧 Manufacturer: {data['manufacturer']}\n"
        if data.get('model'):
            result += f"📋 Model: {data['model']}\n"
        if data.get('registration_date'):
            result += f"📅 Reg Date: {data['registration_date']}\n"
        if data.get('registration_valid_till'):
            result += f"✅ Valid Till: {data['registration_valid_till']}\n"
        
        return filter_links_and_usernames(result)

    except Exception as e:
        logger.exception("Vehicle formatter error: %s", e)
        return None

# ============ Bot State ============

user_states: Dict = {}
pending_searches: Dict = {}
interactive_sessions: Dict = {}

# ============ Telethon Clients ============

bot_client = TelegramClient(BOT_SESSION_FILE, BOT_API_ID, BOT_API_HASH)

if USE_USER_ACCOUNT:
    user_client = TelegramClient(USER_SESSION_FILE, USER_API_ID, USER_API_HASH)
else:
    user_client = bot_client

async def check_channel_membership(user_id: int) -> bool:
    """Check if user is member of mandatory channel"""
    try:
        channel = await bot_client.get_entity(MANDATORY_CHANNEL)
        
        try:
            participant = await bot_client(
                GetParticipantRequest(channel, user_id)
            )
            from telethon.tl.types import ChannelParticipantBanned, ChannelParticipantLeft
            
            if isinstance(participant.participant, (ChannelParticipantBanned, ChannelParticipantLeft)):
                return False
            
            return True
            
        except Exception:
            logger.debug(f"User {user_id} is not in channel")
            return False
        
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

# ============ API Functions ============

async def fetch_phone_api(phone_number: str) -> Optional[str]:
    """Fetch phone info from API"""
    try:
        async with ClientSession() as session:
            headers = {"X-API-Key": PHONE_API_KEY}
            params = {"phone": phone_number}
            
            async with session.get(PHONE_API_URL, headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return format_phone_api_response(data, phone_number)
                else:
                    logger.warning(f"Phone API returned {resp.status}")
    except Exception as e:
        logger.exception(f"Phone API error: {e}")
    return None

async def fetch_vehicle_api(vehicle_no: str) -> Optional[str]:
    """Fetch vehicle info from API"""
    try:
        async with ClientSession() as session:
            headers = {"X-API-Key": VEHICLE_API_KEY}
            params = {"vehicle_number": vehicle_no}
            
            async with session.get(VEHICLE_API_URL, headers=headers, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return format_vehicle_api_response(data, vehicle_no)
                else:
                    logger.warning(f"Vehicle API returned {resp.status}")
    except Exception as e:
        logger.exception(f"Vehicle API error: {e}")
    return None

# ============ Keyboard Menus ============

def get_main_menu() -> List[List[Button]]:
    """Get main menu keyboard"""
    buttons = []
    row = []
    for key, info in SEARCH_COMMANDS.items():
        row.append(Button.inline(info["name"], f"search_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([
        Button.inline("🔑 API Keys", "api_menu"),
        Button.inline("👥 Referrals", "referral_menu")
    ])
    buttons.append([Button.inline("ℹ️ Help", "help_menu")])
    
    return buttons

def get_admin_menu() -> List[List[Button]]:
    """Get admin menu keyboard"""
    return [
        [
            Button.inline("📢 Broadcast", "admin_broadcast"),
            Button.inline("📊 Statistics", "admin_stats")
        ],
        [
            Button.inline("👨‍💼 Manage Admins", "admin_manage_admins"),
            Button.inline("🚫 Block User", "admin_block_user")
        ],
        [
            Button.inline("💳 Payments", "admin_payments"),
            Button.inline("📜 Logs", "admin_logs")
        ],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_api_menu() -> List[List[Button]]:
    """Get API menu keyboard"""
    return [
        [Button.inline("➕ Create API Key", "api_create")],
        [Button.inline("📋 List API Keys", "api_list")],
        [Button.inline("📚 Documentation", "api_docs")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_referral_menu() -> List[List[Button]]:
    """Get referral menu keyboard"""
    return [
        [Button.inline("📊 My Stats", "referral_stats")],
        [Button.inline("🔗 Get Referral Link", "referral_link")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_help_menu() -> List[List[Button]]:
    """Get help menu keyboard"""
    return [
        [Button.inline("❓ How to use", "help_usage")],
        [Button.inline("💰 Pricing", "help_pricing")],
        [Button.inline("📞 Support", "help_support")],
        [Button.inline("🔙 Back to Main Menu", "back_main")]
    ]

def get_plans_menu() -> List[List[Button]]:
    """Get plans menu keyboard"""
    buttons = []
    for plan_key, plan_info in PLANS.items():
        buttons.append([Button.inline(
            f"{plan_info['name']} - ₹{plan_info['price']}", 
            f"buy_{plan_key}"
        )])
    buttons.append([Button.inline("❌ Cancel", "cancel")])
    return buttons

def get_payment_approval_buttons(payment_id: str, user_id: int) -> List[List[Button]]:
    """Get payment approval buttons"""
    return [
        [
            Button.inline("✅ Approve", f"approve_{payment_id}_{user_id}"),
            Button.inline("❌ Reject", f"reject_{payment_id}_{user_id}")
        ]
    ]

def get_admin_manage_buttons() -> List[List[Button]]:
    """Get admin manage buttons"""
    return [
        [Button.inline("➕ Add Admin", "admin_add_admin")],
        [Button.inline("➖ Remove Admin", "admin_remove_admin")],
        [Button.inline("📋 List Admins", "admin_list_admins")],
        [Button.inline("🔙 Back", "admin_menu")]
    ]

# ============ Core Search Function ============

async def perform_search(search_type: str, query: str, user_id: int = None) -> Dict:
    """Perform search across all groups"""
    if search_type not in SEARCH_COMMANDS:
        return {"success": False, "error": "Invalid search type"}
    
    command_info = SEARCH_COMMANDS[search_type]
    search_dest_type = command_info.get('type', 'group')
    
    logger.info(f"🔍 Starting search: {search_type} = {query}")
    
    # Interactive searches (movie, telegram)
    if search_dest_type == 'movie_bot':
        return await perform_interactive_movie_search(query, user_id)
    elif search_dest_type == 'telegram_bot':
        return await perform_interactive_telegram_search(query, user_id)
    elif search_dest_type == 'telegram_username_group':
        return await perform_telegram_username_search(query, user_id)
    
    # Regular searches with file support
    if search_dest_type == 'family_group':
        destinations = [FAMILY_GROUP]
    elif search_dest_type == 'vehicle_group':
        destinations = [VEHICLE_GROUP]
    else:
        destinations = DESTINATION_GROUPS
    
    for idx, dest_config in enumerate(destinations):
        dest_entity = dest_config.get('entity')
        if not dest_entity:
            logger.warning(f"❌ Destination {idx} ({dest_config['name']}) not resolved")
            continue
        
        command_prefix = command_info['commands'].get(idx)
        if not command_prefix:
            logger.warning(f"❌ No command for {search_type} in group {idx}")
            continue
        
        command = f"{command_prefix} {query}"
        base_timeout = dest_config.get('timeout', GROUP_TIMEOUT)
        
        try:
            forwarded = await user_client.send_message(dest_entity, command)
            logger.info(f"📤 Sent to {dest_config['name']}: {command}")
            
            future = asyncio.get_running_loop().create_future()
            search_id = f"{forwarded.id}_{int(time.time() * 1000)}_{idx}"
            
            pending_searches[search_id] = {
                "future": future,
                "user_id": user_id,
                "query": query,
                "search_type": search_type,
                "timestamp": time.time(),
                "group_name": dest_config['name'],
                "message_id": forwarded.id,
                "chat_entity": dest_entity
            }
            
            logger.info(f"📝 Registered search: {search_id}")
            
            try:
                result_text = await asyncio.wait_for(future, timeout=base_timeout)
                logger.info(f"✅ Response received from {dest_config['name']}")
                
                if not isinstance(result_text, str):
                    result_text = str(result_text)
                
                # Validate result
                if is_valid_result(result_text, search_type):
                    cleaned = filter_links_and_usernames(result_text)
                    final_result = add_footer(cleaned)
                    
                    if user_id:
                        await log_search(user_id, search_type, query, cleaned)
                    
                    pending_searches.pop(search_id, None)
                    
                    logger.info(f"✅ Valid result from {dest_config['name']}")
                    return {
                        "success": True, 
                        "result": final_result, 
                        "search_type": search_type, 
                        "source": dest_config['name']
                    }
                else:
                    logger.warning(f"⚠️ Invalid result format from {dest_config['name']}")
                    pending_searches.pop(search_id, None)
                    
                    # Try next group
                    if idx < len(destinations) - 1:
                        logger.info(f"➡️ Trying next group: {destinations[idx + 1]['name']}")
                        continue
                    else:
                        # Try API fallback
                        logger.info(f"🔄 Trying API fallback")
                        if search_type in ['phone', 'telegram']:
                            api_result = await fetch_phone_api(query)
                            if api_result:
                                final_result = add_footer(api_result)
                                return {"success": True, "result": final_result, "search_type": search_type, "source": "Phone API"}
                        
                        return {"success": False, "error": "No valid result found. Try another query."}
            
            except asyncio.TimeoutError:
                pending_searches.pop(search_id, None)
                logger.warning(f"⏱️ Timeout from {dest_config['name']} ({base_timeout}s)")
                
                if idx == len(destinations) - 1:
                    return {"success": False, "error": "Request timed out. Please try again."}
                continue
        
        except Exception as e:
                        logger.exception(f"Error searching in {dest_config['name']}: {e}")
            pending_searches.pop(search_id, None)
            
            if idx == len(destinations) - 1:
                return {"success": False, "error": "Search failed. Please try again."}
            continue
    
    return {"success": False, "error": "No result found. Please try another query."}

async def perform_interactive_telegram_search(query: str, user_id: int) -> Dict:
    """Perform interactive telegram search with button handling"""
    if await check_telegram_daily_limit(user_id):
        reset_time = await get_telegram_search_reset_time(user_id)
        return {"success": False, "error": f"⏰ Daily limit reached (1/day).\n\n🔄 Reset in: {reset_time}"}
    
    bot_entity = TELEGRAM_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Telegram bot not configured"}
    
    try:
        command = f"/tg {query}"
        await user_client.send_message(bot_entity, command)
        logger.info(f"📤 Sent telegram search: {query}")
        
        await asyncio.sleep(3)
        
        messages = await user_client.get_messages(bot_entity, limit=15)
        for msg in messages:
            if msg.buttons:
                logger.info(f"🔘 Found inline buttons")
                
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "telegram",
                    "query": query,
                    "user_id": user_id
                }
                
                user_buttons = []
                for row_idx, row in enumerate(msg.buttons):
                    button_row = []
                    for col_idx, button in enumerate(row):
                        if hasattr(button, 'text'):
                            button_row.append(Button.inline(
                                button.text, 
                                f"relay_tg_{row_idx}_{col_idx}"
                            ))
                    if button_row:
                        user_buttons.append(button_row)
                
                return {
                    "success": False,
                    "needs_interaction": True,
                    "message": msg.text or "Select an option:",
                    "buttons": user_buttons
                }
            
            if msg.text and len(msg.text.strip()) > 30:
                if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                    result = filter_links_and_usernames(msg.text)
                    final_result = add_footer(result)
                    await log_search(user_id, "telegram", query, result)
                    return {"success": True, "result": final_result, "search_type": "telegram", "source": "Telegram Bot"}
        
        return {"success": False, "error": "No response from telegram bot"}
    
    except Exception as e:
        logger.exception(f"Telegram search error: {e}")
        return {"success": False, "error": str(e)}

async def perform_interactive_movie_search(query: str, user_id: int) -> Dict:
    """Perform interactive movie search with button handling"""
    bot_entity = MOVIE_BOT.get('entity')
    if not bot_entity:
        return {"success": False, "error": "Movie bot not configured"}
    
    try:
        await user_client.send_message(bot_entity, query)
        logger.info(f"📤 Sent movie search: {query}")
        
        await asyncio.sleep(5)
        
        messages = await user_client.get_messages(bot_entity, limit=20)
        
        for msg in messages:
            if msg.buttons:
                logger.info(f"🎬 Found movie buttons")
                
                interactive_sessions[user_id] = {
                    "dest_message": msg,
                    "dest_entity": bot_entity,
                    "type": "movie",
                    "query": query,
                    "user_id": user_id
                }
                
                user_buttons = []
                for row_idx, row in enumerate(msg.buttons):
                    button_row = []
                    for col_idx, button in enumerate(row):
                        if hasattr(button, 'text'):
                            button_row.append(Button.inline(
                                button.text,
                                f"relay_movie_{row_idx}_{col_idx}"
                            ))
                    if button_row:
                        user_buttons.append(button_row)
                
                return {
                    "success": False,
                    "needs_interaction": True,
                    "message": msg.text or "Select a movie:",
                    "buttons": user_buttons
                }
            
            if msg.text and len(msg.text.strip()) > 30:
                if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                    result = filter_links_and_usernames(msg.text)
                    final_result = add_footer(result)
                    return {"success": True, "result": final_result, "search_type": "movies", "source": "Movie Bot"}
        
        return {"success": False, "error": "No response from movie bot"}
    
    except Exception as e:
        logger.exception(f"Movie search error: {e}")
        return {"success": False, "error": str(e)}

async def perform_telegram_username_search(query: str, user_id: int) -> Dict:
    """Perform telegram username search"""
    if await check_telegram_daily_limit(user_id):
        reset_time = await get_telegram_search_reset_time(user_id)
        return {"success": False, "error": f"⏰ Daily limit. Reset in: {reset_time}"}
    
    group_entity = TELEGRAM_USERNAME_GROUP.get('entity')
    if not group_entity:
        return {"success": False, "error": "Username group not configured"}
    
    try:
        command = f"/tg {query}"
        await user_client.send_message(group_entity, command)
        logger.info(f"📤 Sent telegram username search: {query}")
        
        await asyncio.sleep(3)
        
        messages = await user_client.get_messages(group_entity, limit=15)
        for msg in messages:
            if msg.text and len(msg.text.strip()) > 30:
                if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                    result = filter_links_and_usernames(msg.text)
                    final_result = add_footer(result)
                    await log_search(user_id, "telegram_username", query, result)
                    return {"success": True, "result": final_result, "search_type": "telegram_username"}
        
        return {"success": False, "error": "No information found for this username"}
    
    except Exception as e:
        logger.exception(f"Username search error: {e}")
        return {"success": False, "error": str(e)}

# ============ Bot Event Handlers ============

@bot_client.on(events.NewMessage(pattern=r'/start( (.+))?'))
async def start_handler(event):
    """Handle /start command"""
    user = await event.get_sender()
    user_id = user.id
    
    user_doc = await get_user(user_id)
    if not user_doc:
        await create_or_update_user(user_id, user.username, user.first_name)
    
    # Check for referral code
    if event.pattern_match.group(2):
        referral_code = event.pattern_match.group(2).strip()
        await apply_referral(user_id, referral_code)
    
    user_doc = await get_user(user_id)
    
    # Check if user is blocked
    if user_doc.get('blocked'):
        await event.respond("❌ You have been blocked from using this bot.")
        return
    
    # Admin check
    admin_check = await is_admin(user_id)
    if admin_check:
        await event.respond(
            f"👋 Welcome Admin {user.first_name}!\n\n"
            f"Full access enabled.",
            buttons=get_admin_menu()
        )
        return
    
    # Channel membership check
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.respond(
            f"👋 Welcome to Premium Info Bot!\n\n"
            f"To use this bot, join our channel first:\n\n"
            f"@{MANDATORY_CHANNEL.replace('@', '')}",
            buttons=[
                [Button.url("📢 Join Channel", f"https://t.me/{MANDATORY_CHANNEL.replace('@', '')}")],
                [Button.inline("✅ I've Joined", "check_membership")]
            ]
        )
        return
    
    # Mark channel as joined
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one({"user_id": user_id}, {"$set": {"channel_joined": True}})
    )
    
    await event.respond(
        f"👋 Welcome {user.first_name}!\n\n"
        f"📊 Your Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits Remaining: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        f"Select what you want to search:",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^admin_stats'))
async def admin_stats_handler(event):
    """Handle admin stats request"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    stats = await get_admin_stats()
    message = (
        f"📊 BOT STATISTICS\n\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"🟢 Active Users: {stats['active_users']}\n"
        f"💎 Premium Users: {stats['premium_users']}\n"
        f"🔍 Total Searches: {stats['total_searches']}\n\n"
        f"💳 PAYMENTS\n"
        f"✅ Approved: {stats['approved_payments']}\n"
        f"⏳ Pending: {stats['pending_payments']}\n"
        f"💰 Total Revenue: ₹{stats['total_revenue']}\n\n"
        f"📢 Mandatory Channel: @{MANDATORY_CHANNEL.replace('@', '')}"
    )
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "back_main")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_broadcast'))
async def admin_broadcast_handler(event):
    """Handle broadcast message request"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_broadcast"}
    await event.edit("📢 Send the message you want to broadcast to all users:")

@bot_client.on(events.CallbackQuery(pattern='^admin_manage_admins'))
async def admin_manage_admins_handler(event):
    """Handle admin management"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    await event.edit("👨‍💼 Admin Management", buttons=get_admin_manage_buttons())

@bot_client.on(events.CallbackQuery(pattern='^admin_add_admin'))
async def admin_add_admin_handler(event):
    """Handle add admin request"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_admin_user_id"}
    await event.edit("👨‍💼 Send the User ID to make them an admin:")

@bot_client.on(events.CallbackQuery(pattern='^admin_list_admins'))
async def admin_list_admins_handler(event):
    """Handle list admins request"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    admins = await get_all_admins()
    message = f"👨‍💼 Admins ({len(admins)}):\n\n"
    for admin_id in admins:
        if admin_id == ADMIN_USER_ID:
            message += f"• {admin_id} (Owner)\n"
        else:
            message += f"• {admin_id}\n"
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "admin_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^admin_block_user'))
async def admin_block_user_handler(event):
    """Handle block user request"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    user_states[event.sender_id] = {"action": "awaiting_block_user_id"}
    await event.edit("🚫 Send the User ID to block:")

@bot_client.on(events.CallbackQuery(pattern='^admin_payments'))
async def admin_payments_handler(event):
    """Handle payments management"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    try:
        pending = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(payments_col.find({"status": "pending"}).limit(5))
        )
        
        if not pending:
            await event.edit("✅ No pending payments", buttons=[[Button.inline("🔙 Back", "admin_menu")]])
            return
        
        message = f"💳 Pending Payments ({len(pending)}):\n\n"
        buttons = []
        
        for payment in pending:
            plan_info = PLANS.get(payment['plan'], {})
            user_id = payment['user_id']
            message += f"User: {user_id}\n"
            message += f"Plan: {plan_info.get('name', 'Unknown')}\n"
            message += f"Amount: ₹{payment['amount']}\n"
            message += f"ID: {payment['payment_id'][:8]}...\n\n"
            
            buttons.append([
                Button.inline("✅ Approve", f"approve_{payment['payment_id']}_{user_id}"),
                Button.inline("❌ Reject", f"reject_{payment['payment_id']}_{user_id}")
            ])
        
        buttons.append([Button.inline("🔙 Back", "admin_menu")])
        await event.edit(message, buttons=buttons)
    
    except Exception as e:
        logger.exception(f"Error in payments handler: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^referral_menu'))
async def referral_menu_handler(event):
    """Handle referral menu"""
    await event.edit(
        f"👥 Referral System\n\n"
        f"Earn {REFERRAL_REWARD} credits for each friend!\n\n"
        f"Share your link and when they perform their first search, you get rewarded.",
        buttons=get_referral_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_link'))
async def referral_link_handler(event):
    """Handle get referral link"""
    user_id = event.sender_id
    referral_code = await get_or_create_referral_code(user_id)
    
    if referral_code:
        bot_info = await bot_client.get_me()
        link = f"https://t.me/{bot_info.username}?start={referral_code}"
        await event.edit(
            f"🔗 Your Referral Link:\n\n"
            f"`{link}`\n\n"
            f"Share with friends and earn credits! 💰",
            buttons=[[Button.inline("🔙 Back", "referral_menu")]]
        )
    else:
        await event.answer("❌ Error generating link", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^referral_stats'))
async def referral_stats_handler(event):
    """Handle referral stats"""
    stats = await get_referral_stats(event.sender_id)
    user_doc = await get_user(event.sender_id)
    
    message = (
        f"📊 Your Referral Statistics\n\n"
        f"👥 Total Referrals: {stats['total']}\n"
        f"✅ Rewarded: {stats['rewarded']}\n"
        f"⏳ Pending: {stats['pending']}\n\n"
        f"💰 Total Earned: {stats['earnings']} credits\n"
        f"🔍 Current Balance: {user_doc.get('searches_remaining', 0)} credits"
    )
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "referral_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^api_menu'))
async def api_menu_handler(event):
    """Handle API menu"""
    await event.edit(
        "🔑 API Key Management\n\n"
        "Create and manage your API keys for programmatic access.",
        buttons=get_api_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^api_create'))
async def api_create_handler(event):
    """Handle API key creation"""
    user_states[event.sender_id] = {"action": "awaiting_api_key_name"}
    await event.edit("➕ Create New API Key\n\nSend a name for this API key:")

@bot_client.on(events.CallbackQuery(pattern='^api_list'))
async def api_list_handler(event):
    """Handle list API keys"""
    api_keys = await list_user_api_keys(event.sender_id)
    
    if not api_keys:
        await event.answer("No API keys", alert=True)
        return
    
    message = f"📋 Your API Keys ({len(api_keys)}):\n\n"
    buttons = []
    
    for key in api_keys:
        created = datetime.fromisoformat(key['created_at']).strftime('%Y-%m-%d')
        message += f"**{key['name']}**\n"
        message += f"Key: `{key['api_key'][:20]}...`\n"
        message += f"Created: {created}\n"
        message += f"Used: {key.get('searches_used', 0)} times\n"
        message += f"Status: {'🟢 Active' if key.get('active', True) else '🔴 Inactive'}\n\n"
        
        buttons.append([Button.inline(f"🗑️ {key['name']}", f"api_del_{key['api_key']}")])
    
    buttons.append([Button.inline("🔙 Back", "api_menu")])
    await event.edit(message, buttons=buttons)

@bot_client.on(events.CallbackQuery(pattern=r'^api_del_(.+)'))
async def api_del_handler(event):
    """Handle delete API key"""
    api_key = event.data.decode().split('_', 1)[1]
    if await delete_api_key(api_key, event.sender_id):
        await event.answer("✅ API key deleted", alert=True)
        await api_list_handler(event)
    else:
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^api_docs'))
async def api_docs_handler(event):
    """Handle API documentation"""
    await event.edit(
        "📚 API Documentation\n\n"
        "**Endpoint:** POST /api/search\n\n"
        "**Headers:**\n"
        "`X-API-Key: your_api_key`\n\n"
        "**Request:**\n"
        "```json\n"
        "{\n"
        "  \"search_type\": \"phone\",\n"
        "  \"query\": \"9876543210\"\n"
        "}\n"
        "```\n\n"
        "**Response:**\n"
        "```json\n"
        "{\n"
        "  \"success\": true,\n"
        "  \"result\": \"...\",\n"
        "  \"creator_credits_remaining\": 5\n"
        "}\n"
        "```",
        buttons=[[Button.inline("🔙 Back", "api_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^help_menu'))
async def help_menu_handler(event):
    """Handle help menu"""
    await event.edit("ℹ️ Help & Support", buttons=get_help_menu())

@bot_client.on(events.CallbackQuery(pattern='^help_usage'))
async def help_usage_handler(event):
    """Handle help usage"""
    await event.edit(
        "❓ How to Use\n\n"
        "1. Join our channel\n"
        "2. Select a search type\n"
        "3. Send the query\n"
        "4. Get instant results!\n\n"
        "💡 Tips:\n"
        "• Use correct phone format\n"
        "• One search per query\n"
        "• Results cached for 24h\n"
        "• Premium plans = more searches",
        buttons=[[Button.inline("🔙 Back", "help_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern='^help_pricing'))
async def help_pricing_handler(event):
    """Handle pricing info"""
    message = "💰 Premium Plans\n\n"
    for plan_key, plan_info in PLANS.items():
        message += f"**{plan_info['name']}**\n"
        if plan_info['searches'] == -1:
            message += f"Unlimited searches for {plan_info['days']} days\n"
        else:
            message += f"{plan_info['searches']} searches\n"
        message += f"Price: ₹{plan_info['price']}\n\n"
    
    await event.edit(message, buttons=[[Button.inline("🔙 Back", "help_menu")]])

@bot_client.on(events.CallbackQuery(pattern='^help_support'))
async def help_support_handler(event):
    """Handle support info"""
    await event.edit(
        "📞 Support\n\n"
        "Having issues? Contact us:\n\n"
        "📧 Email: support@example.com\n"
        "💬 Telegram: @darkboxesAdmin\n"
        "⏰ Response time: 24h",
        buttons=[[Button.inline("🔙 Back", "help_menu")]]
    )

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_handler(event):
    """Handle search type selection"""
    user_id = event.sender_id
    search_type = event.data.decode().split('_')[1]
    
    user_doc = await get_user(user_id)
    if user_doc.get('blocked'):
        await event.answer("❌ You are blocked", alert=True)
        return
    
    admin_check = await is_admin(user_id)
    if not admin_check:
        if user_doc.get('plan') != 'unlimited' and user_doc.get('searches_remaining', 0) <= 0:
            await event.edit(
                "❌ No credits remaining\n\n"
                "Buy a premium plan to continue:",
                buttons=get_plans_menu()
            )
            return
    
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    await event.edit(
        f"🔍 {SEARCH_COMMANDS[search_type]['name']}\n\n"
        f"Credits: {user_doc.get('searches_remaining', 0) if not admin_check else '∞'}\n\n"
        f"Send the {search_type} to search:"
    )

@bot_client.on(events.CallbackQuery(pattern=r'^buy_(.+)'))
async def buy_handler(event):
    """Handle plan purchase"""
    user_id = event.sender_id
    plan_key = event.data.decode().split('_')[1]
    
    if plan_key not in PLANS:
        await event.answer("❌ Invalid plan", alert=True)
        return
    
    plan_info = PLANS[plan_key]
    payment_id = await create_payment_request(user_id, plan_key, plan_info['price'])
    
    if not payment_id:
        await event.answer("❌ Error creating payment", alert=True)
        return
    
    user_states[user_id] = {"action": "awaiting_payment", "payment_id": payment_id, "plan": plan_key}
    
    user = await event.get_sender()
    
    # Notify admin
    try:
        await bot_client.send_message(
            ADMIN_USER_ID,
            f"💰 New Payment Request\n\n"
            f"User: {user.first_name} (@{user.username or 'N/A'})\n"
            f"User ID: {user_id}\n"
            f"Plan: {plan_info['name']}\n"
            f"Amount: ₹{plan_info['price']}\n"
            f"Payment ID: {payment_id}"
        )
    except:
        pass
    
    await event.edit(
        f"💳 Payment Required\n\n"
        f"Plan: {plan_info['name']}\n"
        f"Amount: ₹{plan_info['price']}\n\n"
        f"Scan the QR code and send screenshot:\n\n"
        f"ID: `{payment_id}`",
        buttons=[[Button.inline("❌ Cancel", "cancel")]]
    )
    
    try:
        await bot_client.send_file(user_id, PAYMENT_QR_CODE, caption="Scan to pay")
    except:
        pass

@bot_client.on(events.CallbackQuery(pattern=r'^approve_(.+)_(.+)'))
async def approve_handler(event):
    """Handle payment approval"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    try:
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
        
        await event.edit(f"✅ Approved: {payment_id}")
        
        try:
            await bot_client.send_message(
                target_user_id,
                f"✅ Payment Approved!\n\n"
                f"Plan: {plan_info['name']}\n"
                f"Enjoy unlimited searches! 🎉"
            )
        except:
            pass
    
    except Exception as e:
        logger.exception(f"Approval error: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^reject_(.+)_(.+)'))
async def reject_handler(event):
    """Handle payment rejection"""
    admin_check = await is_admin(event.sender_id)
    if not admin_check:
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    try:
        data_parts = event.data.decode().split('_')
        payment_id = data_parts[1]
        target_user_id = int(data_parts[2])
        
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: payments_col.update_one(
                {"payment_id": payment_id},
                {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}}
            )
        )
        
        await event.edit(f"❌ Rejected: {payment_id}")
        
        try:
            await bot_client.send_message(target_user_id, "❌ Payment was rejected")
        except:
            pass
    
    except Exception as e:
        logger.exception(f"Rejection error: {e}")

@bot_client.on(events.CallbackQuery(pattern='^cancel'))
async def cancel_handler(event):
    """Handle cancel"""
    user_states.pop(event.sender_id, None)
    interactive_sessions.pop(event.sender_id, None)
    await event.edit("❌ Cancelled")

@bot_client.on(events.CallbackQuery(pattern='^check_membership'))
async def check_membership_handler(event):
    """Handle membership check"""
    user_id = event.sender_id
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.answer("❌ Not joined yet", alert=True)
        return
    
    user_doc = await get_user(user_id)
    user = await event.get_sender()
    
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: users_col.update_one({"user_id": user_id}, {"$set": {"channel_joined": True}})
    )
    
    await event.edit(
        f"✅ Welcome {user.first_name}!\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}",
        buttons=get_main_menu()
    )

@bot_client.on(events.CallbackQuery(pattern='^back_main'))
async def back_main_handler(event):
    """Handle back to main"""
    user = await event.get_sender()
    user_id = user.id
    
    admin_check = await is_admin(user_id)
    if admin_check:
        await event.edit("👋 Admin Panel", buttons=get_admin_menu())
    else:
        user_doc = await get_user(user_id)
        await event.edit(
            f"👋 Welcome {user.first_name}!\n\n"
            f"📊 Plan: {user_doc.get('plan', 'free').upper()}\n"
            f"🔍 Credits: {user_doc.get('searches_remaining', 0)}",
            buttons=get_main_menu()
        )

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and e.text and not e.text.startswith('/')))
async def message_handler(event):
    """Handle private messages"""
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    
    # API Key Name
    if state.get('action') == 'awaiting_api_key_name':
        key_name = event.text.strip()
        if len(key_name) < 3:
            await event.respond("❌ Minimum 3 characters")
            return
        
        api_key = await create_api_key(user_id, key_name)
        if api_key:
            user_doc = await get_user(user_id)
            if user_doc.get('plan') == 'unlimited':
                credits = "∞ Unlimited"
            else:
                credits = f"{user_doc.get('searches_remaining', 0)} credits"
            
            await event.respond(
                f"✅ API Key Created!\n\n"
                f"**Key:** `{api_key}`\n"
                f"**Name:** {key_name}\n"
                f"**Your Credits:** {credits}\n\n"
                f"⚠️ Save this key securely!",
                buttons=[[Button.inline("🔙 Back", "api_menu")]]
            )
        
        user_states.pop(user_id, None)
        return
    
    # Broadcast Message
    if state.get('action') == 'awaiting_broadcast':
        admin_check = await is_admin(user_id)
        if not admin_check:
            await event.respond("❌ Unauthorized")
            return
        
        message = event.text
        status_msg = await event.respond("📢 Broadcasting to all users...")
        
        result = await broadcast_message(message, exclude_user_id=user_id)
        
        await status_msg.edit(
            f"✅ Broadcast Complete!\n\n"
            f"✅ Sent to: {result['sent']} users\n"
            f"❌ Failed: {result['failed']} users"
        )
        user_states.pop(user_id, None)
        return
    
    # Make Admin
    if state.get('action') == 'awaiting_admin_user_id':
        admin_check = await is_admin(user_id)
        if not admin_check:
            await event.respond("❌ Unauthorized")
            return
        
        try:
            target_user_id = int(event.text.strip())
            success = await add_admin(target_user_id)
            if success:
                await event.respond(f"✅ {target_user_id} is now an admin!", buttons=[[Button.inline("🔙 Back", "admin_menu")]])
            else:
                await event.respond("❌ Error")
        except:
            await event.respond("❌ Invalid User ID")
        
        user_states.pop(user_id, None)
        return
    
    # Block User
    if state.get('action') == 'awaiting_block_user_id':
        admin_check = await is_admin(user_id)
        if not admin_check:
            await event.respond("❌ Unauthorized")
            return
        
        try:
            target_user_id = int(event.text.strip())
            await block_user(target_user_id)
            await event.respond(f"🚫 User {target_user_id} blocked!", buttons=[[Button.inline("🔙 Back", "admin_menu")]])
        except:
            await event.respond("❌ Invalid User ID")
        
        user_states.pop(user_id, None)
        return
    
    # Payment Screenshot
    if state.get('action') == 'awaiting_payment':
        if not event.photo:
            await event.respond("❌ Please send an image")
            return
        
        payment_id = state['payment_id']
        plan_key = state['plan']
        plan_info = PLANS[plan_key]
        
        await update_payment_screenshot(payment_id, event.message.id)
        
        try:
            user = await event.get_sender()
            admins = await get_all_admins()
            
            for admin_id in admins:
                try:
                    await bot_client.send_file(
                        admin_id,
                        event.photo,
                        caption=(
                            f"💰 Payment Screenshot\n\n"
                            f"User: {user.first_name}\n"
                            f"Plan: {plan_info['name']}\n"
                            f"Amount: ₹{plan_info['price']}\n"
                            f"ID: {payment_id}"
                        ),
                        buttons=get_payment_approval_buttons(payment_id, user_id)
                    )
                except:
                    pass
        except:
            pass
        
        await event.respond("✅ Screenshot received!\n\nWaiting for approval...")
        user_states.pop(user_id, None)
        return
    
    # Search Query
    if state.get('action') == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        status_msg = await event.respond("⏳ Searching... Please wait.")
        
        user_doc = await get_user(user_id)
        is_first_search = (
            user_doc.get('total_searches', 0) == 0 and
            user_doc.get('referred_by')
        )
        
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
                if user_doc and user_doc.get('plan') != 'unlimited':
                    await decrement_search(user_id)
                
                if is_first_search:
                    await reward_referrer(user_id)
        
        elif result.get('needs_interaction'):
            await event.respond(result['message'], buttons=result['buttons'])
            return
        
        else:
            error_msg = result.get('error', 'An error occurred')
            await event.respond(f"❌ {error_msg}")
        
        user_states.pop(user_id, None)

# ============ Relay Button Handler ============

@bot_client.on(events.CallbackQuery(pattern=r'^relay_'))
async def relay_button_handler(event):
    """Handle relay button clicks"""
    user_id = event.sender_id
    
    if user_id not in interactive_sessions:
        await event.answer("❌ Session expired", alert=True)
        return
    
    session = interactive_sessions[user_id]
    dest_message = session['dest_message']
    dest_entity = session['dest_entity']
    search_type = session['type']
    
    try:
        callback_data = event.data.decode()
        
        if callback_data.startswith('relay_tg_'):
            parts = callback_data.split('_')
            if len(parts) >= 4:
                row_idx = int(parts[2])
                col_idx = int(parts[3])
                
                if row_idx < len(dest_message.buttons) and col_idx < len(dest_message.buttons[row_idx]):
                    logger.info(f"🔘 Clicking button [{row_idx}][{col_idx}]")
                    await event.answer("⏳ Fetching...")
                    await dest_message.click(row_idx, col_idx)
        
        elif callback_data.startswith('relay_movie_'):
            parts = callback_data.split('_')
            if len(parts) >= 4:
                row_idx = int(parts[2])
                col_idx = int(parts[3])
                
                if row_idx < len(dest_message.buttons) and col_idx < len(dest_message.buttons[row_idx]):
                    logger.info(f"🎬 Clicking movie button [{row_idx}][{col_idx}]")
                    await event.answer("⏳ Fetching...")
                    await dest_message.click(row_idx, col_idx)
        
        else:
            await event.answer("❌ Invalid button", alert=True)
            return
        
        # Wait for response
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
                    
                    # File found
                    if msg.file:
                        logger.info(f"📁 File received")
                        interactive_sessions.pop(user_id, None)
                        
                        await event.answer("✅ File received!")
                        
                        if msg.text:
                            result = filter_links_and_usernames(msg.text)
                            final = add_footer(result)
                            await bot_client.send_message(user_id, final)
                        
                        await bot_client.forward_messages(user_id, msg)
                        
                        admin_check = await is_admin(user_id)
                        if not admin_check:
                            user_doc = await get_user(user_id)
                            if user_doc and user_doc.get('plan') != 'unlimited':
                                await decrement_search(user_id)
                        
                        return
                    
                    # Text result found
                    if msg.text and len(msg.text.strip()) >= 30:
                        if not is_processing_message(msg.text) and not is_no_info_message(msg.text):
                            logger.info(f"📨 Result received")
                            interactive_sessions.pop(user_id, None)
                            
                            result = filter_links_and_usernames(msg.text)
                            final = add_footer(result)
                            
                            await event.answer("✅ Result received!")
                            await bot_client.send_message(user_id, final)
                            
                            admin_check = await is_admin(user_id)
                            if not admin_check:
                                user_doc = await get_user(user_id)
                                if user_doc and user_doc.get('plan') != 'unlimited':
                                    await decrement_search(user_id)
                            
                            return
                    
                    # Pagination buttons
                    if msg.buttons and msg.id != dest_message.id:
                        logger.info(f"🔘 Pagination buttons found")
                        session['dest_message'] = msg
                        
                        user_buttons = []
                        for r_idx, row in enumerate(msg.buttons):
                            button_row = []
                            for c_idx, button in enumerate(row):
                                if hasattr(button, 'text'):
                                    prefix = "relay_tg_" if search_type == "telegram" else "relay_movie_"
                                    button_row.append(Button.inline(
                                        button.text,
                                        f"{prefix}{r_idx}_{c_idx}"
                                    ))
                            if button_row:
                                user_buttons.append(button_row)
                        
                        msg_text = msg.text or msg.raw_text or "Select an option:"
                        try:
                            await event.edit(msg_text, buttons=user_buttons)
                        except:
                            await bot_client.send_message(user_id, msg_text, buttons=user_buttons)
                        
                        return
            
            except Exception as e:
                logger.warning(f"Check error: {e}")
        
        logger.warning(f"❌ No response after retries")
        await event.answer("❌ No response", alert=True)
        interactive_sessions.pop(user_id, None)
    
    except Exception as e:
        logger.exception(f"Relay error: {e}")
        await event.answer("❌ Error", alert=True)
        interactive_sessions.pop(user_id, None)

# ============ Message Handler for Groups ============

@user_client.on(events.NewMessage())
async def handle_all_replies(event):
    """Handle all messages from groups/bots"""
    message = event.message
    now = time.time()
    
    # Find matching search
    matched_search = None
    matched_key = None
    
    # Check for new messages (telegram/movie searches accept any new message)
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
    
    # Check for direct replies
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
    
    # Handle files (highest priority)
    if has_file:
        try:
            if file_name and (file_name.lower().endswith('.txt') or (message.file and message.file.mime_type == 'text/plain')):
                logger.info(f"📥 Downloading: {file_name}")
                
                file_bytes = await message.download_media(bytes)
                
                try:
                    file_text = file_bytes.decode('utf-8')
                except:
                    try:
                        file_text = file_bytes.decode('latin-1')
                    except:
                        file_text = file_bytes.decode('utf-8', errors='ignore')
                
                cleaned_file_text = clean_file_content(file_text)
                
                # Extract family members for family search
                if matched_search['search_type'] == 'family':
                    family_members = extract_family_members(cleaned_file_text)
                    if family_members:
                        logger.info(f"👨‍👩‍👧 Extracted family members")
                        cleaned_file_text = family_members
                
                if cleaned_file_text and len(cleaned_file_text) > 15:
                    if not matched_search['future'].done():
                        logger.info(f"✅ Delivering file content")
                        matched_search['future'].set_result(cleaned_file_text)
                        logger.info(f"📨 File delivered: {matched_key}")
                        pending_searches.pop(matched_key, None)
                        return
        
        except Exception as e:
            logger.error(f"❌ File error: {e}")
            return
    
    # Handle text
    if text and not has_file:
        if is_processing_message(text):
            logger.info(f"⏳ Processing message, skipping")
            return
        
        if is_no_info_message(text):
            logger.info(f"🚫 No-info message, skipping")
            return
        
        if not matched_search['future'].done():
            cleaned_text = filter_links_and_usernames(text)
            logger.info(f"✅ Delivering text result")
            matched_search['future'].set_result(cleaned_text)
            logger.info(f"📨 Text delivered: {matched_key}")
            pending_searches.pop(matched_key, None)

# ============ Cleanup Task ============

async def cleanup_old_searches():
    """Cleanup expired pending searches"""
    while True:
        await asyncio.sleep(30)
        now = time.time()
        to_remove = []
        
        for search_id, info in list(pending_searches.items()):
            age = now - info.get('timestamp', now)
            
            if age > REPLY_TIMEOUT:
                if not info['future'].done():
                    try:
                        info['future'].set_exception(TimeoutError("Search expired"))
                    except:
                        pass
                to_remove.append(search_id)
        
        for search_id in to_remove:
            pending_searches.pop(search_id, None)
        
        if to_remove:
            logger.info(f"🧹 Cleanup: Removed {len(to_remove)} expired searches")

# ============ Web Server (Health Check) ============

async def start_web_server():
    """Start web server for health checks"""
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    async def api_search(request):
        """API search endpoint"""
        try:
            api_key = request.headers.get('X-API-Key')
            if not api_key:
                return web.json_response({"success": False, "error": "Missing API key"}, status=401)
            
            key_info = await get_api_key_info(api_key)
            if not key_info:
                return web.json_response({"success": False, "error": "Invalid API key"}, status=401)
            
            user_doc = await get_user(key_info['user_id'])
            if not user_doc:
                return web.json_response({"success": False, "error": "User not found"}, status=404)
            
            data = await request.json()
            search_type = data.get('search_type')
            query = data.get('query')
            
            if not search_type or not query:
                return web.json_response({"success": False, "error": "Missing parameters"}, status=400)
            
            result = await perform_search(search_type, query, key_info['user_id'])
            
            if result['success']:
                await increment_api_key_usage(api_key)
                
                if user_doc.get('plan') != 'unlimited':
                    await decrement_search(key_info['user_id'])
                    updated_user = await get_user(key_info['user_id'])
                    remaining = updated_user.get('searches_remaining', 0)
                else:
                    remaining = -1
                
                return web.json_response({
                    "success": True,
                    "result": result['result'],
                    "creator_credits_remaining": remaining
                })
            else:
                return web.json_response(result, status=500)
        
        except Exception as e:
            logger.exception(f"API error: {e}")
            return web.json_response({"success": False, "error": str(e)}, status=500)
    
    app.router.add_get("/health", health_check)
    app.router.add_post("/api/search", api_search)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"🌐 Web server started on port {PORT}")

# ============ Main Bot Function ============

async def start_bot():
    """Start the bot"""
    try:
        logger.info("🤖 Starting bot...")
        await bot_client.start(bot_token=BOT_TOKEN)
        logger.info("✅ Bot started")
        
        me = await bot_client.get_me()
        logger.info(f"Bot username: @{me.username}")
        
        if USE_USER_ACCOUNT:
            logger.info("👤 Connecting user account...")
            if not user_client.is_connected():
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                raise RuntimeError("❌ User not authorized")
            
            logger.info("✅ User account ready")

        logger.info("📡 Resolving destination groups...")
        
        for idx, group in enumerate(DESTINATION_GROUPS):
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ Group {idx}: {group['name']}")
            except Exception as e:
                logger.warning(f"❌ Group {idx}: {e}")
        
        try:
            VEHICLE_GROUP['entity'] = await user_client.get_entity(VEHICLE_GROUP['identifier'])
            logger.info(f"✅ Vehicle Group")
        except Exception as e:
            logger.warning(f"❌ Vehicle Group: {e}")
        
        try:
            FAMILY_GROUP['entity'] = await user_client.get_entity(FAMILY_GROUP['identifier'])
            logger.info(f"✅ Family Group")
        except Exception as e:
            logger.warning(f"❌ Family Group: {e}")
        
        try:
            TELEGRAM_BOT['entity'] = await user_client.get_entity(TELEGRAM_BOT['identifier'])
            logger.info(f"✅ Telegram Bot")
        except Exception as e:
            logger.warning(f"❌ Telegram Bot: {e}")
        
        try:
            TELEGRAM_USERNAME_GROUP['entity'] = await user_client.get_entity(TELEGRAM_USERNAME_GROUP['identifier'])
            logger.info(f"✅ Telegram Username Group")
        except Exception as e:
            logger.warning(f"❌ Telegram Username Group: {e}")
        
        try:
            MOVIE_BOT['entity'] = await user_client.get_entity(MOVIE_BOT['identifier'])
            logger.info(f"✅ Movie Bot")
        except Exception as e:
            logger.warning(f"❌ Movie Bot: {e}")

        init_mongo()
        await add_admin(ADMIN_USER_ID)
        
        asyncio.create_task(cleanup_old_searches())
        asyncio.create_task(start_web_server())

        logger.info("=" * 80)
        logger.info("🚀 BOT IS FULLY OPERATIONAL!")
        logger.info("=" * 80)
        logger.info(f"⏱️  Group Timeout: {GROUP_TIMEOUT}s")
        logger.info(f"💰 Free Credits: {NEW_USER_CREDITS}")
        logger.info(f"👨‍💼 Admin: {ADMIN_USER_ID}")
        logger.info(f"📢 Channel: @{MANDATORY_CHANNEL.replace('@', '')}")
        logger.info(f"🌐 Port: {PORT}")
        logger.info("=" * 80)

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
