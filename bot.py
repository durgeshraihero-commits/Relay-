"""
Premium Information Bot - Advanced Edition
Features:
- Smart cascading search across multiple groups
- Advanced .txt/.json file processing
- Interactive button handling for Telegram/Movie bots
- Referral system with rewards
- API key management system
- Admin panel with statistics
- Payment processing system
- Robust error handling and logging
- Clean architecture with modular design
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
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum

# Third-party imports
try:
    from aiohttp import web, ClientSession
    from telethon import TelegramClient, events, Button
    from telethon.tl.types import User, MessageMediaDocument
    from telethon.tl.functions.channels import GetParticipantRequest
    from pymongo import MongoClient
    from pymongo.errors import ServerSelectionTimeoutError
except ImportError as e:
    print(f"❌ Missing required dependency: {e}")
    print("Install with: pip install telethon aiohttp pymongo")
    sys.exit(1)

# ================== CONFIGURATION ==================

@dataclass
class BotConfig:
    # Server
    PORT: int = int(os.getenv("PORT", "10000"))
    
    # Bot credentials
    BOT_API_ID: int = int(os.getenv("API_ID", "0"))
    BOT_API_HASH: str = os.getenv("API_HASH", "").strip()
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    BOT_SESSION_FILE: str = "bot_session.session"
    
    # User account (for relaying)
    USER_API_ID: int = int(os.getenv("USER_API_ID", "0"))
    USER_API_HASH: str = os.getenv("USER_API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    
    # Admin and mandatory channel
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
    MANDATORY_CHANNEL: str = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")
    
    # Database
    MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DBNAME: str = "advanced_bot_db"
    
    # Payment
    PAYMENT_QR_CODE: str = os.getenv("PAYMENT_QR_CODE", "https://example.com/payment-qr.png")
    
    # Timeouts and limits
    GROUP_TIMEOUT: int = int(os.getenv("GROUP_TIMEOUT", "25"))
    FETCH_WAIT_TIME: int = int(os.getenv("FETCH_WAIT_TIME", "2"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
    
    # Credits and rewards
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "3"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "2"))
    
    # External APIs
    PHONE_API_URL: str = os.getenv("PHONE_API_URL", "")
    PHONE_API_KEY: str = os.getenv("PHONE_API_KEY", "")
    VEHICLE_API_URL: str = os.getenv("VEHICLE_API_URL", "")
    VEHICLE_API_KEY: str = os.getenv("VEHICLE_API_KEY", "")

config = BotConfig()

# ================== LOGGING SETUP ==================

class ColoredFormatter(logging.Formatter):
    """Colored logging formatter"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)

# Apply colored formatter to console handler
console_handler = logging.getLogger().handlers[0]
console_handler.setFormatter(ColoredFormatter("%(asctime)s %(levelname)s [%(name)s]: %(message)s"))

logger = logging.getLogger("AdvancedBot")

# ================== CONFIGURATION VALIDATION ==================

def validate_config() -> bool:
    """Validate all required configuration"""
    errors = []
    
    # Required configs
    required_configs = [
        ("BOT_API_ID", config.BOT_API_ID, lambda x: x != 0),
        ("BOT_API_HASH", config.BOT_API_HASH, lambda x: len(x) > 0),
        ("BOT_TOKEN", config.BOT_TOKEN, lambda x: len(x) > 0),
        ("ADMIN_USER_ID", config.ADMIN_USER_ID, lambda x: x != 0),
        ("MONGODB_URI", config.MONGODB_URI, lambda x: len(x) > 0),
    ]
    
    for name, value, validator in required_configs:
        if not validator(value):
            errors.append(f"❌ {name} is not properly configured")
    
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  {error}")
        return False
    
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = config.USER_API_ID != 0 and config.USER_API_HASH and config.USER_PHONE

# ================== ENUMS AND CONSTANTS ==================

class SearchStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    NO_INFO = "no_info"

class UserRole(Enum):
    USER = "user"
    PREMIUM = "premium"
    ADMIN = "admin"
    BANNED = "banned"

# ================== DESTINATION GROUPS ==================

DESTINATION_GROUPS = [
    {
        "name": "Main Group",
        "identifier": -1003596998816,
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 1
    },
    {
        "name": "Backup Group 2",
        "identifier": "darkboxesv3",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 2
    },
    {
        "name": "Backup Group 3",
        "identifier": "nex_chats",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 3
    }
]

SPECIAL_BOTS = {
    "family": {
        "name": "Family Info Group",
        "identifier": -1003596998816,
        "timeout": config.GROUP_TIMEOUT,
        "entity": None
    },
    "telegram": {
        "name": "Telegram Lookup Bot",
        "identifier": "@Dirgeshrai8090_bot",
        "timeout": 30,
        "entity": None
    },
    "telegram_username": {
        "name": "Telegram Username Group",
        "identifier": "darkboxesv3",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None
    },
    "vehicle": {
        "name": "Vehicle Group",
        "identifier": "IntelXGroup",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None
    },
    "movie": {
        "name": "Movie Bot",
        "identifier": "@iPapkornD2bot",
        "timeout": 45,
        "entity": None
    }
}

# ================== SEARCH COMMANDS ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Number Info",
        "description": "Get detailed information from phone number",
        "commands": ["/num", "/phone", "/mobile"],
        "destination": "groups",
        "example": "9876543210",
        "validation": r"^\d{10,15}$"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Info",
        "description": "Get family member details from phone",
        "commands": ["/familyinfo", "/family"],
        "destination": "family",
        "example": "9876543210",
        "validation": r"^\d{10,15}$"
    },
    "aadhar": {
        "name": "🆔 Aadhar Card Info",
        "description": "Get information from Aadhar number",
        "commands": ["/aadhar", "/adh", "/aadhaar"],
        "destination": "groups",
        "example": "123456789012",
        "validation": r"^\d{12}$"
    },
    "vehicle": {
        "name": "🚗 Vehicle Info",
        "description": "Get vehicle and owner details",
        "commands": ["/vehicle", "/vnum", "/car"],
        "destination": "vehicle",
        "example": "UP16BH1234",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$"
    },
    "upi": {
        "name": "💳 UPI ID Info",
        "description": "Get UPI account information",
        "commands": ["/upiinfo", "/upi"],
        "destination": "groups",
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$"
    },
    "fampay": {
        "name": "💰 FamPay Info",
        "description": "Get FamPay account details",
        "commands": ["/fam", "/fampay"],
        "destination": "groups",
        "example": "9876543210",
        "validation": r"^\d{10}$"
    },
    "email": {
        "name": "📧 Email Info",
        "description": "Search email address details",
        "commands": ["/email", "/mail"],
        "destination": "groups",
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$"
    },
    "telegram": {
        "name": "📲 Telegram to Phone",
        "description": "Get phone from Telegram username",
        "commands": ["/tg", "/telegram"],
        "destination": "telegram",
        "example": "@username",
        "validation": r"^@?\w{5,32}$",
        "daily_limit": 1
    },
    "telegram_username": {
        "name": "👤 Telegram Username Info",
        "description": "Get details from Telegram username",
        "commands": ["/tguser", "/tginfo"],
        "destination": "telegram_username",
        "example": "@username",
        "validation": r"^@?\w{5,32}$",
        "daily_limit": 1
    },
    "imei": {
        "name": "📱 IMEI Info",
        "description": "Get device info from IMEI",
        "commands": ["/imei", "/device"],
        "destination": "groups",
        "example": "123456789012345",
        "validation": r"^\d{15}$"
    },
    "gst": {
        "name": "🏢 GST Info",
        "description": "Get business info from GST number",
        "commands": ["/gst", "/gstin"],
        "destination": "groups",
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$"
    },
    "insta": {
        "name": "📷 Instagram Info",
        "description": "Search Instagram profile details",
        "commands": ["/insta", "/instagram"],
        "destination": "groups",
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$"
    },
    "pak": {
        "name": "🇵🇰 Pakistan CNIC Info",
        "description": "Get Pakistan CNIC details",
        "commands": ["/cnic", "/pak"],
        "destination": "groups",
        "example": "42101-1234567-8",
        "validation": r"^\d{5}-\d{7}-\d{1}$"
    },
    "movies": {
        "name": "🎬 Movies/Series",
        "description": "Search movies and web series",
        "commands": [""],
        "destination": "movie",
        "example": "Avengers",
        "validation": r"^.{2,50}$"
    }
}

# ================== PRICING PLANS ==================

PLANS = {
    "trial": {
        "name": "🆓 Trial Pack",
        "searches": 5,
        "price": 50,
        "days": None,
        "description": "Perfect for testing our services",
        "features": ["5 searches", "Basic support", "All search types"]
    },
    "basic": {
        "name": "🔥 Basic Pack",
        "searches": 15,
        "price": 100,
        "days": None,
        "description": "Most popular choice for regular users",
        "features": ["15 searches", "Priority support", "All search types", "48h validity"]
    },
    "premium": {
        "name": "⭐ Premium Pack",
        "searches": 50,
        "price": 250,
        "days": None,
        "description": "Great value for power users",
        "features": ["50 searches", "Premium support", "All search types", "7 days validity"]
    },
    "unlimited": {
        "name": "💎 Unlimited Pack",
        "searches": -1,
        "price": 500,
        "days": 30,
        "description": "Unlimited searches for 30 days",
        "features": ["Unlimited searches", "24/7 support", "All search types", "30 days validity", "Priority processing"]
    }
}

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.collections = {}
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            
            # Test connection
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            
            # Initialize collections
            self.collections = {
                'users': self.db['users'],
                'searches': self.db['searches'],
                'payments': self.db['payments'],
                'api_keys': self.db['api_keys'],
                'referrals': self.db['referrals'],
                'admin_logs': self.db['admin_logs']
            }
            
            # Create indexes
            await self._create_indexes()
            
            logger.info("✅ MongoDB connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return False
    
    async def _create_indexes(self):
        """Create database indexes for better performance"""
        try:
            # User indexes
            self.collections['users'].create_index([("user_id", 1)], unique=True)
            self.collections['users'].create_index([("referral_code", 1)], unique=True, sparse=True)
            
            # Search indexes
            self.collections['searches'].create_index([("user_id", 1)])
            self.collections['searches'].create_index([("timestamp", -1)])
            
            # Payment indexes
            self.collections['payments'].create_index([("user_id", 1)])
            self.collections['payments'].create_index([("payment_id", 1)], unique=True)
            
            # API key indexes
            self.collections['api_keys'].create_index([("api_key", 1)], unique=True)
            self.collections['api_keys'].create_index([("user_id", 1)])
            
            # Referral indexes
            self.collections['referrals'].create_index([("referrer_id", 1)])
            self.collections['referrals'].create_index([("referred_id", 1)])
            
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.warning(f"⚠️ Index creation warning: {e}")
    
    def get_collection(self, name: str):
        """Get collection by name"""
        return self.collections.get(name)

# ================== USER MANAGER ==================

class UserManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.users_col = db.get_collection('users')
        self.referrals_col = db.get_collection('referrals')
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.users_col.find_one, {"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def create_user(self, user_id: int, username: str = None, first_name: str = None, referral_code: str = None) -> bool:
        """Create new user"""
        try:
            # Generate unique referral code
            user_referral_code = await self._generate_referral_code()
            
            user_doc = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "plan": "free",
                "searches_remaining": config.NEW_USER_CREDITS,
                "plan_expiry": None,
                "total_searches": 0,
                "channel_joined": False,
                "referral_code": user_referral_code,
                "referred_by": None,
                "role": UserRole.USER.value,
                "banned": False,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "telegram_limits": {}
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": user_doc},
                    upsert=True
                )
            )
            
            # Apply referral if provided
            if referral_code:
                await self.apply_referral(user_id, referral_code)
            
            logger.info(f"✅ Created user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            return False
    
    async def _generate_referral_code(self) -> str:
        """Generate unique referral code"""
        for _ in range(10):  # Try 10 times
            code = secrets.token_urlsafe(6).upper()
            existing = await asyncio.get_running_loop().run_in_executor(
                None, self.users_col.find_one, {"referral_code": code}
            )
            if not existing:
                return code
        
        # Fallback with timestamp
        return f"REF{int(time.time())}"[-8:]
    
    async def apply_referral(self, referred_id: int, referral_code: str) -> bool:
        """Apply referral code for new user"""
        try:
            # Find referrer
            referrer = await asyncio.get_running_loop().run_in_executor(
                None, self.users_col.find_one, {"referral_code": referral_code.upper()}
            )
            
            if not referrer or referrer['user_id'] == referred_id:
                return False
            
            # Check if user already has a referrer
            user = await self.get_user(referred_id)
            if user and user.get('referred_by'):
                return False
            
            # Record referral
            referral_doc = {
                "referrer_id": referrer['user_id'],
                "referred_id": referred_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "reward_given": False
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, self.referrals_col.insert_one, referral_doc
            )
            
            # Update referred user
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": referred_id},
                    {"$set": {"referred_by": referrer['user_id']}}
                )
            )
            
            logger.info(f"✅ Applied referral: {referrer['user_id']} -> {referred_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error applying referral: {e}")
            return False
    
    async def reward_referrer(self, referred_id: int) -> bool:
        """Reward referrer when referred user makes first search"""
        try:
            # Find unrewarded referral
            referral = await asyncio.get_running_loop().run_in_executor(
                None, self.referrals_col.find_one,
                {"referred_id": referred_id, "reward_given": False}
            )
            
            if not referral:
                return False
            
            # Give reward to referrer
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": referral['referrer_id']},
                    {"$inc": {"searches_remaining": config.REFERRAL_REWARD}}
                )
            )
            
            # Mark as rewarded
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.referrals_col.update_one(
                    {"_id": referral['_id']},
                    {
                        "$set": {
                            "reward_given": True,
                            "rewarded_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            
            logger.info(f"✅ Rewarded referrer {referral['referrer_id']} for {referred_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error rewarding referrer: {e}")
            return False
    
    async def update_searches(self, user_id: int, increment: int = -1) -> bool:
        """Update user search count"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "searches_remaining": increment,
                            "total_searches": abs(increment)
                        },
                        "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error updating searches for {user_id}: {e}")
            return False
    
    async def check_daily_limit(self, user_id: int, search_type: str) -> bool:
        """Check if user has exceeded daily limit for specific search type"""
        try:
            if search_type not in SEARCH_COMMANDS:
                return False
            
            daily_limit = SEARCH_COMMANDS[search_type].get('daily_limit')
            if not daily_limit:
                return False  # No daily limit
            
            today = datetime.now(timezone.utc).date().isoformat()
            
            # Get user's limits for today
            user = await self.get_user(user_id)
            if not user:
                return True  # Block if user not found
            
            telegram_limits = user.get('telegram_limits', {})
            today_count = telegram_limits.get(today, {}).get(search_type, 0)
            
            return today_count >= daily_limit
            
        except Exception as e:
            logger.error(f"Error checking daily limit: {e}")
            return True  # Block on error
    
    async def update_daily_limit(self, user_id: int, search_type: str):
        """Update daily limit counter"""
        try:
            if search_type not in SEARCH_COMMANDS:
                return
            
            today = datetime.now(timezone.utc).date().isoformat()
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {f"telegram_limits.{today}.{search_type}": 1}}
                )
            )
            
        except Exception as e:
            logger.error(f"Error updating daily limit: {e}")

# ================== TEXT PROCESSING UTILITIES ==================

class TextProcessor:
    @staticmethod
    def is_processing_message(text: str) -> bool:
        """Check if message indicates processing"""
        if not text or len(text.strip()) < 10:
            return True
        
        processing_keywords = [
            'processing', 'please wait', 'fetching', 'loading', 'searching',
            'retrieving', 'hold on', 'wait a moment', 'in progress',
            'gathering data', 'working on it', '⏳', '🔍', 'searching for'
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in processing_keywords)
    
    @staticmethod
    def is_no_info_message(text: str) -> bool:
        """Check if message indicates no information found"""
        if not text:
            return False
        
        no_info_keywords = [
            'no info', 'no information', 'not found', 'no data', 'no result',
            'no record', 'invalid', 'doesn\'t exist', 'does not exist',
            'not available', 'no details', 'unable to find', 'could not find',
            'couldn\'t find', 'no match', 'not exist', 'no information found',
            'to reduce spam', 'must have joined', 'join all channels',
            'verify your account', 'admin to verify', 'subscription required'
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in no_info_keywords)
    
    @staticmethod
    def clean_result_text(text: str) -> str:
        """Clean and format result text"""
        if not text:
            return ""
        
        # Remove URLs and mentions
        patterns = [
            r'https?://[^\s]+',
            r'www\.[^\s]+', 
            r't\.me/[^\s]+',
            r'@[a-zA-Z0-9_]{3,32}',
            r'tg://[^\s]+',
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove promotional content
        promotional_patterns = [
            r'(?i)(powered by|developed by|designed by).*',
            r'(?i)(follow|subscribe|join|visit|contact).*',
            r'(?i)admin.*',
            r'(?i)creator.*'
        ]
        
        for pattern in promotional_patterns:
            text = re.sub(pattern, '', text)
        
        # Clean whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def clean_file_content(content: str) -> str:
        """Clean content from downloaded files"""
        if not content:
            return ""
        
        # Remove all promotional content more aggressively for files
        content = re.sub(r'https?://\S+', '', content)
        content = re.sub(r'www\.\S+', '', content)
        content = re.sub(r't\.me/\S+', '', content)
        content = re.sub(r'@\w+', '', content)
        content = re.sub(r'(?i)(powered by|developed by|created by).*', '', content)
        
        # Clean up lines
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('=') and not line.startswith('--'):
                # Skip lines with only special characters
                if re.match(r'^[=\-_*]{3,}$', line):
                    continue
                cleaned_lines.append(line)
        
        result = '\n'.join(cleaned_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        
        return result.strip()
    
    @staticmethod
    def validate_query(query: str, search_type: str) -> tuple[bool, str]:
        """Validate query against search type requirements"""
        if search_type not in SEARCH_COMMANDS:
            return False, "Invalid search type"
        
        command_info = SEARCH_COMMANDS[search_type]
        validation_pattern = command_info.get('validation')
        
        if not validation_pattern:
            return True, ""  # No validation required
        
        # Clean the query
        query = query.strip()
        
        # Special handling for different types
        if search_type == "phone":
            query = re.sub(r'[^\d]', '', query)
            if len(query) < 10 or len(query) > 15:
                return False, "Phone number must be 10-15 digits"
        
        elif search_type == "aadhar":
            query = re.sub(r'[^\d]', '', query)
            if len(query) != 12:
                return False, "Aadhar number must be 12 digits"
        
        elif search_type == "vehicle":
            query = query.upper().replace(' ', '')
            if not re.match(validation_pattern, query):
                return False, "Invalid vehicle number format (e.g., UP16BH1234)"
        
        elif search_type in ["telegram", "telegram_username"]:
            query = query.replace('@', '').strip()
            if len(query) < 5 or len(query) > 32:
                return False, "Username must be 5-32 characters"
        
        elif search_type == "email":
            if not re.match(validation_pattern, query):
                return False, "Invalid email format"
        
        elif search_type == "gst":
            query = query.upper().replace(' ', '')
            if not re.match(validation_pattern, query):
                return False, "Invalid GST number format"
        
        # Default regex validation
        if not re.match(validation_pattern, query):
            return False, f"Invalid format for {search_type}"
        
        return True, query

# ================== SEARCH ENGINE ==================

class SearchEngine:
    def __init__(self, db: DatabaseManager, user_manager: UserManager):
        self.db = db
        self.user_manager = user_manager
        self.searches_col = db.get_collection('searches')
        self.pending_searches: Dict[str, Dict] = {}
        self.interactive_sessions: Dict[int, Dict] = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Main search function with cascading logic"""
        if search_type not in SEARCH_COMMANDS:
            return {"success": False, "error": "❌ Invalid search type"}
        
        # Validate query
        is_valid, cleaned_query = TextProcessor.validate_query(query, search_type)
        if not is_valid:
            return {"success": False, "error": f"❌ {cleaned_query}"}
        
        query = cleaned_query
        
        # Check daily limits for specific search types
        if await self.user_manager.check_daily_limit(user_id, search_type):
            reset_time = await self._get_reset_time()
            return {
                "success": False, 
                "error": f"⏰ Daily limit reached for {search_type}.\nReset in: {reset_time}"
            }
        
        command_info = SEARCH_COMMANDS[search_type]
        destination = command_info["destination"]
        
        logger.info(f"🔍 Starting search: {search_type} = {query} for user {user_id}")
        
        # Route to appropriate handler
        if destination == "groups":
            result = await self._search_in_groups(search_type, query, user_id)
        elif destination in SPECIAL_BOTS:
            result = await self._search_in_special_bot(destination, search_type, query, user_id)
        else:
            result = {"success": False, "error": "❌ Search destination not configured"}
        
        # Log search attempt
        await self._log_search(user_id, search_type, query, result.get("success", False))
        
        # Update daily limit if applicable
        if result.get("success") and command_info.get("daily_limit"):
            await self.user_manager.update_daily_limit(user_id, search_type)
        
        return result
    
    async def _search_in_groups(self, search_type: str, query: str, user_id: int) -> Dict:
        """Search in cascading groups"""
        command_info = SEARCH_COMMANDS[search_type]
        commands = command_info["commands"]
        
        # Sort groups by priority
        groups = sorted(DESTINATION_GROUPS, key=lambda x: x["priority"])
        
        for idx, group in enumerate(groups):
            if not group.get("entity"):
                logger.warning(f"Group {group['name']} not resolved, skipping")
                continue
            
            command = commands[idx % len(commands)]  # Cycle through commands
            message = f"{command} {query}"
            
            try:
                # Send message to group
                sent_msg = await user_client.send_message(group["entity"], message)
                logger.info(f"📤 [{idx+1}/{len(groups)}] Sent to {group['name']}: {message}")
                
                # Create search tracking
                search_id = f"{sent_msg.id}_{int(time.time()*1000)}_{idx}"
                future = asyncio.get_running_loop().create_future()
                
                self.pending_searches[search_id] = {
                    "future": future,
                    "user_id": user_id,
                    "query": query,
                    "search_type": search_type,
                    "timestamp": time.time(),
                    "message_id": sent_msg.id,
                    "chat_entity": group["entity"],
                    "group_name": group["name"],
                    "group_index": idx
                }
                
                try:
                    # Wait for result
                    result_text = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if isinstance(result_text, str) and result_text.strip():
                        # Validate result
                        if not TextProcessor.is_no_info_message(result_text):
                            cleaned = TextProcessor.clean_result_text(result_text)
                            if len(cleaned) > 20:  # Minimum content check
                                self.pending_searches.pop(search_id, None)
                                return {
                                    "success": True,
                                    "result": self._format_result(cleaned, search_type),
                                    "source": group["name"]
                                }
                    
                    # Result not useful, try next group
                    self.pending_searches.pop(search_id, None)
                    logger.info(f"⚠️ Result from {group['name']} not useful, trying next")
                    continue
                    
                except asyncio.TimeoutError:
                    self.pending_searches.pop(search_id, None)
                    logger.info(f"⏱️ Timeout from {group['name']} ({group['timeout']}s)")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Error searching in {group['name']}: {e}")
                continue
        
        # Try API fallback for supported types
        api_result = await self._try_api_fallback(search_type, query)
        if api_result["success"]:
            return api_result
        
        return {
            "success": False,
            "error": "❌ No results found from any source.\n\nPlease try a different query or format."
        }
    
    async def _search_in_special_bot(self, destination: str, search_type: str, query: str, user_id: int) -> Dict:
        """Search in special bots (telegram, movie, etc.)"""
        bot_config = SPECIAL_BOTS.get(destination)
        if not bot_config or not bot_config.get("entity"):
            return {"success": False, "error": f"❌ {destination} bot not configured"}
        
        # Handle interactive bots
        if destination in ["telegram", "movie"]:
            return await self._handle_interactive_bot(destination, search_type, query, user_id)
        
        # Handle regular special bots
        command_info = SEARCH_COMMANDS[search_type]
        command = command_info["commands"][0] if command_info["commands"][0] else ""
        message = f"{command} {query}".strip()
        
        try:
            sent_msg = await user_client.send_message(bot_config["entity"], message)
            logger.info(f"📤 Sent to {bot_config['name']}: {message}")
            
            # Wait for response
            await asyncio.sleep(3)  # Give bot time to process
            
            # Get recent messages
            messages = await user_client.get_messages(bot_config["entity"], limit=10)
            
            for msg in messages:
                if msg.id == sent_msg.id:
                    continue
                
                # Check if it's a response to our message
                msg_time = msg.date.timestamp() if msg.date else 0
                sent_time = sent_msg.date.timestamp() if sent_msg.date else 0
                
                if msg_time > sent_time:
                    text = msg.text or msg.raw_text
                    if text and not TextProcessor.is_processing_message(text):
                        if not TextProcessor.is_no_info_message(text):
                            cleaned = TextProcessor.clean_result_text(text)
                            return {
                                "success": True,
                                "result": self._format_result(cleaned, search_type),
                                "source": bot_config["name"]
                            }
            
            return {"success": False, "error": f"❌ No response from {bot_config['name']}"}
            
        except Exception as e:
            logger.error(f"Error with {destination} bot: {e}")
            return {"success": False, "error": f"❌ Error contacting {destination} bot"}
    
    async def _handle_interactive_bot(self, destination: str, search_type: str, query: str, user_id: int) -> Dict:
        """Handle bots that require interactive button selection"""
        bot_config = SPECIAL_BOTS[destination]
        
        try:
            command_info = SEARCH_COMMANDS[search_type]
            command = command_info["commands"][0] if command_info["commands"] else ""
            message = f"{command} {query}".strip()
            
            sent_msg = await user_client.send_message(bot_config["entity"], message)
            logger.info(f"📤 Sent to interactive {bot_config['name']}: {message}")
            
            # Wait for response with buttons
            await asyncio.sleep(5)
            
            messages = await user_client.get_messages(bot_config["entity"], limit=15)
            
            for msg in messages:
                if msg.id == sent_msg.id:
                    continue
                
                msg_time = msg.date.timestamp() if msg.date else 0
                sent_time = sent_msg.date.timestamp() if sent_msg.date else 0
                
                if msg_time > sent_time:
                    # Check for inline buttons
                    if msg.buttons:
                        logger.info(f"🔘 Found interactive buttons in {bot_config['name']}")
                        
                        # Store interactive session
                        self.interactive_sessions[user_id] = {
                            "dest_message": msg,
                            "dest_entity": bot_config["entity"],
                            "type": destination,
                            "query": query,
                            "search_type": search_type,
                            "original_msg_id": sent_msg.id,
                            "user_id": user_id
                        }
                        
                        # Convert buttons for user
                        user_buttons = []
                        for row_idx, row in enumerate(msg.buttons):
                            button_row = []
                            for col_idx, button in enumerate(row):
                                if hasattr(button, 'text'):
                                    button_row.append(Button.inline(
                                        button.text,
                                        f"interactive_{destination}_{row_idx}_{col_idx}"
                                    ))
                            if button_row:
                                user_buttons.append(button_row)
                        
                        return {
                            "success": False,
                            "needs_interaction": True,
                            "message": msg.text or msg.raw_text or f"🔍 Select an option for {search_type}:",
                            "buttons": user_buttons
                        }
                    
                    # Direct result
                    elif msg.text or msg.file:
                        text = msg.text or msg.raw_text or "File received"
                        if msg.file:
                            return {
                                "success": True,
                                "result": self._format_result(text, search_type),
                                "source": bot_config["name"],
                                "file": msg
                            }
                        else:
                            cleaned = TextProcessor.clean_result_text(text)
                            return {
                                "success": True,
                                "result": self._format_result(cleaned, search_type),
                                "source": bot_config["name"]
                            }
            
            return {"success": False, "error": f"❌ No response from {bot_config['name']}"}
            
        except Exception as e:
            logger.error(f"Error with interactive {destination}: {e}")
            return {"success": False, "error": f"❌ Error with interactive {destination}"}
    
    async def handle_interactive_button(self, user_id: int, button_data: str):
        """Handle interactive button clicks"""
        if user_id not in self.interactive_sessions:
            return {"success": False, "error": "❌ Session expired"}
        
        session = self.interactive_sessions[user_id]
        dest_message = session['dest_message']
        dest_entity = session['dest_entity']
        bot_type = session['type']
        
        try:
            # Parse button data
            parts = button_data.split('_')
            if len(parts) >= 4:
                row_idx = int(parts[2])
                col_idx = int(parts[3])
                
                # Click the button
                await dest_message.click(row_idx, col_idx)
                logger.info(f"🔘 Clicked button [{row_idx}][{col_idx}] in {bot_type}")
                
                # Wait for response
                for attempt in range(4):
                    await asyncio.sleep(3 + attempt)
                    
                    # Check for updated message or new messages
                    messages = await user_client.get_messages(dest_entity, limit=20)
                    
                    for msg in messages:
                        if msg.date and msg.date.timestamp() > time.time() - 30:
                            # New buttons (pagination)
                            if msg.buttons:
                                session['dest_message'] = msg
                                
                                user_buttons = []
                                for r_idx, row in enumerate(msg.buttons):
                                    button_row = []
                                    for c_idx, button in enumerate(row):
                                        if hasattr(button, 'text'):
                                            button_row.append(Button.inline(
                                                button.text,
                                                f"interactive_{bot_type}_{r_idx}_{c_idx}"
                                            ))
                                    if button_row:
                                        user_buttons.append(button_row)
                                
                                return {
                                    "success": False,
                                    "needs_interaction": True,
                                    "message": msg.text or msg.raw_text or "Select an option:",
                                    "buttons": user_buttons
                                }
                            
                            # Final result
                            elif msg.file or (msg.text and len(msg.text.strip()) > 10):
                                self.interactive_sessions.pop(user_id, None)
                                
                                if msg.file:
                                    return {
                                        "success": True,
                                        "result": self._format_result(msg.text or "File received", session['search_type']),
                                        "source": f"Interactive {bot_type}",
                                        "file": msg
                                    }
                                else:
                                    cleaned = TextProcessor.clean_result_text(msg.text)
                                    return {
                                        "success": True,
                                        "result": self._format_result(cleaned, session['search_type']),
                                        "source": f"Interactive {bot_type}"
                                    }
                
                return {"success": False, "error": "❌ No response after button click"}
        
        except Exception as e:
            logger.error(f"Error handling interactive button: {e}")
            self.interactive_sessions.pop(user_id, None)
            return {"success": False, "error": "❌ Button interaction failed"}
    
    async def _try_api_fallback(self, search_type: str, query: str) -> Dict:
        """Try external API as fallback"""
        if search_type == "phone" and config.PHONE_API_URL and config.PHONE_API_KEY:
            return await self._phone_api_search(query)
        elif search_type == "vehicle" and config.VEHICLE_API_URL and config.VEHICLE_API_KEY:
            return await self._vehicle_api_search(query)
        
        return {"success": False}
    
    async def _phone_api_search(self, phone: str) -> Dict:
        """Search using phone API"""
        try:
            async with ClientSession() as session:
                headers = {"X-API-Key": config.PHONE_API_KEY}
                params = {"phone": phone}
                
                async with session.get(config.PHONE_API_URL, headers=headers, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        formatted = self._format_phone_api_response(data, phone)
                        return {
                            "success": True,
                            "result": self._format_result(formatted, "phone"),
                            "source": "Phone API"
                        }
        except Exception as e:
            logger.error(f"Phone API error: {e}")
        
        return {"success": False}
    
    async def _vehicle_api_search(self, vehicle: str) -> Dict:
        """Search using vehicle API"""
        try:
            async with ClientSession() as session:
                headers = {"X-API-Key": config.VEHICLE_API_KEY}
                params = {"vehicle_number": vehicle}
                
                async with session.get(config.VEHICLE_API_URL, headers=headers, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        formatted = self._format_vehicle_api_response(data, vehicle)
                        return {
                            "success": True,
                            "result": self._format_result(formatted, "vehicle"),
                            "source": "Vehicle API"
                        }
        except Exception as e:
            logger.error(f"Vehicle API error: {e}")
        
        return {"success": False}
    
    def _format_result(self, content: str, search_type: str) -> str:
        """Format final result with header and footer"""
        if not content:
            return "❌ No information found"
        
        command_info = SEARCH_COMMANDS.get(search_type, {})
        search_name = command_info.get("name", "Search Result")
        
        header = f"✅ {search_name}\n\n"
        footer = f"\n\n{'─'*35}\n💎 Premium Info Bot\n🔗 @darkboxesAdmin"
        
        return header + content + footer
    
    def _format_phone_api_response(self, data: dict, phone: str) -> str:
        """Format phone API response"""
        try:
            result = f"📱 Phone: {phone}\n\n"
            
            if isinstance(data, dict) and 'Result' in data:
                records = data['Result']
                if isinstance(records, list) and records:
                    for idx, record in enumerate(records, 1):
                        if len(records) > 1:
                            result += f"━━━ Record {idx} ━━━\n"
                        
                        if record.get('name'):
                            result += f"👤 Name: {record['name']}\n"
                        if record.get('mobile'):
                            result += f"📱 Mobile: {record['mobile']}\n"
                        if record.get('address'):
                            result += f"🏠 Address: {record['address']}\n"
                        if record.get('father_name'):
                            result += f"👨 Father: {record['father_name']}\n"
                        if record.get('email'):
                            result += f"📧 Email: {record['email']}\n"
                        
                        if idx < len(records):
                            result += "\n"
                else:
                    result += "No records found"
            
            return result
            
        except Exception as e:
            logger.error(f"Error formatting phone API response: {e}")
            return f"📱 Phone: {phone}\n\nAPI data formatting failed"
    
    def _format_vehicle_api_response(self, data: dict, vehicle: str) -> str:
        """Format vehicle API response"""
        try:
            result = f"🚗 Vehicle: {vehicle}\n\n"
            
            if isinstance(data, dict):
                if data.get('owner_name'):
                    result += f"👤 Owner: {data['owner_name']}\n"
                if data.get('father_name'):
                    result += f"👨 Father: {data['father_name']}\n"
                if data.get('mobile_number'):
                    result += f"📱 Mobile: {data['mobile_number']}\n"
                if data.get('address'):
                    result += f"🏠 Address: {data['address']}\n"
                if data.get('manufacturer'):
                    result += f"🏭 Make: {data['manufacturer']}\n"
                if data.get('model'):
                    result += f"🚙 Model: {data['model']}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"Error formatting vehicle API response: {e}")
            return f"🚗 Vehicle: {vehicle}\n\nAPI data formatting failed"
    
    async def _log_search(self, user_id: int, search_type: str, query: str, success: bool):
        """Log search to database"""
        try:
            doc = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query[:100],  # Limit query length
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await asyncio.get_running_loop().run_in_executor(
                None, self.searches_col.insert_one, doc
            )
        except Exception as e:
            logger.error(f"Error logging search: {e}")
    
    async def _get_reset_time(self) -> str:
        """Get time until daily limit reset"""
        try:
            tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
            tomorrow_start = datetime.combine(tomorrow, datetime.min.time()).replace(tzinfo=timezone.utc)
            time_diff = tomorrow_start - datetime.now(timezone.utc)
            hours = int(time_diff.total_seconds() // 3600)
            minutes = int((time_diff.total_seconds() % 3600) // 60)
            return f"{hours}h {minutes}m"
        except Exception:
            return "24h"

# ================== MESSAGE HANDLER ==================

class MessageHandler:
    def __init__(self, search_engine: SearchEngine):
        self.search_engine = search_engine
    
    async def handle_group_message(self, event):
        """Handle messages from groups (replies to our searches)"""
        message = event.message
        
        if not message.reply_to:
            return
        
        text = message.text or message.raw_text
        has_file = message.file is not None
        
        if not text and not has_file:
            return
        
        # Find matching pending search
        matched_search = None
        matched_key = None
        
        for search_id, search_info in list(self.search_engine.pending_searches.items()):
            if search_info['future'].done():
                continue
            
            # Check if this is a reply to our message
            if message.reply_to.reply_to_msg_id == search_info.get('message_id'):
                matched_search = search_info
                matched_key = search_id
                break
        
        if not matched_search:
            return
        
        await asyncio.sleep(config.FETCH_WAIT_TIME)
        
        # Handle file responses
        if has_file:
            await self._handle_file_response(message, matched_search, matched_key)
            return
        
        # Handle text responses
        if text:
            await self._handle_text_response(text, matched_search, matched_key)
    
    async def _handle_file_response(self, message, matched_search, matched_key):
        """Handle file responses (.txt, .json)"""
        try:
            file_name = (message.file.name or "").lower()
            mime_type = (message.file.mime_type or "").lower()
            
            # Check if it's a text file we can process
            is_processable = (
                file_name.endswith(('.txt', '.json')) or 
                mime_type.startswith('text/') or 
                'json' in mime_type
            )
            
            if not is_processable:
                logger.info("📁 Non-text file received, ignoring")
                return
            
            # Check file size
            if message.file.size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning(f"📁 File too large: {message.file.size} bytes")
                return
            
            logger.info(f"📥 Downloading file: {file_name}")
            
            # Download and process file
            file_bytes = await message.download_media(bytes)
            
            # Try different encodings
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
                try:
                    content = file_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file content")
                return
            
            # Process JSON files
            if file_name.endswith('.json') or 'json' in mime_type:
                try:
                    parsed = json.loads(content)
                    content = json.dumps(parsed, indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    logger.warning("⚠️ Invalid JSON, treating as text")
            
            # Clean content
            cleaned_content = TextProcessor.clean_file_content(content)
            
            # Special processing for family info
            if matched_search.get('search_type') == 'family':
                cleaned_content = self._extract_family_members(cleaned_content)
            
            # Validate content
            if cleaned_content and len(cleaned_content.strip()) > 15:
                if not matched_search['future'].done():
                    logger.info("✅ Delivering file content")
                    matched_search['future'].set_result(cleaned_content)
                    self.search_engine.pending_searches.pop(matched_key, None)
            else:
                logger.warning("⚠️ File content too short or empty after cleaning")
                
        except Exception as e:
            logger.error(f"❌ Error processing file: {e}")
    
    async def _handle_text_response(self, text, matched_search, matched_key):
        """Handle text responses"""
        # Skip processing messages
        if TextProcessor.is_processing_message(text):
            logger.info("⏳ Processing message detected, waiting...")
            return
        
        # Skip no-info messages  
        if TextProcessor.is_no_info_message(text):
            logger.info("🚫 No-info message detected")
            if not matched_search['future'].done():
                try:
                    matched_search['future'].set_exception(TimeoutError("No info"))
                except Exception:
                    pass
            self.search_engine.pending_searches.pop(matched_key, None)
            return
        
        # Process valid text
        if len(text.strip()) >= 15:  # Minimum content length
            cleaned_text = TextProcessor.clean_result_text(text)
            
            if cleaned_text and not matched_search['future'].done():
                logger.info("✅ Delivering text result")
                matched_search['future'].set_result(cleaned_text)
                self.search_engine.pending_searches.pop(matched_key, None)
    
    def _extract_family_members(self, text: str) -> str:
        """Extract family member information from family info text"""
        if not text:
            return text
        
        lines = text.splitlines()
        family_members = []
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines and decorators
            if not stripped or stripped.startswith(('=', '-', '*', '_')):
                continue
            
            # Skip header/footer lines
            skip_keywords = [
                'family report', 'head:', 'rc no:', 'designed', 'powered by',
                'developed by', 'telegram', '©', 'copyright', 'admin'
            ]
            
            if any(keyword in stripped.lower() for keyword in skip_keywords):
                continue
            
            # Include lines that look like family member entries
            if any(marker in stripped for marker in ['•', '-', '*', '→', '●']):
                family_members.append(stripped)
            elif any(keyword in stripped.lower() for keyword in ['name', 'age', 'relation', 'member']):
                family_members.append(stripped)
        
        return '\n'.join(family_members) if family_members else text

# ================== PAYMENT SYSTEM ==================

class PaymentManager:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.payments_col = db.get_collection('payments')
        self.users_col = db.get_collection('users')
    
    async def create_payment_request(self, user_id: int, plan_key: str) -> Optional[str]:
        """Create a new payment request"""
        try:
            if plan_key not in PLANS:
                return None

            plan = PLANS[plan_key]
            payment_id = uuid.uuid4().hex

            doc = {
                "payment_id": payment_id,
                "user_id": user_id,
                "plan": plan_key,
                "amount": plan["price"],
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "screenshot_file_id": None,
                "approved_at": None,
                "rejected_at": None
            }

            await asyncio.get_running_loop().run_in_executor(
                None,
                self.payments_col.insert_one,
                doc
            )

            logger.info(f"💳 Created payment request {payment_id} for user {user_id}")
            return payment_id

        except Exception as e:
            logger.exception("Error creating payment request")
            return None
    
    async def update_payment_screenshot(self, payment_id: str, file_id: str) -> bool:
        """Update payment with screenshot"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.payments_col.update_one(
                    {"payment_id": payment_id},
                    {
                        "$set": {
                            "screenshot_file_id": file_id,
                            "screenshot_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error updating payment screenshot: {e}")
            return False
    
    async def approve_payment(self, payment_id: str) -> bool:
        """Approve payment and update user plan"""
        try:
            # Get payment details
            payment = await asyncio.get_running_loop().run_in_executor(
                None, self.payments_col.find_one, {"payment_id": payment_id}
            )
            
            if not payment or payment["status"] != "pending":
                return False
            
            plan_key = payment["plan"]
            plan = PLANS[plan_key]
            user_id = payment["user_id"]
            
            # Update user plan
            if plan["searches"] == -1:  # Unlimited plan
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.users_col.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "plan": "unlimited",
                                "searches_remaining": 999999,
                                "plan_expiry": (datetime.now(timezone.utc) + timedelta(days=plan["days"])).isoformat()
                            }
                        }
                    )
                )
            else:  # Limited searches plan
                user = await asyncio.get_running_loop().run_in_executor(
                    None, self.users_col.find_one, {"user_id": user_id}
                )
                current_searches = user.get("searches_remaining", 0)
                
                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self.users_col.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "plan": "premium",
                                "searches_remaining": current_searches + plan["searches"]
                            }
                        }
                    )
                )
            
            # Mark payment as approved
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.payments_col.update_one(
                    {"payment_id": payment_id},
                    {
                        "$set": {
                            "status": "approved",
                            "approved_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            
            logger.info(f"✅ Approved payment {payment_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error approving payment: {e}")
            return False
    
    async def reject_payment(self, payment_id: str) -> bool:
        """Reject payment"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.payments_col.update_one(
                    {"payment_id": payment_id},
                    {
                        "$set": {
                            "status": "rejected",
                            "rejected_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error rejecting payment: {e}")
            return False
    
    async def get_pending_payments(self, limit: int = 10) -> List[Dict]:
        """Get pending payments for admin review"""
        try:
            cursor = self.payments_col.find({"status": "pending"}).limit(limit).sort("created_at", -1)
            return await asyncio.get_running_loop().run_in_executor(None, list, cursor)
        except Exception as e:
            logger.error(f"Error getting pending payments: {e}")
            return []

# ================== ADMIN PANEL ==================

class AdminPanel:
    def __init__(self, db: DatabaseManager, user_manager: UserManager):
        self.db = db
        self.user_manager = user_manager
        self.users_col = db.get_collection('users')
        self.searches_col = db.get_collection('searches')
        self.payments_col = db.get_collection('payments')
    
    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id == config.ADMIN_USER_ID
    
    async def get_bot_statistics(self) -> Dict:
        """Get comprehensive bot statistics"""
        try:
            loop = asyncio.get_running_loop()
            
            # Basic counts
            total_users = await loop.run_in_executor(None, self.users_col.count_documents, {})
            premium_users = await loop.run_in_executor(
                None, self.users_col.count_documents, {"plan": {"$in": ["premium", "unlimited"]}}
            )
            total_searches = await loop.run_in_executor(None, self.searches_col.count_documents, {})
            successful_searches = await loop.run_in_executor(
                None, self.searches_col.count_documents, {"success": True}
            )
            
            # Payment statistics
            total_payments = await loop.run_in_executor(None, self.payments_col.count_documents, {})
            approved_payments = await loop.run_in_executor(
                None, self.payments_col.count_documents, {"status": "approved"}
            )
            pending_payments = await loop.run_in_executor(
                None, self.payments_col.count_documents, {"status": "pending"}
            )
            
            # Revenue calculation
            approved_payment_docs = await loop.run_in_executor(
                None, lambda: list(self.payments_col.find({"status": "approved"}, {"amount": 1}))
            )
            total_revenue = sum(p.get("amount", 0) for p in approved_payment_docs)
            
            # Today's statistics
            today = datetime.now(timezone.utc).date()
            today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
            
            today_users = await loop.run_in_executor(
                None, self.users_col.count_documents, 
                {"joined_at": {"$gte": today_start.isoformat()}}
            )
            today_searches = await loop.run_in_executor(
                None, self.searches_col.count_documents,
                {"timestamp": {"$gte": today_start.isoformat()}}
            )
            today_payments = await loop.run_in_executor(
                None, self.payments_col.count_documents,
                {"created_at": {"$gte": today_start.isoformat()}}
            )
            
            # Search type breakdown
            search_pipeline = [
                {"$group": {"_id": "$search_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            search_types = await loop.run_in_executor(
                None, lambda: list(self.searches_col.aggregate(search_pipeline))
            )
            
            return {
                "total_users": total_users,
                "premium_users": premium_users,
                "total_searches": total_searches,
                "successful_searches": successful_searches,
                "success_rate": round((successful_searches / max(total_searches, 1)) * 100, 1),
                "total_payments": total_payments,
                "approved_payments": approved_payments,
                "pending_payments": pending_payments,
                "total_revenue": total_revenue,
                "today_users": today_users,
                "today_searches": today_searches,
                "today_payments": today_payments,
                "popular_searches": search_types
            }
            
        except Exception as e:
            logger.error(f"Error getting bot statistics: {e}")
            return {}
    
    async def ban_user(self, user_id: int) -> bool:
        """Ban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"banned": True, "banned_at": datetime.now(timezone.utc).isoformat()}}
                )
            )
            logger.info(f"🚫 Banned user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False
    
    async def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"banned": False}, "$unset": {"banned_at": ""}}
                )
            )
            logger.info(f"✅ Unbanned user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False
    
    async def add_credits(self, user_id: int, credits: int) -> bool:
        """Add credits to user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": credits}}
                )
            )
            logger.info(f"💰 Added {credits} credits to user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding credits: {e}")
            return False

# ================== KEYBOARD BUILDERS ==================

class KeyboardBuilder:
    @staticmethod
    def main_menu(user_role: str = "user") -> List[List[Button]]:
        """Build main menu keyboard"""
        buttons = []
        
        # Search type buttons (2 per row)
        search_buttons = []
        for key, cmd in SEARCH_COMMANDS.items():
            search_buttons.append(Button.inline(cmd["name"], f"search_{key}"))
            
            if len(search_buttons) == 2:
                buttons.append(search_buttons)
                search_buttons = []
        
        # Add remaining button
        if search_buttons:
            buttons.append(search_buttons)
        
        # User menu options
        buttons.extend([
            [Button.inline("👤 My Profile", "profile"), Button.inline("🎁 Referrals", "referrals")],
            [Button.inline("💎 Premium Plans", "plans"), Button.inline("🆘 Support", "support")]
        ])
        
        # Admin options
        if user_role == "admin":
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def plans_menu() -> List[List[Button]]:
        """Build plans menu keyboard"""
        buttons = []
        
        for key, plan in PLANS.items():
            if plan["searches"] == -1:
                searches_text = f"Unlimited ({plan['days']} days)"
            else:
                searches_text = f"{plan['searches']} searches"
            
            button_text = f"{plan['name']}\n₹{plan['price']} • {searches_text}"
            buttons.append([Button.inline(button_text, f"buy_{key}")])
        
        buttons.append([Button.inline("🔙 Back to Main", "main_menu")])
        return buttons
    
    @staticmethod
    def admin_menu() -> List[List[Button]]:
        """Build admin menu keyboard"""
        return [
            [Button.inline("📊 Statistics", "admin_stats"), Button.inline("💳 Payments", "admin_payments")],
            [Button.inline("👥 User Management", "admin_users"), Button.inline("📝 Logs", "admin_logs")],
            [Button.inline("📢 Broadcast", "admin_broadcast"), Button.inline("⚙️ Settings", "admin_settings")],
            [Button.inline("🔙 Back to Main", "main_menu")]
        ]
    
    @staticmethod
    def referral_menu() -> List[List[Button]]:
        """Build referral menu keyboard"""
        return [
            [Button.inline("🔗 My Referral Link", "referral_link")],
            [Button.inline("📊 Referral Stats", "referral_stats")],
            [Button.inline("🔙 Back to Main", "main_menu")]
        ]
    
    @staticmethod
    def payment_approval_buttons(payment_id: str, user_id: int) -> List[List[Button]]:
        """Build payment approval buttons for admin"""
        return [
            [
                Button.inline("✅ Approve", f"approve_payment_{payment_id}_{user_id}"),
                Button.inline("❌ Reject", f"reject_payment_{payment_id}_{user_id}")
            ]
        ]

# ================== TELEGRAM CLIENTS ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

# ================== GLOBAL MANAGERS ==================

db_manager = DatabaseManager()
user_manager = None
search_engine = None
payment_manager = None
admin_panel = None
message_handler = None

# State tracking
user_states: Dict[int, Dict] = {}

# ================== CHANNEL MEMBERSHIP CHECK ==================

async def check_channel_membership(user_id: int) -> bool:
    """Check if user is member of mandatory channel"""
    try:
        channel = await bot_client.get_entity(config.MANDATORY_CHANNEL)
        
        try:
            participant = await bot_client(GetParticipantRequest(channel, user_id))
            from telethon.tl.types import ChannelParticipantBanned, ChannelParticipantLeft
            
            if isinstance(participant.participant, (ChannelParticipantBanned, ChannelParticipantLeft)):
                return False
            
            return True
            
        except Exception:
            return False
        
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

# ================== BOT EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start( (.+))?'))
async def start_handler(event):
    """Handle /start command"""
    user = await event.get_sender()
    user_id = user.id
    
    # Extract referral code if present
    referral_code = None
    if event.pattern_match.group(2):
        referral_code = event.pattern_match.group(2).strip()
    
    # Get or create user
    user_doc = await user_manager.get_user(user_id)
    if not user_doc:
        await user_manager.create_user(user_id, user.username, user.first_name, referral_code)
        user_doc = await user_manager.get_user(user_id)
        
        # Welcome message for new users with referral
        if referral_code:
            await event.respond(
                f"🎉 Welcome {user.first_name}!\n\n"
                f"Thanks for using a referral link!\n"
                f"You got {config.NEW_USER_CREDITS} free credits to start with.\n\n"
                "First, please join our channel to continue:"
            )
    
    # Check if user is banned
    if user_doc.get("banned"):
        await event.respond(
            "🚫 **Account Suspended**\n\n"
            "Your account has been suspended.\n"
            "Contact @darkboxesAdmin if you believe this is an error.",
            parse_mode="md"
        )
        return
    
    # Admin welcome
    if await admin_panel.is_admin(user_id):
        stats = await admin_panel.get_bot_statistics()
        await event.respond(
            "👑 **Admin Dashboard**\n\n"
            f"👥 Total Users: {stats.get('total_users', 0)}\n"
            f"💎 Premium Users: {stats.get('premium_users', 0)}\n"
            f"🔍 Total Searches: {stats.get('total_searches', 0)}\n"
            f"💰 Total Revenue: ₹{stats.get('total_revenue', 0)}\n"
            f"⏳ Pending Payments: {stats.get('pending_payments', 0)}\n\n"
            "Welcome back, Admin!",
            buttons=KeyboardBuilder.main_menu("admin"),
            parse_mode="md"
        )
        return
    
    # Check channel membership
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.respond(
            f"👋 **Welcome to Premium Info Bot!**\n\n"
            f"To use this bot, you must first join our channel:\n"
            f"@{config.MANDATORY_CHANNEL}\n\n"
            f"After joining, click the button below to verify.",
            buttons=[
                [Button.url(f"📢 Join Channel", f"https://t.me/{config.MANDATORY_CHANNEL}")],
                [Button.inline("✅ I've Joined - Verify", "check_membership")]
            ],
            parse_mode="md"
        )
        return
    
    # Main welcome message
    plan_expiry = ""
    if user_doc.get("plan_expiry"):
        try:
            expiry = datetime.fromisoformat(user_doc["plan_expiry"])
            days_left = (expiry - datetime.now(timezone.utc)).days
            if days_left > 0:
                plan_expiry = f" ({days_left} days left)"
        except Exception:
            pass
    
    await event.respond(
        f"👋 **Welcome {user.first_name}!**\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}{plan_expiry}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        f"Select a search type below:",
        buttons=KeyboardBuilder.main_menu(),
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_callback(event):
    """Handle search type selection"""
    user_id = event.sender_id
    search_type = event.data.decode().split('_', 1)[1]
    
    if search_type not in SEARCH_COMMANDS:
        await event.answer("❌ Invalid search type", alert=True)
        return
    
    # Check if user exists and is not banned
    user_doc = await user_manager.get_user(user_id)
    if not user_doc:
        await event.answer("❌ User not found", alert=True)
        return
    
    if user_doc.get("banned"):
        await event.answer("❌ Account suspended", alert=True)
        return
    
    # Check credits (skip for admin)
    if not await admin_panel.is_admin(user_id):
        searches_remaining = user_doc.get('searches_remaining', 0)
        plan = user_doc.get('plan', 'free')
        
        # Check plan expiry
        if plan == 'unlimited' and user_doc.get('plan_expiry'):
            try:
                expiry = datetime.fromisoformat(user_doc['plan_expiry'])
                if expiry < datetime.now(timezone.utc):
                    # Plan expired, reset to free
                    await user_manager.users_col.update_one(
                        {"user_id": user_id},
                        {"$set": {"plan": "free", "searches_remaining": 0, "plan_expiry": None}}
                    )
                    searches_remaining = 0
            except Exception:
                pass
        
        if searches_remaining <= 0 and plan != 'unlimited':
            await event.edit(
                "❌ **No Credits Remaining**\n\n"
                "You need to purchase a premium plan to continue using the bot.\n\n"
                "Choose a plan below:",
                buttons=KeyboardBuilder.plans_menu(),
                parse_mode="md"
            )
            return
    
    # Set user state for input
    command_info = SEARCH_COMMANDS[search_type]
    user_states[user_id] = {"action": "awaiting_input", "type": search_type}
    
    credits_text = f"{user_doc.get('searches_remaining', 0)}" if user_doc.get('searches_remaining', 0) > 0 else "Unlimited"
    
    await event.edit(
        f"🔍 **{command_info['name']}**\n\n"
        f"📝 {command_info['description']}\n\n"
        f"💳 Credits: {credits_text}\n\n"
        f"📤 Example: `{command_info['example']}`\n"
        f"Please send your query below:",
        buttons=[[Button.inline("❌ Cancel", "cancel")]],
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern=r'^interactive_'))
async def interactive_callback(event):
    """Handle interactive bot button clicks"""
    user_id = event.sender_id
    button_data = event.data.decode()
    
    await event.answer("⏳ Processing...")
    
    # Handle button click
    result = await search_engine.handle_interactive_button(user_id, button_data)
    
    if result["success"]:
        await event.edit(result["result"])
        
        # Handle file if present
        if result.get("file"):
            try:
                await bot_client.forward_messages(user_id, result["file"])
            except Exception as e:
                logger.error(f"Error forwarding file: {e}")
        
        # Deduct credit
        if not await admin_panel.is_admin(user_id):
            await user_manager.update_searches(user_id, -1)
        
        # Clear user state
        user_states.pop(user_id, None)
        
    elif result.get("needs_interaction"):
        await event.edit(
            result["message"],
            buttons=result["buttons"]
        )
    else:
        await event.edit(f"❌ {result.get('error', 'Unknown error')}")
        user_states.pop(user_id, None)

@bot_client.on(events.CallbackQuery(pattern='^buy_'))
async def buy_plan_callback(event):
    """Handle plan purchase"""
    user_id = event.sender_id
    plan_key = event.data.decode().split('_', 1)[1]
    
    if plan_key not in PLANS:
        await event.answer("❌ Invalid plan", alert=True)
        return
    
    plan = PLANS[plan_key]
    
    # Create payment request
    payment_id = await payment_manager.create_payment_request(user_id, plan_key)
    if not payment_id:
        await event.answer("❌ Error creating payment request", alert=True)
        return
    
    # Set user state
    user_states[user_id] = {
        "action": "awaiting_payment",
        "payment_id": payment_id,
        "plan": plan_key
    }
    
    # Notify admin
    try:
        user = await event.get_sender()
        await bot_client.send_message(
            config.ADMIN_USER_ID,
            f"💳 **New Payment Request**\n\n"
            f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 User ID: {user_id}\n"
            f"📦 Plan: {plan['name']}\n"
            f"💰 Amount: ₹{plan['price']}\n"
            f"🔢 Payment ID: `{payment_id}`\n\n"
            f"⏳ Waiting for payment screenshot...",
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")
    
    await event.edit(
        f"💳 **Payment Required**\n\n"
        f"📦 Plan: {plan['name']}\n"
        f"💰 Amount: ₹{plan['price']}\n"
        f"🔢 Payment ID: `{payment_id}`\n\n"
        f"Please make the payment and send a screenshot here.\n"
        f"Admin will verify and activate your plan.",
        buttons=[[Button.inline("❌ Cancel", "cancel")]],
        parse_mode="md"
    )
    
    # Send payment QR code if available
    try:
        if config.PAYMENT_QR_CODE:
            await bot_client.send_file(
                user_id,
                config.PAYMENT_QR_CODE,
                caption="📱 Scan this QR code to make payment"
            )
    except Exception as e:
        logger.error(f"Error sending payment QR: {e}")

@bot_client.on(events.CallbackQuery(pattern='^approve_payment_'))
async def approve_payment_callback(event):
    """Handle payment approval by admin"""
    if not await admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    if len(data_parts) < 4:
        await event.answer("❌ Invalid data", alert=True)
        return
    
    payment_id = data_parts[2]
    target_user_id = int(data_parts[3])
    
    # Approve payment
    success = await payment_manager.approve_payment(payment_id)
    
    if success:
        await event.edit(
            f"✅ **Payment Approved**\n\n"
            f"Payment ID: {payment_id}\n"
            f"User ID: {target_user_id}\n\n"
            f"User has been notified and plan activated."
        )
        
        # Notify user
        try:
            await bot_client.send_message(
                target_user_id,
                "🎉 **Payment Approved!**\n\n"
                "Your premium plan has been activated!\n"
                "You can now start using all search features.\n\n"
                "Thank you for choosing our service! 💎",
                buttons=[[Button.inline("🚀 Start Searching", "main_menu")]]
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    else:
        await event.answer("❌ Error approving payment", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^reject_payment_'))
async def reject_payment_callback(event):
    """Handle payment rejection by admin"""
    if not await admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    data_parts = event.data.decode().split('_')
    if len(data_parts) < 4:
        await event.answer("❌ Invalid data", alert=True)
        return
    
    payment_id = data_parts[2]
    target_user_id = int(data_parts[3])
    
    # Reject payment
    success = await payment_manager.reject_payment(payment_id)
    
    if success:
        await event.edit(
            f"❌ **Payment Rejected**\n\n"
            f"Payment ID: {payment_id}\n"
            f"User ID: {target_user_id}"
        )
        
        # Notify user
        try:
            await bot_client.send_message(
                target_user_id,
                "❌ **Payment Rejected**\n\n"
                "Your payment screenshot was not approved.\n"
                "Please contact support or try again with a clear screenshot.\n\n"
                "Support: @darkboxesAdmin"
            )
        except Exception as e:
            logger.error(f"Error notifying user: {e}")
    else:
        await event.answer("❌ Error rejecting payment", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^admin_'))
async def admin_callback(event):
    """Handle admin panel callbacks"""
    if not await admin_panel.is_admin(event.sender_id):
        await event.answer("❌ Unauthorized", alert=True)
        return
    
    action = event.data.decode().split('_', 1)[1]
    
    if action == "panel":
        stats = await admin_panel.get_bot_statistics()
        await event.edit(
            "⚙️ **Admin Panel**\n\n"
            f"📊 **Today's Stats:**\n"
            f"• New Users: {stats.get('today_users', 0)}\n"
            f"• Searches: {stats.get('today_searches', 0)}\n"
            f"• Payments: {stats.get('today_payments', 0)}\n\n"
            f"📈 **Overall Stats:**\n"
            f"• Total Users: {stats.get('total_users', 0)}\n"
            f"• Premium Users: {stats.get('premium_users', 0)}\n"
            f"• Total Revenue: ₹{stats.get('total_revenue', 0)}",
            buttons=KeyboardBuilder.admin_menu(),
            parse_mode="md"
        )
    
    elif action == "stats":
        stats = await admin_panel.get_bot_statistics()
        popular_searches = stats.get('popular_searches', [])
        
        search_breakdown = "\n".join([
            f"• {item['_id']}: {item['count']}" for item in popular_searches[:5]
        ]) if popular_searches else "No data available"
        
        await event.edit(
            f"📊 **Detailed Statistics**\n\n"
            f"👥 **Users:**\n"
            f"• Total: {stats.get('total_users', 0)}\n"
            f"• Premium: {stats.get('premium_users', 0)}\n"
            f"• Today: {stats.get('today_users', 0)}\n\n"
            f"🔍 **Searches:**\n"
            f"• Total: {stats.get('total_searches', 0)}\n"
            f"• Successful: {stats.get('successful_searches', 0)}\n"
            f"• Success Rate: {stats.get('success_rate', 0)}%\n"
            f"• Today: {stats.get('today_searches', 0)}\n\n"
            f"💰 **Revenue:**\n"
            f"• Total: ₹{stats.get('total_revenue', 0)}\n"
            f"• Approved: {stats.get('approved_payments', 0)}\n"
            f"• Pending: {stats.get('pending_payments', 0)}\n\n"
            f"🔥 **Popular Searches:**\n{search_breakdown}",
            buttons=[[Button.inline("🔙 Back", "admin_panel")]],
            parse_mode="md"
        )
    
    elif action == "payments":
        pending_payments = await payment_manager.get_pending_payments(5)
        
        if not pending_payments:
            await event.edit(
                "✅ **No Pending Payments**\n\n"
                "All payments have been processed.",
                buttons=[[Button.inline("🔙 Back", "admin_panel")]]
            )
            return
        
        message = "💳 **Pending Payment Requests**\n\n"
        buttons = []
        
        for payment in pending_payments:
            plan = PLANS.get(payment['plan'], {})
            created = payment.get('created_at', '')[:10]  # Just date
            
            message += (
                f"🔸 **Payment {payment['payment_id'][:8]}...**\n"
                f"👤 User ID: {payment['user_id']}\n"
                f"📦 Plan: {plan.get('name', 'Unknown')}\n"
                f"💰 Amount: ₹{payment['amount']}\n"
                f"📅 Date: {created}\n\n"
            )
            
            buttons.append([
                Button.inline("✅ Approve", f"approve_payment_{payment['payment_id']}_{payment['user_id']}"),
                Button.inline("❌ Reject", f"reject_payment_{payment['payment_id']}_{payment['user_id']}")
            ])
        
        buttons.append([Button.inline("🔙 Back", "admin_panel")])
        await event.edit(message, buttons=buttons, parse_mode="md")

@bot_client.on(events.CallbackQuery(pattern='^profile$'))
async def profile_callback(event):
    """Handle profile view"""
    user_id = event.sender_id
    user_doc = await user_manager.get_user(user_id)
    
    if not user_doc:
        await event.answer("❌ User not found", alert=True)
        return
    
    # Calculate plan details
    plan_info = ""
    if user_doc.get('plan_expiry'):
        try:
            expiry = datetime.fromisoformat(user_doc['plan_expiry'])
            days_left = (expiry - datetime.now(timezone.utc)).days
            if days_left > 0:
                plan_info = f" (expires in {days_left} days)"
            else:
                plan_info = " (expired)"
        except Exception:
            pass
    
    # Get referral stats
    referrals_given = await asyncio.get_running_loop().run_in_executor(
        None, 
        lambda: db_manager.get_collection('referrals').count_documents({"referrer_id": user_id})
    )
    
    join_date = user_doc.get('joined_at', '')[:10] if user_doc.get('joined_at') else 'Unknown'
    
    await event.edit(
        f"👤 **My Profile**\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"👤 Name: {user_doc.get('first_name', 'N/A')}\n"
        f"📅 Joined: {join_date}\n\n"
        f"📊 **Plan & Credits:**\n"
        f"• Plan: {user_doc.get('plan', 'free').upper()}{plan_info}\n"
        f"• Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"• Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        f"👥 **Referrals:**\n"
        f"• Friends Referred: {referrals_given}\n"
        f"• Referral Code: `{user_doc.get('referral_code', 'N/A')}`",
        buttons=[[Button.inline("🔙 Back to Main", "main_menu")]],
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern='^referrals$'))
async def referrals_callback(event):
    """Handle referrals menu"""
    await event.edit(
        f"👥 **Referral System**\n\n"
        f"💰 Earn {config.REFERRAL_REWARD} credits for each friend!\n\n"
        f"📝 **How it works:**\n"
        f"1. Share your referral link\n"
        f"2. Friend joins using your link\n"
        f"3. When they make their first search, you get {config.REFERRAL_REWARD} credits!\n\n"
        f"🎁 **Benefits:**\n"
        f"• Unlimited referrals\n"
        f"• Instant credit rewards\n"
        f"• Help friends discover the bot",
        buttons=KeyboardBuilder.referral_menu(),
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern='^referral_'))
async def referral_callback(event):
    """Handle referral actions"""
    user_id = event.sender_id
    action = event.data.decode().split('_', 1)[1]
    
    if action == "link":
        user_doc = await user_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        referral_code = user_doc.get('referral_code', 'N/A')
        bot_info = await bot_client.get_me()
        referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
        
        await event.edit(
            f"🔗 **Your Referral Link**\n\n"
            f"`{referral_link}`\n\n"
            f"📋 **Copy and share this link!**\n\n"
            f"💡 **Tips for sharing:**\n"
            f"• Share in groups and channels\n"
            f"• Send to friends directly\n"
            f"• Post on social media\n"
            f"• Add to your bio/status\n\n"
            f"🎯 You earn {config.REFERRAL_REWARD} credits per successful referral!",
            buttons=[[Button.inline("🔙 Back", "referrals")]],
            parse_mode="md"
        )
    
    elif action == "stats":
        # Get referral statistics
        referrals_given = await asyncio.get_running_loop().run_in_executor(
            None, 
            lambda: db_manager.get_collection('referrals').count_documents({"referrer_id": user_id})
        )
        
        referrals_rewarded = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: db_manager.get_collection('referrals').count_documents({
                "referrer_id": user_id, 
                "reward_given": True
            })
        )
        
        total_earned = referrals_rewarded * config.REFERRAL_REWARD
        pending_rewards = referrals_given - referrals_rewarded
        
        await event.edit(
            f"📊 **Your Referral Statistics**\n\n"
            f"👥 **Referrals:**\n"
            f"• Total Sent: {referrals_given}\n"
            f"• Successful: {referrals_rewarded}\n"
            f"• Pending: {pending_rewards}\n\n"
            f"💰 **Earnings:**\n"
            f"• Credits Earned: {total_earned}\n"
            f"• Per Referral: {config.REFERRAL_REWARD} credits\n\n"
            f"⏳ Pending rewards will be given when your friends make their first search.",
            buttons=[[Button.inline("🔙 Back", "referrals")]],
            parse_mode="md"
        )

@bot_client.on(events.CallbackQuery(pattern='^plans$'))
async def plans_callback(event):
    """Handle plans menu"""
    message = "💎 **Premium Plans**\n\n"
    
    for key, plan in PLANS.items():
        searches_text = (
            f"Unlimited searches for {plan['days']} days" 
            if plan['searches'] == -1 
            else f"{plan['searches']} searches"
        )
        
        features = '\n'.join([f"  • {feature}" for feature in plan.get('features', [])])
        
        message += (
            f"🔸 **{plan['name']}**\n"
            f"💰 Price: ₹{plan['price']}\n"
            f"🔍 Benefit: {searches_text}\n"
            f"📝 {plan['description']}\n"
            f"✨ Features:\n{features}\n\n"
        )
    
    await event.edit(
        message,
        buttons=KeyboardBuilder.plans_menu(),
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern='^support$'))
async def support_callback(event):
    """Handle support"""
    await event.edit(
        f"🆘 **Support & Help**\n\n"
        f"📞 **Contact Admin:**\n"
        f"• Telegram: @darkboxesAdmin\n"
        f"• For payment issues, include your User ID: `{event.sender_id}`\n\n"
        f"❓ **Common Issues:**\n"
        f"• Payment not approved → Contact admin with screenshot\n"
        f"• Search not working → Try different format\n"
        f"• Credits not added → Contact with payment proof\n\n"
        f"⏰ **Response Time:** Usually within 24 hours\n\n"
        f"💡 **Tip:** Include your User ID in all support messages!",
        buttons=[[Button.inline("🔙 Back to Main", "main_menu")]],
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern='^check_membership$'))
async def check_membership_callback(event):
    """Handle channel membership verification"""
    user_id = event.sender_id
    
    is_member = await check_channel_membership(user_id)
    
    if not is_member:
        await event.answer(
            "❌ You haven't joined the channel yet. Please join first and try again.",
            alert=True
        )
        return
    
    # Update user as verified
    await asyncio.get_running_loop().run_in_executor(
        None, lambda: user_manager.users_col.update_one(
            {"user_id": user_id},
            {"$set": {"channel_joined": True}}
        )
    )
    
    user_doc = await user_manager.get_user(user_id)
    
    await event.edit(
        f"✅ **Verification Successful!**\n\n"
        f"Welcome to the Premium Info Bot!\n\n"
        f"📊 **Your Account:**\n"
        f"• Plan: {user_doc.get('plan', 'free').upper()}\n"
        f"• Credits: {user_doc.get('searches_remaining', 0)}\n\n"
        f"🔍 Choose a search type below to get started:",
        buttons=KeyboardBuilder.main_menu(),
        parse_mode="md"
    )

@bot_client.on(events.CallbackQuery(pattern='^(main_menu|cancel)$'))
async def main_menu_callback(event):
    """Handle main menu and cancel actions"""
    user_id = event.sender_id
    
    # Clear user state
    user_states.pop(user_id, None)
    
    user_doc = await user_manager.get_user(user_id)
    if not user_doc:
        await event.answer("❌ User not found", alert=True)
        return
    
    # Check if admin
    user_role = "admin" if await admin_panel.is_admin(user_id) else "user"
    
    plan_expiry = ""
    if user_doc.get("plan_expiry"):
        try:
            expiry = datetime.fromisoformat(user_doc["plan_expiry"])
            days_left = (expiry - datetime.now(timezone.utc)).days
            if days_left > 0:
                plan_expiry = f" ({days_left} days left)"
        except Exception:
            pass
    
    await event.edit(
        f"🏠 **Main Menu**\n\n"
        f"📊 Plan: {user_doc.get('plan', 'free').upper()}{plan_expiry}\n"
        f"🔍 Credits: {user_doc.get('searches_remaining', 0)}\n"
        f"📈 Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        f"Select a search type below:",
        buttons=KeyboardBuilder.main_menu(user_role),
        parse_mode="md"
    )

# ================== PRIVATE MESSAGE HANDLER ==================

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/') and e.text))
async def private_message_handler(event):
    """Handle private messages based on user state"""
    user_id = event.sender_id
    
    if user_id not in user_states:
        return
    
    state = user_states[user_id]
    action = state.get('action')
    
    # Handle search input
    if action == 'awaiting_input':
        search_type = state['type']
        query = event.text.strip()
        
        if not query:
            await event.respond("❌ Please send a valid query.")
            return
        
        # Show processing message
        status_msg = await event.respond(
            "🔍 **Searching...**\n\n"
            "⏳ Please wait 15-30 seconds while we search through our databases.\n\n"
            "💡 We search multiple sources to get you the best results!",
            parse_mode="md"
        )
        
        # Perform search
        result = await search_engine.perform_search(search_type, query, user_id)
        
        # Delete status message
        try:
            await status_msg.delete()
        except Exception:
            pass
        
        if result.get('success'):
            # Send result
            await event.respond(result['result'])
            
            # Handle file if present
            if result.get('file'):
                try:
                    await bot_client.forward_messages(user_id, result['file'])
                except Exception as e:
                    logger.error(f"Error forwarding file: {e}")
            
            # Deduct credit (skip for admin)
            if not await admin_panel.is_admin(user_id):
                await user_manager.update_searches(user_id, -1)
                
                # Check if this was user's first search (for referral reward)
                user_doc = await user_manager.get_user(user_id)
                if user_doc.get('total_searches') == 1 and user_doc.get('referred_by'):
                    await user_manager.reward_referrer(user_id)
            
        elif result.get('needs_interaction'):
            # Handle interactive search (telegram, movie bots)
            await event.respond(
                result['message'],
                buttons=result['buttons']
            )
            return  # Don't clear state, wait for button interaction
            
        else:
            # Search failed
            error_msg = result.get('error', 'Unknown error occurred')
            await event.respond(f"❌ **Search Failed**\n\n{error_msg}", parse_mode="md")
        
        # Clear user state
        user_states.pop(user_id, None)
    
    # Handle payment screenshot
    elif action == 'awaiting_payment':
        if not event.photo:
            await event.respond(
                "❌ **Invalid File**\n\n"
                "Please send a payment screenshot image.",
                parse_mode="md"
            )
            return
        
        payment_id = state['payment_id']
        plan_key = state['plan']
        plan = PLANS.get(plan_key, {})
        
        # Update payment with screenshot
        await payment_manager.update_payment_screenshot(payment_id, str(event.message.id))
        
        # Forward screenshot to admin
        try:
            user = await event.get_sender()
            await bot_client.send_file(
                config.ADMIN_USER_ID,
                event.photo,
                caption=(
                    f"💳 **Payment Screenshot**\n\n"
                    f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 User ID: {user_id}\n"
                    f"📦 Plan: {plan.get('name', 'Unknown')}\n"
                    f"💰 Amount: ₹{plan.get('price', 0)}\n"
                    f"🔢 Payment ID: `{payment_id}`"
                ),
                buttons=KeyboardBuilder.payment_approval_buttons(payment_id, user_id),
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Error forwarding to admin: {e}")
        
        await event.respond(
            "✅ **Screenshot Received!**\n\n"
            "📋 Your payment is being reviewed by admin.\n"
            "🔔 You'll be notified once it's approved.\n\n"
            "⏰ Usually takes 1-24 hours to process.\n\n"
            "Thank you for your patience! 💙",
            parse_mode="md"
        )
        
        # Clear user state
        user_states.pop(user_id, None)

# ================== GROUP MESSAGE HANDLER ==================

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all messages for search responses"""
    await message_handler.handle_group_message(event)

# ================== CLEANUP TASKS ==================

async def cleanup_expired_searches():
    """Clean up expired pending searches"""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            
            current_time = time.time()
            expired_searches = []
            
            for search_id, search_info in list(search_engine.pending_searches.items()):
                # Check if search is older than max timeout
                if current_time - search_info.get('timestamp', current_time) > 300:  # 5 minutes
                    expired_searches.append(search_id)
            
            for search_id in expired_searches:
                search_info = search_engine.pending_searches.pop(search_id, None)
                if search_info and not search_info['future'].done():
                    try:
                        search_info['future'].set_exception(TimeoutError("Search expired"))
                    except Exception:
                        pass
            
            if expired_searches:
                logger.info(f"🧹 Cleaned up {len(expired_searches)} expired searches")
            
            # Clean up expired interactive sessions
            expired_sessions = []
            for user_id, session in list(search_engine.interactive_sessions.items()):
                session_time = session.get('timestamp', current_time)
                if current_time - session_time > 600:  # 10 minutes
                    expired_sessions.append(user_id)
            
            for user_id in expired_sessions:
                search_engine.interactive_sessions.pop(user_id, None)
            
            if expired_sessions:
                logger.info(f"🧹 Cleaned up {len(expired_sessions)} expired interactive sessions")
                
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

async def cleanup_user_states():
    """Clean up expired user states"""
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            
            # Remove user states older than 30 minutes
            current_time = time.time()
            expired_states = []
            
            for user_id, state in list(user_states.items()):
                state_time = state.get('timestamp', current_time)
                if current_time - state_time > 1800:  # 30 minutes
                    expired_states.append(user_id)
            
            for user_id in expired_states:
                user_states.pop(user_id, None)
            
            if expired_states:
                logger.info(f"🧹 Cleaned up {len(expired_states)} expired user states")
                
        except Exception as e:
            logger.error(f"Error cleaning user states: {e}")

# ================== WEB SERVER ==================

async def start_web_server():
    """Start web server for health checks"""
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    async def bot_stats(request):
        if not admin_panel:
            return web.json_response({"error": "Bot not ready"}, status=503)
        
        stats = await admin_panel.get_bot_statistics()
        return web.json_response({
            "status": "running",
            "users": stats.get('total_users', 0),
            "searches_today": stats.get('today_searches', 0),
            "uptime": int(time.time() - start_time)
        })
    
    app.router.add_get("/health", health_check)
    app.router.add_get("/stats", bot_stats)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server started on port {config.PORT}")
    except Exception as e:
        logger.error(f"❌ Failed to start web server: {e}")

# ================== INITIALIZATION ==================

start_time = time.time()

async def initialize_clients():
    """Initialize Telegram clients"""
    global user_manager, search_engine, payment_manager, admin_panel, message_handler
    
    try:
        # Start bot client
        logger.info("🤖 Starting bot client...")
        await bot_client.start(bot_token=config.BOT_TOKEN)
        
        me = await bot_client.get_me()
        logger.info(f"✅ Bot started: @{me.username}")
        
        # Start user client if configured
        if USE_USER_ACCOUNT:
            logger.info("👤 Starting user client...")
            if not user_client.is_connected():
                await user_client.connect()
            
            if not await user_client.is_user_authorized():
                raise RuntimeError("❌ User account not authorized")
            
            logger.info("✅ User client started")
        
        # Connect to database
        logger.info("💾 Connecting to database...")
        if not await db_manager.connect():
            raise RuntimeError("❌ Database connection failed")
        
        # Initialize managers
        user_manager = UserManager(db_manager)
        search_engine = SearchEngine(db_manager, user_manager)
        payment_manager = PaymentManager(db_manager)
        admin_panel = AdminPanel(db_manager, user_manager)
        message_handler = MessageHandler(search_engine)
        
        # Resolve group entities
        logger.info("📡 Resolving destination groups...")
        for group in DESTINATION_GROUPS:
            try:
                group['entity'] = await user_client.get_entity(group['identifier'])
                logger.info(f"✅ Resolved {group['name']}")
            except Exception as e:
                logger.warning(f"⚠️ Could not resolve {group['name']}: {e}")
        
        # Resolve special bot entities
        for key, bot in SPECIAL_BOTS.items():
            try:
                bot['entity'] = await user_client.get_entity(bot['identifier'])
                logger.info(f"✅ Resolved {bot['name']}")
            except Exception as e:
                logger.warning(f"⚠️ Could not resolve {key} bot: {e}")
        
        logger.info("✅ All managers initialized")
        return True
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        return False

# ================== MAIN FUNCTION ==================

async def main():
    """Main bot execution function"""
    try:
        logger.info("🚀 Starting Advanced Premium Info Bot...")
        logger.info(f"📊 Config: {len(SEARCH_COMMANDS)} search types, {len(PLANS)} plans")
        
        # Initialize everything
        if not await initialize_clients():
            logger.error("❌ Failed to initialize. Exiting...")
            return
        
        # Start background tasks
        logger.info("🔧 Starting background tasks...")
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(cleanup_user_states())
        asyncio.create_task(start_web_server())
        
        # Log successful startup
        stats = await admin_panel.get_bot_statistics()
        logger.info("=" * 60)
        logger.info("🎉 BOT SUCCESSFULLY STARTED!")
        logger.info(f"👥 Total Users: {stats.get('total_users', 0)}")
        logger.info(f"💎 Premium Users: {stats.get('premium_users', 0)}")
        logger.info(f"🔍 Total Searches: {stats.get('total_searches', 0)}")
        logger.info(f"💰 Total Revenue: ₹{stats.get('total_revenue', 0)}")
        logger.info("=" * 60)
        
        # Notify admin of startup
        try:
            await bot_client.send_message(
                config.ADMIN_USER_ID,
                f"🚀 **Bot Started Successfully!**\n\n"
                f"📊 **Current Stats:**\n"
                f"• Users: {stats.get('total_users', 0)}\n"
                f"• Premium: {stats.get('premium_users', 0)}\n"
                f"• Revenue: ₹{stats.get('total_revenue', 0)}\n\n"
                f"✅ All systems operational!",
                parse_mode="md"
            )
        except Exception as e:
            logger.warning(f"Could not notify admin: {e}")
        
        # Keep running
        logger.info("🔄 Bot is running... Press Ctrl+C to stop")
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception(f"❌ Fatal error: {e}")
    finally:
        # Cleanup
        try:
            logger.info("🧹 Cleaning up...")
            if bot_client.is_connected():
                await bot_client.disconnect()
            if USE_USER_ACCOUNT and user_client.is_connected():
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
            logger.info("✅ Cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# ================== ENTRY POINT ==================

if __name__ == "__main__":
    try:
        # Set event loop policy for better performance on Windows
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        # Run the bot
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Failed to start bot: {e}")
