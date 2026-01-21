"""
Premium Information Bot - Advanced Edition
Enhanced with better file processing, cascading search, and admin notifications
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
    from telethon.tl.types import User, MessageMediaDocument, MessageMediaPhoto
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
        "priority": 1,
        "commands": {
            "phone": "/num",
            "family": "/familyinfo",
            "aadhar": "/aadhar",
            "vehicle": "/vehicle",
            "upi": "/upiinfo",
            "fampay": "/fam",
            "email": "/email",
            "imei": "/imei",
            "gst": "/gst",
            "insta": "/insta",
            "pak": "/cnic"
        }
    },
    {
        "name": "Backup Group 2",
        "identifier": "darkboxesv3",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 2,
        "commands": {
            "phone": "/phone",
            "family": "/family",
            "aadhar": "/adh",
            "vehicle": "/vnum",
            "upi": "/upi",
            "fampay": "/fampay",
            "email": "/mail",
            "imei": "/device",
            "gst": "/gstin",
            "insta": "/instagram",
            "pak": "/pak"
        }
    },
    {
        "name": "Backup Group 3",
        "identifier": "nex_chats",
        "timeout": config.GROUP_TIMEOUT,
        "entity": None,
        "priority": 3,
        "commands": {
            "phone": "/mobile",
            "family": "/familyinfo",
            "aadhar": "/aadhaar",
            "vehicle": "/car",
            "upi": "/upiinfo",
            "fampay": "/fam",
            "email": "/email",
            "imei": "/imei",
            "gst": "/gst",
            "insta": "/insta",
            "pak": "/cnic"
        }
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
        "name": "📱 Phone Number",
        "description": "Get detailed information from phone number",
        "commands": ["/num", "/phone", "/mobile"],
        "destination": "groups",
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "emoji": "📱"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Info",
        "description": "Get family member details from phone",
        "commands": ["/familyinfo", "/family"],
        "destination": "groups",
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "emoji": "👨‍👩‍👧‍👦"
    },
    "aadhar": {
        "name": "🆔 Aadhar Card",
        "description": "Get information from Aadhar number",
        "commands": ["/aadhar", "/adh", "/aadhaar"],
        "destination": "groups",
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "emoji": "🆔"
    },
    "vehicle": {
        "name": "🚗 Vehicle Info",
        "description": "Get vehicle and owner details",
        "commands": ["/vehicle", "/vnum", "/car"],
        "destination": "groups",
        "example": "UP16BH1234",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "emoji": "🚗"
    },
    "upi": {
        "name": "💳 UPI ID",
        "description": "Get UPI account information",
        "commands": ["/upiinfo", "/upi"],
        "destination": "groups",
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "emoji": "💳"
    },
    "fampay": {
        "name": "💰 FamPay",
        "description": "Get FamPay account details",
        "commands": ["/fam", "/fampay"],
        "destination": "groups",
        "example": "9876543210",
        "validation": r"^\d{10}$",
        "emoji": "💰"
    },
    "email": {
        "name": "📧 Email",
        "description": "Search email address details",
        "commands": ["/email", "/mail"],
        "destination": "groups",
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "emoji": "📧"
    },
    "telegram": {
        "name": "📲 Telegram Phone",
        "description": "Get phone from Telegram username",
        "commands": ["/tg", "/telegram"],
        "destination": "telegram",
        "example": "@username",
        "validation": r"^@?\w{5,32}$",
        "daily_limit": 1,
        "emoji": "📲"
    },
    "telegram_username": {
        "name": "👤 Telegram User",
        "description": "Get details from Telegram username",
        "commands": ["/tguser", "/tginfo"],
        "destination": "telegram_username",
        "example": "@username",
        "validation": r"^@?\w{5,32}$",
        "daily_limit": 1,
        "emoji": "👤"
    },
    "imei": {
        "name": "📱 IMEI",
        "description": "Get device info from IMEI",
        "commands": ["/imei", "/device"],
        "destination": "groups",
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "emoji": "📱"
    },
    "gst": {
        "name": "🏢 GST",
        "description": "Get business info from GST number",
        "commands": ["/gst", "/gstin"],
        "destination": "groups",
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "emoji": "🏢"
    },
    "insta": {
        "name": "📷 Instagram",
        "description": "Search Instagram profile details",
        "commands": ["/insta", "/instagram"],
        "destination": "groups",
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "emoji": "📷"
    },
    "pak": {
        "name": "🇵🇰 Pakistan CNIC",
        "description": "Get Pakistan CNIC details",
        "commands": ["/cnic", "/pak"],
        "destination": "groups",
        "example": "42101-1234567-8",
        "validation": r"^\d{5}-\d{7}-\d{1}$",
        "emoji": "🇵🇰"
    },
    "movies": {
        "name": "🎬 Movies/Series",
        "description": "Search movies and web series",
        "commands": [""],
        "destination": "movie",
        "example": "Avengers",
        "validation": r"^.{2,50}$",
        "emoji": "🎬"
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
                'failed_searches': self.db['failed_searches'],
                'referrals': self.db['referrals']
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
            
            # Failed searches for admin review
            self.collections['failed_searches'].create_index([("user_id", 1)])
            self.collections['failed_searches'].create_index([("timestamp", -1)])
            self.collections['failed_searches'].create_index([("reviewed", 1)])
            
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.warning(f"⚠️ Index creation warning: {e}")
    
    def get_collection(self, name: str):
        """Get collection by name"""
        return self.collections.get(name)

# ================== TEXT PROCESSING UTILITIES ==================

class TextProcessor:
    @staticmethod
    def is_processing_message(text: str) -> bool:
        """Check if message indicates processing"""
        if not text:
            return True
        
        text_lower = text.lower()
        processing_keywords = [
            'processing', 'please wait', 'fetching', 'loading', 'searching',
            'retrieving', 'hold on', 'wait a moment', 'in progress',
            'gathering data', 'working on it', '⏳', '🔍', 'searching for',
            'please wait while', 'getting information', 'fetching data',
            'looking up', 'checking databases', 'analyzing', 'scanning',
            '正在处理', '处理中', '请稍候', '搜索中'
        ]
        
        return any(keyword in text_lower for keyword in processing_keywords)
    
    @staticmethod
    def is_no_info_message(text: str) -> bool:
        """Check if message indicates no information found"""
        if not text:
            return False
        
        text_lower = text.lower()
        no_info_keywords = [
            'no info', 'no information', 'not found', 'no data', 'no result',
            'no record', 'invalid', 'doesn\'t exist', 'does not exist',
            'not available', 'no details', 'unable to find', 'could not find',
            'couldn\'t find', 'no match', 'not exist', 'no information found',
            'to reduce spam', 'must have joined', 'join all channels',
            'verify your account', 'admin to verify', 'subscription required',
            'data not available', 'information unavailable', 'no records',
            'record not found', '查无此人', '没有找到', '无结果', '未找到'
        ]
        
        return any(keyword in text_lower for keyword in no_info_keywords)
    
    @staticmethod
    def is_error_message(text: str) -> bool:
        """Check if message indicates an error"""
        if not text:
            return False
        
        text_lower = text.lower()
        error_keywords = [
            'error', 'failed', 'invalid', 'unable to', 'could not',
            'something went wrong', 'try again', 'contact admin',
            'admin contact', 'support', 'issue', 'problem', 'bug',
            '出错', '错误', '失败', '无效'
        ]
        
        return any(keyword in text_lower for keyword in error_keywords)
    
    @staticmethod
    def extract_file_content(text: str) -> str:
        """Extract meaningful content from text"""
        if not text:
            return ""
        
        # Remove URLs and mentions
        patterns = [
            r'https?://\S+',
            r'www\.\S+',
            r't\.me/\S+',
            r'@\w+',
            r'tg://\S+',
            r'powered by.*',
            r'developed by.*',
            r'created by.*',
            r'designed by.*',
            r'©.*',
            r'copyright.*',
            r'join.*channel',
            r'subscribe.*',
            r'follow.*',
            r'contact.*admin',
            r'admin.*@\w+'
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Remove multiple newlines and spaces
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def process_file_content(content: str, search_type: str) -> str:
        """Process file content with search type specific formatting"""
        if not content:
            return ""
        
        # Clean the content
        content = TextProcessor.extract_file_content(content)
        
        # Format based on search type
        if search_type == "family":
            return TextProcessor._format_family_info(content)
        elif search_type == "phone":
            return TextProcessor._format_phone_info(content)
        elif search_type == "aadhar":
            return TextProcessor._format_aadhar_info(content)
        elif search_type == "vehicle":
            return TextProcessor._format_vehicle_info(content)
        
        return content
    
    @staticmethod
    def _format_family_info(content: str) -> str:
        """Format family information"""
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 3:
                continue
            
            # Skip promotional lines
            if any(keyword in line.lower() for keyword in ['powered', 'developed', 'created', 'admin', 'join', 'subscribe']):
                continue
            
            # Format family member lines
            if any(marker in line for marker in [':', '-', '•', '*', '→', '●', '|']):
                formatted_lines.append(line)
            elif re.match(r'^[A-Z][a-z]+(\s[A-Z][a-z]+)*$', line):
                formatted_lines.append(f"👤 {line}")
            elif re.match(r'^\d+$', line):
                formatted_lines.append(f"🎂 Age: {line}")
            elif 'father' in line.lower() or 'mother' in line.lower() or 'wife' in line.lower() or 'husband' in line.lower():
                formatted_lines.append(f"👨‍👩‍👧‍👦 {line}")
        
        return '\n'.join(formatted_lines) if formatted_lines else content
    
    @staticmethod
    def _format_phone_info(content: str) -> str:
        """Format phone information"""
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Add emojis based on content
            if any(keyword in line.lower() for keyword in ['name:', 'full name:', 'person:']):
                formatted_lines.append(f"👤 {line}")
            elif any(keyword in line.lower() for keyword in ['phone:', 'mobile:', 'number:']):
                formatted_lines.append(f"📱 {line}")
            elif any(keyword in line.lower() for keyword in ['address:', 'location:', 'city:', 'state:']):
                formatted_lines.append(f"🏠 {line}")
            elif any(keyword in line.lower() for keyword in ['email:', 'mail:']):
                formatted_lines.append(f"📧 {line}")
            elif any(keyword in line.lower() for keyword in ['father:', 'mother:', 'spouse:']):
                formatted_lines.append(f"👨‍👩‍👧‍👦 {line}")
            elif any(keyword in line.lower() for keyword in ['carrier:', 'operator:', 'sim:']):
                formatted_lines.append(f"📶 {line}")
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
    
    @staticmethod
    def _format_aadhar_info(content: str) -> str:
        """Format Aadhar information"""
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(keyword in line.lower() for keyword in ['name:', 'full name:']):
                formatted_lines.append(f"👤 {line}")
            elif any(keyword in line.lower() for keyword in ['aadhar:', 'number:']):
                formatted_lines.append(f"🆔 {line}")
            elif any(keyword in line.lower() for keyword in ['address:', 'location:']):
                formatted_lines.append(f"🏠 {line}")
            elif any(keyword in line.lower() for keyword in ['dob:', 'birth:', 'age:']):
                formatted_lines.append(f"🎂 {line}")
            elif any(keyword in line.lower() for keyword in ['gender:', 'sex:']):
                formatted_lines.append(f"⚧️ {line}")
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
    
    @staticmethod
    def _format_vehicle_info(content: str) -> str:
        """Format vehicle information"""
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if any(keyword in line.lower() for keyword in ['owner:', 'name:', 'person:']):
                formatted_lines.append(f"👤 {line}")
            elif any(keyword in line.lower() for keyword in ['vehicle:', 'number:', 'reg:']):
                formatted_lines.append(f"🚗 {line}")
            elif any(keyword in line.lower() for keyword in ['model:', 'make:', 'brand:']):
                formatted_lines.append(f"🏭 {line}")
            elif any(keyword in line.lower() for keyword in ['year:', 'manufacture:']):
                formatted_lines.append(f"📅 {line}")
            elif any(keyword in line.lower() for keyword in ['color:', 'paint:']):
                formatted_lines.append(f"🎨 {line}")
            elif any(keyword in line.lower() for keyword in ['engine:', 'cc:', 'fuel:']):
                formatted_lines.append(f"⚙️ {line}")
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)

# ================== SEARCH ENGINE ==================

class SearchEngine:
    def __init__(self, db: DatabaseManager, user_manager):
        self.db = db
        self.user_manager = user_manager
        self.searches_col = db.get_collection('searches')
        self.failed_searches_col = db.get_collection('failed_searches')
        
        # Track pending searches: {search_id: {future, user_id, query, search_type, group, start_time}}
        self.pending_searches = {}
        
        # Track last message IDs per chat to detect new replies
        self.last_message_ids = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search across groups"""
        if search_type not in SEARCH_COMMANDS:
            return {"success": False, "error": "❌ Invalid search type"}
        
        command_info = SEARCH_COMMANDS[search_type]
        
        # Log search start
        logger.info(f"🔍 Starting {search_type} search for {query} (User: {user_id})")
        
        # Try groups in priority order
        groups = sorted(DESTINATION_GROUPS, key=lambda x: x["priority"])
        
        for group in groups:
            if not group.get("entity"):
                logger.warning(f"Group {group['name']} not resolved, skipping")
                continue
            
            # Get appropriate command for this group
            cmd = group["commands"].get(search_type)
            if not cmd:
                cmd = command_info["commands"][0] if command_info["commands"] else ""
            
            message = f"{cmd} {query}".strip()
            
            logger.info(f"📤 Trying {group['name']}: {message}")
            
            try:
                # Send message to group
                sent_msg = await user_client.send_message(group["entity"], message)
                
                # Create search tracking
                search_id = f"{group['identifier']}_{sent_msg.id}_{int(time.time())}"
                future = asyncio.get_running_loop().create_future()
                
                self.pending_searches[search_id] = {
                    "future": future,
                    "user_id": user_id,
                    "query": query,
                    "search_type": search_type,
                    "group": group,
                    "sent_msg_id": sent_msg.id,
                    "chat_entity": group["entity"],
                    "start_time": time.time(),
                    "waiting_for_file": False
                }
                
                # Store last message ID for this chat
                self.last_message_ids[group["entity"]] = sent_msg.id
                
                try:
                    # Wait for result with timeout
                    result = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if result["success"]:
                        logger.info(f"✅ Success from {group['name']}")
                        await self._log_search(user_id, search_type, query, True)
                        return result
                    else:
                        logger.info(f"⚠️ No valid result from {group['name']}, trying next...")
                        continue
                        
                except asyncio.TimeoutError:
                    logger.info(f"⏱️ Timeout from {group['name']}")
                    continue
                    
                except Exception as e:
                    logger.error(f"❌ Error waiting for result from {group['name']}: {e}")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Error sending to {group['name']}: {e}")
                continue
        
        # If all groups failed, notify admin
        await self._notify_admin_failed_search(user_id, search_type, query)
        
        await self._log_search(user_id, search_type, query, False)
        
        return {
            "success": False,
            "error": f"❌ No information found for `{query}`\n\n🔍 **Don't worry!** Your query has been sent to our admin team for manual review.\n\n📋 **What happens next?**\n• Our team will search from premium sources\n• You'll receive results within 24 hours\n• Check back later for updates\n\n💎 **Premium users get priority review!**"
        }
    
    async def handle_group_message(self, event):
        """Handle incoming messages in groups"""
        try:
            message = event.message
            chat = await event.get_chat()
            
            # Check if this is a reply to one of our sent messages
            if not message.reply_to:
                return
            
            # Find matching pending search
            matched_search = None
            matched_id = None
            
            for search_id, search_info in list(self.pending_searches.items()):
                if (search_info["chat_entity"] == chat and 
                    message.reply_to.reply_to_msg_id == search_info["sent_msg_id"]):
                    matched_search = search_info
                    matched_id = search_id
                    break
            
            if not matched_search:
                return
            
            # Wait a bit for complete response
            await asyncio.sleep(config.FETCH_WAIT_TIME)
            
            # Check if this is a processing message
            text = message.text or message.raw_text or ""
            
            if TextProcessor.is_processing_message(text):
                logger.info(f"⏳ Processing message detected in {search_info['group']['name']}, waiting...")
                # Don't complete future yet, wait for actual result
                return
            
            # Check for files
            if message.file:
                logger.info(f"📁 File received in {search_info['group']['name']}")
                result = await self._process_file_message(message, matched_search)
            elif text:
                logger.info(f"📝 Text response in {search_info['group']['name']}")
                result = await self._process_text_message(text, matched_search)
            else:
                return
            
            # Complete the future if we have a valid result
            if matched_id in self.pending_searches:
                future = self.pending_searches[matched_id]["future"]
                if not future.done():
                    future.set_result(result)
                self.pending_searches.pop(matched_id, None)
                
        except Exception as e:
            logger.error(f"Error handling group message: {e}")
    
    async def _process_file_message(self, message, search_info) -> Dict:
        """Process file message (txt, json, etc.)"""
        try:
            file_name = (message.file.name or "").lower()
            
            # Check if it's a processable file
            is_text_file = file_name.endswith(('.txt', '.json', '.csv'))
            is_document = isinstance(message.file, MessageMediaDocument)
            
            if not (is_text_file or is_document):
                logger.info("📁 Non-text file, ignoring")
                return {"success": False}
            
            # Download file
            file_bytes = await message.download_media(bytes)
            
            if not file_bytes:
                return {"success": False}
            
            # Try different encodings
            content = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    content = file_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file")
                return {"success": False}
            
            # Check if content is meaningful
            if len(content.strip()) < 20:
                logger.warning("⚠️ File content too short")
                return {"success": False}
            
            # Process the content
            processed_content = TextProcessor.process_file_content(
                content, search_info["search_type"]
            )
            
            if not processed_content or len(processed_content.strip()) < 20:
                logger.warning("⚠️ Processed content too short")
                return {"success": False}
            
            # Format the result
            formatted_result = self._format_result(
                processed_content, 
                search_info["search_type"],
                search_info["query"],
                search_info["group"]["name"]
            )
            
            logger.info(f"✅ Valid file content from {search_info['group']['name']}")
            return {
                "success": True,
                "result": formatted_result,
                "source": search_info["group"]["name"],
                "has_file": True
            }
            
        except Exception as e:
            logger.error(f"Error processing file: {e}")
            return {"success": False}
    
    async def _process_text_message(self, text: str, search_info) -> Dict:
        """Process text message response"""
        # Check if it's a no-info message
        if TextProcessor.is_no_info_message(text):
            logger.info(f"🚫 No-info message from {search_info['group']['name']}")
            return {"success": False}
        
        # Check if it's an error message
        if TextProcessor.is_error_message(text):
            logger.info(f"⚠️ Error message from {search_info['group']['name']}")
            return {"success": False}
        
        # Check if it's meaningful content
        cleaned_text = TextProcessor.extract_file_content(text)
        
        if len(cleaned_text.strip()) < 20:
            logger.warning(f"⚠️ Text too short from {search_info['group']['name']}")
            return {"success": False}
        
        # Process the content
        processed_content = TextProcessor.process_file_content(
            cleaned_text, search_info["search_type"]
        )
        
        # Format the result
        formatted_result = self._format_result(
            processed_content,
            search_info["search_type"],
            search_info["query"],
            search_info["group"]["name"]
        )
        
        logger.info(f"✅ Valid text result from {search_info['group']['name']}")
        return {
            "success": True,
            "result": formatted_result,
            "source": search_info["group"]["name"],
            "has_file": False
        }
    
    def _format_result(self, content: str, search_type: str, query: str, source: str) -> str:
        """Format search result with nice presentation"""
        command_info = SEARCH_COMMANDS.get(search_type, {})
        emoji = command_info.get("emoji", "✅")
        search_name = command_info.get("name", "Search Result")
        
        header = f"{emoji} **{search_name}**\n"
        header += f"🔍 Query: `{query}`\n"
        header += f"📊 Source: {source}\n"
        header += "─" * 35 + "\n\n"
        
        footer = "\n" + "─" * 35 + "\n"
        footer += "💎 **Premium Info Bot**\n"
        footer += "⚡ Fast & Accurate Results\n"
        footer += "🔗 @darkboxesAdmin for support"
        
        return header + content + footer
    
    async def _notify_admin_failed_search(self, user_id: int, search_type: str, query: str):
        """Notify admin about failed search for manual review"""
        try:
            # Save to failed searches collection
            failed_doc = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reviewed": False,
                "admin_replied": False
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, self.failed_searches_col.insert_one, failed_doc
            )
            
            # Notify admin
            user_info = await user_manager.get_user(user_id)
            username = user_info.get('username', 'N/A') if user_info else 'N/A'
            first_name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
            
            admin_msg = (
                f"🚨 **Failed Search - Manual Review Needed**\n\n"
                f"👤 User: {first_name} (@{username})\n"
                f"🆔 User ID: `{user_id}`\n"
                f"🔍 Type: {SEARCH_COMMANDS.get(search_type, {}).get('name', search_type)}\n"
                f"📝 Query: `{query}`\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"💡 **Admin Commands:**\n"
                f"• `/reply {user_id} [message]` - Send result to user\n"
                f"• `/skip {user_id}` - Mark as reviewed without reply\n"
                f"• `/review` - View all pending reviews"
            )
            
            await bot_client.send_message(
                config.ADMIN_USER_ID,
                admin_msg,
                parse_mode="md"
            )
            
            logger.info(f"📋 Notified admin about failed search: {search_type}={query}")
            
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")
    
    async def _log_search(self, user_id: int, search_type: str, query: str, success: bool):
        """Log search to database"""
        try:
            doc = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query[:100],
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await asyncio.get_running_loop().run_in_executor(
                None, self.searches_col.insert_one, doc
            )
        except Exception as e:
            logger.error(f"Error logging search: {e}")

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
        for _ in range(10):
            code = secrets.token_urlsafe(6).upper()
            existing = await asyncio.get_running_loop().run_in_executor(
                None, self.users_col.find_one, {"referral_code": code}
            )
            if not existing:
                return code
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

# ================== ADMIN PANEL ==================

class AdminPanel:
    def __init__(self, db: DatabaseManager, user_manager: UserManager, search_engine: SearchEngine):
        self.db = db
        self.user_manager = user_manager
        self.search_engine = search_engine
        self.users_col = db.get_collection('users')
        self.searches_col = db.get_collection('searches')
        self.failed_searches_col = db.get_collection('failed_searches')
    
    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id == config.ADMIN_USER_ID
    
    async def get_pending_reviews(self) -> List[Dict]:
        """Get pending failed searches for review"""
        try:
            cursor = self.failed_searches_col.find({"reviewed": False}).sort("timestamp", -1).limit(50)
            return await asyncio.get_running_loop().run_in_executor(None, list, cursor)
        except Exception as e:
            logger.error(f"Error getting pending reviews: {e}")
            return []
    
    async def send_reply_to_user(self, user_id: int, message: str) -> bool:
        """Send admin reply to user"""
        try:
            await bot_client.send_message(
                user_id,
                f"💎 **Admin Reply**\n\n{message}\n\n🔗 @darkboxesAdmin",
                parse_mode="md"
            )
            
            # Mark as replied
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.failed_searches_col.update_one(
                    {"user_id": user_id, "reviewed": False},
                    {"$set": {"reviewed": True, "admin_replied": True, "replied_at": datetime.now(timezone.utc).isoformat()}}
                )
            )
            
            logger.info(f"✅ Admin replied to user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending reply to user: {e}")
            return False
    
    async def mark_as_reviewed(self, user_id: int) -> bool:
        """Mark failed search as reviewed without reply"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.failed_searches_col.update_one(
                    {"user_id": user_id, "reviewed": False},
                    {"$set": {"reviewed": True, "admin_replied": False}}
                )
            )
            logger.info(f"✅ Marked user {user_id} search as reviewed")
            return True
        except Exception as e:
            logger.error(f"Error marking as reviewed: {e}")
            return False

# ================== KEYBOARD BUILDERS ==================

class KeyboardBuilder:
    @staticmethod
    def main_menu(user_role: str = "user") -> List[List[Button]]:
        """Build main menu keyboard"""
        buttons = []
        
        # Create 4 columns for better layout
        current_row = []
        for idx, (key, cmd) in enumerate(SEARCH_COMMANDS.items()):
            emoji = cmd.get("emoji", "🔍")
            current_row.append(Button.inline(f"{emoji} {cmd['name'].split(' ')[0]}", f"search_{key}"))
            
            if len(current_row) == 3 or idx == len(SEARCH_COMMANDS.items()) - 1:
                buttons.append(current_row)
                current_row = []
        
        # User options
        buttons.extend([
            [Button.inline("👤 Profile", "profile"), Button.inline("🎁 Referrals", "referrals")],
            [Button.inline("💎 Premium", "plans"), Button.inline("🆘 Support", "support")]
        ])
        
        # Admin options
        if user_role == "admin":
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def search_types_menu() -> List[List[Button]]:
        """Build search types menu with better layout"""
        buttons = []
        
        # Group by category
        categories = {
            "Phone & Identity": ["phone", "family", "aadhar", "telegram", "telegram_username"],
            "Vehicle & Finance": ["vehicle", "upi", "fampay", "gst"],
            "Digital & Others": ["email", "imei", "insta", "pak", "movies"]
        }
        
        for category, types in categories.items():
            row = []
            for stype in types:
                if stype in SEARCH_COMMANDS:
                    cmd = SEARCH_COMMANDS[stype]
                    emoji = cmd.get("emoji", "🔍")
                    row.append(Button.inline(f"{emoji} {cmd['name'].split(' ')[0]}", f"search_{stype}"))
            
            if row:
                buttons.append([Button.inline(f"📂 {category}", "noop")])
                # Split into max 3 per row
                for i in range(0, len(row), 3):
                    buttons.append(row[i:i+3])
        
        buttons.append([Button.inline("🔙 Back to Main", "main_menu")])
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]

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
admin_panel = None

# State tracking
user_states = {}

# ================== MESSAGE HANDLER ==================

@user_client.on(events.NewMessage())
async def handle_group_message(event):
    """Handle all group messages for search responses"""
    try:
        # Only handle messages in groups/channels
        chat = await event.get_chat()
        if chat.megagroup or chat.broadcast or chat.gigagroup:
            await search_engine.handle_group_message(event)
    except Exception as e:
        logger.error(f"Error in group message handler: {e}")

# ================== BOT EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start( (.+))?'))
async def start_handler(event):
    """Handle /start command"""
    try:
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
        
        if user_doc.get("banned"):
            await event.respond("🚫 Your account has been suspended.", parse_mode="md")
            return
        
        # Check if admin
        if await admin_panel.is_admin(user_id):
            await event.respond(
                "👑 **Admin Dashboard**\n\nWelcome back, Admin!\nUse /review to see pending requests.",
                buttons=KeyboardBuilder.main_menu("admin"),
                parse_mode="md"
            )
            return
        
        # Welcome message
        welcome_msg = (
            f"👋 **Welcome {user.first_name}!**\n\n"
            f"💎 **Premium Information Bot**\n"
            f"⚡ Fast & Accurate Results\n\n"
            f"📊 **Your Account:**\n"
            f"• Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"• Total Searches: {user_doc.get('total_searches', 0)}\n\n"
            f"🔍 **Select a search type below:**"
        )
        
        await event.respond(welcome_msg, buttons=KeyboardBuilder.main_menu(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in start_handler: {e}")
        await event.respond("❌ An error occurred. Please try again.")

@bot_client.on(events.NewMessage(pattern=r'/review'))
async def review_handler(event):
    """Handle admin review command"""
    try:
        user_id = event.sender_id
        
        if not await admin_panel.is_admin(user_id):
            await event.respond("❌ Unauthorized.", parse_mode="md")
            return
        
        pending = await admin_panel.get_pending_reviews()
        
        if not pending:
            await event.respond("✅ No pending reviews.", parse_mode="md")
            return
        
        message = "📋 **Pending Reviews**\n\n"
        for idx, review in enumerate(pending[:10], 1):
            user_info = await user_manager.get_user(review['user_id'])
            username = user_info.get('username', 'N/A') if user_info else 'N/A'
            first_name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
            
            message += (
                f"{idx}. **User:** {first_name} (@{username})\n"
                f"   **ID:** `{review['user_id']}`\n"
                f"   **Type:** {SEARCH_COMMANDS.get(review['search_type'], {}).get('name', review['search_type'])}\n"
                f"   **Query:** `{review['query']}`\n"
                f"   **Time:** {review['timestamp'][:16].replace('T', ' ')}\n\n"
            )
        
        message += "\n💡 **Commands:**\n`/reply [user_id] [message]`\n`/skip [user_id]`"
        
        await event.respond(message, parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in review_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)', forwards=False))
async def reply_handler(event):
    """Handle admin reply command"""
    try:
        user_id = event.sender_id
        
        if not await admin_panel.is_admin(user_id):
            await event.respond("❌ Unauthorized.", parse_mode="md")
            return
        
        target_user_id = int(event.pattern_match.group(1))
        reply_message = event.pattern_match.group(2)
        
        success = await admin_panel.send_reply_to_user(target_user_id, reply_message)
        
        if success:
            await event.respond(f"✅ Reply sent to user {target_user_id}")
        else:
            await event.respond(f"❌ Failed to send reply to user {target_user_id}")
            
    except Exception as e:
        logger.error(f"Error in reply_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/skip (\d+)', forwards=False))
async def skip_handler(event):
    """Handle admin skip command"""
    try:
        user_id = event.sender_id
        
        if not await admin_panel.is_admin(user_id):
            await event.respond("❌ Unauthorized.", parse_mode="md")
            return
        
        target_user_id = int(event.pattern_match.group(1))
        
        success = await admin_panel.mark_as_reviewed(target_user_id)
        
        if success:
            await event.respond(f"✅ Marked user {target_user_id} as reviewed")
        else:
            await event.respond(f"❌ Failed to mark user {target_user_id}")
            
    except Exception as e:
        logger.error(f"Error in skip_handler: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)'))
async def search_callback(event):
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid search type", alert=True)
            return
        
        user_doc = await user_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        if user_doc.get("banned"):
            await event.answer("❌ Account suspended", alert=True)
            return
        
        # Check credits
        if not await admin_panel.is_admin(user_id):
            credits = user_doc.get('searches_remaining', 0)
            if credits <= 0:
                await event.edit(
                    "❌ **No Credits Remaining**\n\n"
                    "You've used all your free credits.\n"
                    "Contact @darkboxesAdmin for more credits.",
                    buttons=KeyboardBuilder.cancel_button(),
                    parse_mode="md"
                )
                return
        
        # Set user state for input
        command_info = SEARCH_COMMANDS[search_type]
        user_states[user_id] = {"action": "awaiting_input", "type": search_type}
        
        await event.edit(
            f"{command_info.get('emoji', '🔍')} **{command_info['name']}**\n\n"
            f"📝 {command_info['description']}\n\n"
            f"📤 Example: `{command_info['example']}`\n\n"
            f"💡 **Please send your query below:**",
            buttons=KeyboardBuilder.cancel_button(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"Error in search_callback: {e}")
        await event.answer("❌ An error occurred", alert=True)

@bot_client.on(events.CallbackQuery(pattern='^(main_menu|profile|referrals|plans|support|admin_panel|cancel)$'))
async def menu_callback(event):
    """Handle menu callbacks"""
    try:
        action = event.data.decode()
        user_id = event.sender_id
        
        # Clear user state
        user_states.pop(user_id, None)
        
        user_doc = await user_manager.get_user(user_id)
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        user_role = "admin" if await admin_panel.is_admin(user_id) else "user"
        
        if action == "main_menu" or action == "cancel":
            welcome_msg = (
                f"🏠 **Main Menu**\n\n"
                f"📊 **Your Stats:**\n"
                f"• Credits: {user_doc.get('searches_remaining', 0)}\n"
                f"• Total Searches: {user_doc.get('total_searches', 0)}\n\n"
                f"🔍 **Select a search type:**"
            )
            await event.edit(welcome_msg, buttons=KeyboardBuilder.main_menu(user_role), parse_mode="md")
        
        elif action == "profile":
            join_date = user_doc.get('joined_at', '')[:10] if user_doc.get('joined_at') else 'N/A'
            await event.edit(
                f"👤 **Your Profile**\n\n"
                f"🆔 ID: `{user_id}`\n"
                f"👤 Name: {user_doc.get('first_name', 'N/A')}\n"
                f"📅 Joined: {join_date}\n"
                f"💎 Credits: {user_doc.get('searches_remaining', 0)}\n"
                f"🔍 Total Searches: {user_doc.get('total_searches', 0)}\n"
                f"🔗 Referral Code: `{user_doc.get('referral_code', 'N/A')}`",
                buttons=[[Button.inline("🔙 Back", "main_menu")]],
                parse_mode="md"
            )
        
        elif action == "admin_panel":
            await event.edit(
                "⚙️ **Admin Panel**\n\n"
                "Commands:\n"
                "• `/review` - View pending requests\n"
                "• `/reply [id] [msg]` - Reply to user\n"
                "• `/skip [id]` - Mark as reviewed\n\n"
                "Use buttons below:",
                buttons=[
                    [Button.inline("📋 Pending Reviews", "admin_reviews")],
                    [Button.inline("🔙 Back", "main_menu")]
                ],
                parse_mode="md"
            )
        
    except Exception as e:
        logger.error(f"Error in menu_callback: {e}")

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def private_message_handler(event):
    """Handle private messages for search queries"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        if state.get('action') != 'awaiting_input':
            return
        
        search_type = state['type']
        query = event.text.strip()
        
        if not query:
            await event.respond("❌ Please enter a valid query.")
            return
        
        # Show searching message
        status_msg = await event.respond(
            f"🔍 **Searching...**\n\n"
            f"⏳ Please wait while we search our premium databases.\n"
            f"💡 Searching: `{query}`\n\n"
            f"⚡ This may take 15-30 seconds...",
            parse_mode="md"
        )
        
        # Perform search
        result = await search_engine.perform_search(search_type, query, user_id)
        
        # Delete status message
        try:
            await status_msg.delete()
        except:
            pass
        
        if result.get("success"):
            await event.respond(result["result"], parse_mode="md")
            
            # Deduct credit if not admin
            if not await admin_panel.is_admin(user_id):
                await user_manager.update_searches(user_id, -1)
        
        else:
            await event.respond(result.get("error", "❌ Search failed"), parse_mode="md")
        
        # Clear user state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"Error in private_message_handler: {e}")
        await event.respond("❌ An error occurred during search.")

# ================== WEB SERVER ==================

async def start_web_server():
    """Start web server for health checks"""
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    async def bot_stats(request):
        return web.json_response({
            "status": "running",
            "service": "Premium Info Bot",
            "uptime": int(time.time() - start_time)
        })
    
    app.router.add_get("/", bot_stats)
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server started on port {config.PORT}")
    except Exception as e:
        logger.error(f"❌ Failed to start web server: {e}")

# ================== CLEANUP TASKS ==================

async def cleanup_expired_searches():
    """Clean up expired pending searches"""
    while True:
        try:
            await asyncio.sleep(60)
            
            current_time = time.time()
            expired = []
            
            for search_id, search_info in list(search_engine.pending_searches.items()):
                if current_time - search_info.get('start_time', current_time) > 300:
                    expired.append(search_id)
            
            for search_id in expired:
                search_info = search_engine.pending_searches.pop(search_id, None)
                if search_info and not search_info['future'].done():
                    try:
                        search_info['future'].set_exception(TimeoutError("Search expired"))
                    except:
                        pass
            
            if expired:
                logger.info(f"🧹 Cleaned up {len(expired)} expired searches")
                
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

# ================== INITIALIZATION ==================

start_time = time.time()

async def initialize_clients():
    """Initialize Telegram clients"""
    global user_manager, search_engine, admin_panel
    
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
        admin_panel = AdminPanel(db_manager, user_manager, search_engine)
        
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
        
        logger.info("✅ All systems initialized")
        return True
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        return False

# ================== MAIN FUNCTION ==================

async def main():
    """Main bot execution function"""
    try:
        logger.info("🚀 Starting Premium Info Bot...")
        
        # Initialize everything
        if not await initialize_clients():
            logger.error("❌ Failed to initialize. Exiting...")
            return
        
        # Start background tasks
        logger.info("🔧 Starting background tasks...")
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        
        # Log successful startup
        logger.info("=" * 60)
        logger.info("🎉 BOT SUCCESSFULLY STARTED!")
        logger.info("=" * 60)
        
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
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        
        asyncio.run(main())
    except Exception as e:
        logger.exception(f"Failed to start bot: {e}")
