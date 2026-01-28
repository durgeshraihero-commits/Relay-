"""
DarkBoxes Intelligence System - Premium Edition with API Support
Advanced information retrieval with premium interface
Professional Admin Panel and API Management
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
import traceback
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from collections import Counter, defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO

# Third-party imports
try:
    from aiohttp import web
    from telethon import TelegramClient, events, Button
    from telethon.tl.types import PeerChannel, PeerUser, Channel, User, MessageMediaDocument
    from telethon.tl.functions.channels import GetParticipantRequest
    from pymongo import MongoClient
    import pandas as pd
    from bson import ObjectId
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install telethon aiohttp pymongo pandas matplotlib")
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
    USER_API_HASH: str = os.getenv("API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    
    # Admin and mandatory channel
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
    MANDATORY_CHANNEL: str = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")
    
    # Database
    MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DBNAME: str = "darkboxes_db"
    
    # Timeouts and limits
    GROUP_TIMEOUT: int = int(os.getenv("GROUP_TIMEOUT", "45"))
    FETCH_WAIT_TIME: int = int(os.getenv("FETCH_WAIT_TIME", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
    
    # Credits and rewards
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "1"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "1"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "durgeshraihero@oksbi")
    ADMIN_CONTACT: str = "@darkboxesAdmin"
    
    # API Configuration
    API_ENABLED: bool = bool(os.getenv("API_ENABLED", "True"))
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_RATE_LIMIT: int = int(os.getenv("API_RATE_LIMIT", "100"))
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", secrets.token_hex(32))
    API_BASE_URL: str = os.getenv("API_BASE_URL", "")

config = BotConfig()

# ================== LOGGING SETUP ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("darkboxes.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("DarkBoxes")

# ================== VALIDATION ==================

def validate_config() -> bool:
    """Validate all required configuration"""
    errors = []
    
    required_configs = [
        ("BOT_API_ID", config.BOT_API_ID, lambda x: x != 0),
        ("BOT_API_HASH", config.BOT_API_HASH, lambda x: len(x) > 0),
        ("BOT_TOKEN", config.BOT_TOKEN, lambda x: len(x) > 0),
        ("ADMIN_USER_ID", config.ADMIN_USER_ID, lambda x: x != 0),
        ("MONGODB_URI", config.MONGODB_URI, lambda x: len(x) > 0),
    ]
    
    for name, value, validator in required_configs:
        if not validator(value):
            errors.append(f"{name} is not properly configured")
    
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  {error}")
        return False
    
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = config.USER_API_ID != 0 and config.USER_API_HASH and config.USER_PHONE

# ================== GROUP PRIORITY MANAGEMENT ==================

GROUP_PRIORITIES = {
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003596998816,  # Channel ID from your logs
        "timeout": 30,
        "weight": 10,
        "enabled": True,
        "entity": None
    },
    "secondary": {
        "name": "🌐 IntelX Network",
        "identifier": -1003428991184,  # Channel ID from your logs
        "timeout": 35,
        "weight": 7,
        "enabled": True,
        "entity": None
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": -1002314164449,  # Channel ID from your logs
        "timeout": 40,
        "weight": 5,
        "enabled": True,
        "entity": None
    },
    "advanced": {
        "name": "🚀 Advanced OSINT Engine",
        "identifier": -1002904387824,  # Channel ID from your logs
        "timeout": 25,
        "weight": 15,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak"
    }
}

# Sort groups by weight (priority)
DESTINATION_GROUPS = sorted(
    [group for group in GROUP_PRIORITIES.values() if group["enabled"]],
    key=lambda x: x["weight"],
    reverse=True
)

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • Aadhar ID • Complete address • Alternate numbers\n🔸 **Sources:** Government databases • Telecom records • Public directories\n🔸 **Confidence:** 98% accurate",
        "commands": ["/num"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1,
        "priority": "primary",
        "icon": "📱",
        "category": "identity"
    },
    "leak": {
        "name": "🚀 ADVANCED OSINT TOOL",
        "description": "🔮 **SEARCH ANYTHING - MOST POWERFUL TOOL**\n\n🔸 **Universal Search:** Email • Phone (with country code) • Name • Document • Username • Any query\n🔸 **Format:** Phone must include country code (e.g., 917204764637)\n🔸 **Returns:** Comprehensive results in JSON + TXT format\n🔸 **Speed:** Ultra-fast 5-second response\n🔸 **Sources:** Deep web • Breach databases • Global intelligence\n🔸 **Cost:** 3 credits per search",
        "commands": ["/leak"],
        "example": "917204764637 or email@domain.com or John Doe",
        "validation": r"^.+$",  # Accepts any input
        "cost": 3,
        "priority": "advanced",
        "icon": "🚀",
        "category": "advanced",
        "group": "advanced"
    }
}

# ================== TEXT PROCESSOR ==================

class TextProcessor:
    @staticmethod
    def is_processing_message(text: str) -> bool:
        """Check if message indicates processing"""
        if not text:
            return True
        
        text_lower = text.lower()
        keywords = [
            'processing', 'please wait', 'fetching', 'loading', 'searching',
            'retrieving', 'hold on', 'wait a moment', 'in progress',
            'gathering data', 'working on it', 'searching for',
            'please wait while', 'getting information', 'fetching data',
            'generating', 'creating report', 'file generated'
        ]
        
        return any(keyword in text_lower for keyword in keywords)
    
    @staticmethod
    def is_file_generated_message(text: str) -> bool:
        """Check if message indicates file generation"""
        if not text:
            return False
        
        text_lower = text.lower()
        keywords = [
            'file generated', 'report generated', 'download file',
            'txt file', 'download txt', 'successfully generated',
            'file generated', 'report_', '.txt', 'auto-delete',
            'file ready', 'file is ready', 'report is ready'
        ]
        
        result = any(keyword in text_lower for keyword in keywords)
        if result:
            logger.info(f"📄 Detected file generation message: {text[:50]}...")
        return result
    
    @staticmethod
    def is_no_info_message(text: str) -> bool:
        """Check if message indicates no information found"""
        if not text:
            return False
        
        text_lower = text.lower()
        keywords = [
            'no info', 'no information', 'not found', 'no data', 'no result',
            'no record', 'invalid', 'doesn\'t exist', 'does not exist',
            'not available', 'no details', 'unable to find', 'could not find',
            'couldn\'t find', 'no match', 'not exist', 'no information found'
        ]
        
        return any(keyword in text_lower for keyword in keywords)
    
    @staticmethod
    def clean_content(content: str, search_type: str = None) -> str:
        """Clean and format content"""
        if not content:
            return ""
        
        # Remove promotional content and personal information
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
            r'admin.*@\w+',
            r'auto-delete.*',
            r'file generated.*',
            r'report_.*\.txt',
            r'download.*file',
            r'click.*download',
            r'designed & powered.*',
            r'join.*@\w+',
            r'channel.*@\w+',
            r'username.*:.*@\w+',
            r'telegram.*:.*@\w+',
            r'@\w+.*bot',
            r'bot.*@\w+'
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        # Clean whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        
        return content.strip()
    
    @staticmethod
    def split_long_text(text: str, max_length: int = 4000) -> List[str]:
        """Split long text into chunks"""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        while len(text) > max_length:
            # Try to split at paragraph
            split_pos = text.rfind('\n\n', 0, max_length)
            if split_pos == -1:
                split_pos = text.rfind('\n', 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        
        if text:
            chunks.append(text)
        
        return chunks

# ================== PREMIUM TEXT FORMATTER ==================

class PremiumFormatter:
    @staticmethod
    def format_result(content: str, search_type: str, query: str, source: str) -> str:
        """Format search result with premium styling"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        icon = cmd.get("icon", "✅")
        name = cmd.get("name", "Search Result")
        
        # Header
        result = f"{icon} **{name}**\n"
        result += f"🔍 **Query:** `{query}`\n"
        result += f"📊 **Source:** {source}\n"
        result += "─" * 40 + "\n\n"
        
        # Content
        if not content or len(content.strip()) < 30:
            content = "🚫 No valid information found in the response.\n\n🔒 **Premium Notice:** This query may require higher subscription level or manual processing.\nContact @darkboxesAdmin for premium assistance."
        
        result += content + "\n\n"
        
        # Footer
        result += "─" * 40 + "\n"
        result += "⚡ **Powered by DarkBoxes Intelligence System**\n"
        result += "🔐 **Developed by** @darkboxesAdmin\n"
        result += "⚠️ **Confidential** - Authorized use only\n"
        result += f"🕒 {datetime.now().strftime('%I:%M %p | %d %b %Y')}"
        
        return result
    
    @staticmethod
    def format_welcome(user_name: str, user_data: Dict) -> str:
        """Format welcome message"""
        welcome = "🎭 **DARK BOXES INTELLIGENCE SYSTEM** 🎭\n\n"
        welcome += "╔══════════════════════════════════╗\n"
        welcome += f"║   WELCOME, {user_name.upper()}   ║\n"
        welcome += "╚══════════════════════════════════╝\n\n"
        
        welcome += "📈 **ACCOUNT OVERVIEW**\n"
        welcome += "├─ Available Credits: " + ("∞" if user_data.get('subscription') else str(user_data.get('searches_remaining', 0))) + "\n"
        welcome += f"├─ Total Searches: {user_data.get('total_searches', 0)}\n"
        welcome += f"├─ Referral Code: `{user_data.get('referral_code', 'N/A')}`\n"
        welcome += f"└─ Active Referrals: {user_data.get('referrals', 0)}\n\n"
        
        welcome += "🌟 **PREMIUM FEATURES**\n"
        welcome += "• 🔓 OSINT Database\n"
        welcome += "• 👑 Celebrity Information Network\n"
        welcome += "• 🌐 International Data Sources\n"
        welcome += "• ⚡ Priority Processing\n"
        welcome += "• 🔐 Encrypted Communication\n"
        welcome += "• 📊 Real-time Intelligence\n\n"
        
        welcome += "🛠️ **SELECT SERVICE**"
        
        return welcome
    
    @staticmethod
    def format_processing(search_type: str, query: str) -> str:
        """Format processing message"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        
        processing = "🔮 **INTELLIGENCE SCAN INITIATED**\n\n"
        processing += "╔══════════════════════════════════╗\n"
        processing += f"║   {cmd.get('icon', '🔍')} {cmd.get('name', 'Search').upper()}   ║\n"
        processing += "╚══════════════════════════════════╝\n\n"
        
        processing += "📡 **ACCESSING DATABASES**\n"
        processing += "├─ Query: `" + query + "`\n"
        processing += "├─ Priority: Premium Processing\n"
        processing += "├─ Estimated Time: 15-30 seconds\n"
        processing += "└─ Sources: Multiple intelligence feeds\n\n"
        
        processing += "🔄 **PROCESSING STAGES**\n"
        processing += "1️⃣ Data aggregation\n"
        processing += "2️⃣ Cross-reference verification\n"
        processing += "3️⃣ Pattern analysis\n"
        processing += "4️⃣ Report generation\n\n"
        
        processing += "⏳ Please wait while we gather intelligence..."
        
        return processing

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            
            # Create indexes
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.create_index([("user_id", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.create_index([("timestamp", -1)])
            )
            
            logger.info("✅ MongoDB connected")
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return False
    
    async def create_user(self, user_id: int, username: str, first_name: str, referral_code: str = None) -> bool:
        """Create new user with referral tracking"""
        try:
            referral_info = {}
            if referral_code:
                referral_info = {
                    "referred_by": referral_code,
                    "referral_code": str(user_id)[-6:],
                    "referral_date": datetime.now(timezone.utc).isoformat()
                }
            
            user_doc = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "searches_remaining": config.NEW_USER_CREDITS,
                "total_searches": 0,
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "referral_code": str(user_id)[-6:],
                "referrals": 0,
                "referral_credits": 0,
                "subscription": None,
                "subscription_expiry": None,
                "is_banned": False
            }
            
            if referral_info:
                user_doc.update(referral_info)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": user_doc},
                    upsert=True
                )
            )
            
            logger.info(f"✅ Created user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating user: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user by ID"""
        try:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.db.users.find_one, {"user_id": user_id}
            )
        except Exception as e:
            logger.error(f"❌ Error getting user: {e}")
            return None
    
    async def update_searches(self, user_id: int, search_type: str, query: str, success: bool = True) -> bool:
        """Update user search count and log search"""
        try:
            user = await self.get_user(user_id)
            if not user:
                return False
            
            searches_remaining = user.get('searches_remaining', 0)
            if searches_remaining <= 0:
                return False
            
            credits_used = SEARCH_COMMANDS.get(search_type, {}).get("cost", 1)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {
                            "searches_remaining": -credits_used,
                            "total_searches": 1
                        },
                        "$set": {"last_seen": datetime.now(timezone.utc).isoformat()}
                    }
                )
            )
            
            # Log search
            search_log = {
                "user_id": user_id,
                "search_type": search_type,
                "query": query,
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "credits_used": credits_used
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.insert_one(search_log)
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating searches: {e}")
            return False

# ================== ONE COMMAND PER LINE KEYBOARD ==================

class OneLineKeyboard:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build keyboard with ONE COMMAND PER LINE"""
        buttons = []
        
        # Add each command in its own line
        commands_in_order = ["phone", "leak"]
        
        for cmd_key in commands_in_order:
            if cmd_key in SEARCH_COMMANDS:
                cmd = SEARCH_COMMANDS[cmd_key]
                # Special emphasis for leak command
                if cmd_key == "leak":
                    button_text = f"🚀 ADVANCED OSINT TOOL"
                else:
                    button_text = f"{cmd['icon']} {cmd['name'].split()[1]}"
                buttons.append([Button.inline(button_text, f"search_{cmd_key}")])
        
        # Add action buttons in their own lines
        buttons.append([Button.inline("👤 Profile", "profile")])
        buttons.append([Button.inline("📊 Refer & Earn", "referrals")])
        buttons.append([Button.inline("🆘 Support", "support")])
        
        # Add admin button if admin
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        buttons.append([Button.inline("🔄 Refresh Menu", "main_menu")])
        
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]
    
    @staticmethod
    def profile_menu() -> List[List[Button]]:
        """Profile menu buttons"""
        return [
            [Button.inline("🔄 Refresh", "profile")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def support_menu() -> List[List[Button]]:
        """Support menu buttons"""
        return [
            [Button.inline("📞 Contact Admin", "contact_admin")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def referrals_menu() -> List[List[Button]]:
        """Referrals menu buttons"""
        return [
            [Button.inline("📋 My Referrals", "my_referrals")],
            [Button.inline("📢 Share Referral", "share_referral")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def admin_panel() -> List[List[Button]]:
        """Professional admin panel"""
        buttons = [
            [Button.inline("📊 Today's Stats", "admin_today")],
            [Button.inline("👥 User Management", "admin_users")],
            [Button.inline("📈 Search Analytics", "admin_analytics")],
            [Button.inline("🚫 Ban/Unban User", "admin_ban")],
            [Button.inline("🎯 Add Credits", "admin_add_credits")],
            [Button.inline("📢 Broadcast", "admin_broadcast")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons

# ================== SEARCH ENGINE ==================

class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.waiting_for_files = {}
        self.group_performance = {}
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search with priority management"""
        logger.info(f"🚀 Starting {search_type} search: {query} (User: {user_id})")
        
        # Check for leak search
        if search_type == "leak":
            return await self.perform_leak_search(query, user_id)
        
        # Get command priority
        cmd = SEARCH_COMMANDS.get(search_type, {})
        preferred_priority = cmd.get("priority", "primary")
        
        # Sort groups based on command priority and performance
        sorted_groups = self._get_priority_groups(preferred_priority)
        
        for group in sorted_groups:
            if not group.get("entity"):
                logger.warning(f"⚠️ Group {group['name']} not resolved")
                continue
            
            # Get appropriate command for this group
            command_list = cmd["commands"]
            primary_command = command_list[0]
            
            logger.info(f"📤 Trying {group['name']}: {primary_command} {query}")
            
            try:
                # Send message to group
                sent_msg = await user_client.send_message(group["entity"], f"{primary_command} {query}")
                
                # Create search tracking
                search_id = f"{user_id}_{int(time.time())}_{group['name']}"
                future = asyncio.get_running_loop().create_future()
                
                self.active_searches[search_id] = {
                    "user_id": user_id,
                    "future": future,
                    "start_time": time.time(),
                    "group": group,
                    "message_id": sent_msg.id,
                    "search_type": search_type,
                    "query": query,
                    "chat_id": group["entity"].id,
                    "expecting_file": False,
                    "file_wait_start": None,
                    "priority": group["weight"]
                }
                
                # Wait for response
                try:
                    result = await asyncio.wait_for(future, timeout=group["timeout"])
                    
                    if result["success"]:
                        # Update group performance
                        self._update_group_performance(group["name"], True)
                        logger.info(f"✅ Success from {group['name']}")
                        return result
                    else:
                        self._update_group_performance(group["name"], False)
                        logger.info(f"⚠️ No result from {group['name']}, trying next...")
                        continue
                        
                except asyncio.TimeoutError:
                    self._update_group_performance(group["name"], False)
                    logger.info(f"⏱️ Timeout from {group['name']}")
                    continue
                    
            except Exception as e:
                logger.error(f"❌ Error sending to {group['name']}: {e}")
                self._update_group_performance(group["name"], False)
                continue
        
        # All groups failed
        await self._notify_admin(user_id, search_type, query)
        return {
            "success": False,
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\nContact @darkboxesAdmin for immediate assistance."
        }
    
    async def perform_leak_search(self, query: str, user_id: int) -> Dict:
        """Perform advanced leak search"""
        try:
            logger.info(f"🚀 ADVANCED LEAK SEARCH: {query} (User: {user_id})")
            
            # Get the advanced group
            advanced_group = GROUP_PRIORITIES["advanced"]
            if not advanced_group.get("entity"):
                logger.error("❌ Advanced group not resolved")
                return {
                    "success": False,
                    "error": "❌ Advanced search engine is currently unavailable."
                }
            
            # Send leak command
            leak_command = advanced_group.get("leak_command", "/leak")
            sent_msg = await user_client.send_message(advanced_group["entity"], f"{leak_command} {query}")
            
            # Create search tracking
            search_id = f"{user_id}_{int(time.time())}_leak"
            future = asyncio.get_running_loop().create_future()
            
            self.active_searches[search_id] = {
                "user_id": user_id,
                "future": future,
                "start_time": time.time(),
                "group": advanced_group,
                "message_id": sent_msg.id,
                "search_type": "leak",
                "query": query,
                "chat_id": advanced_group["entity"].id,
                "expecting_file": True,
                "file_wait_start": None,
                "priority": advanced_group["weight"],
                "expect_multiple_files": True,
                "files_received": [],
                "file_types": ["json", "txt"]
            }
            
            # Wait for response
            try:
                result = await asyncio.wait_for(future, timeout=10)
                
                if result["success"]:
                    logger.info(f"✅ Advanced leak search successful")
                    return result
                else:
                    logger.info(f"⚠️ No result from advanced search")
                    return {
                        "success": False,
                        "error": "❌ No information found in our advanced databases.\n\n⚠️ **Note:** For phone searches, include country code (e.g., 917204764637)"
                    }
                    
            except asyncio.TimeoutError:
                logger.info(f"⏱️ Timeout from advanced search")
                return {
                    "success": False,
                    "error": "⏱️ **ADVANCED SEARCH TIMEOUT**\n\nOur advanced engine is processing your query.\nResults will be delivered shortly if available."
                }
                
        except Exception as e:
            logger.error(f"❌ Error in leak search: {e}")
            return {
                "success": False,
                "error": "❌ Advanced search engine error."
            }
    
    def _get_priority_groups(self, preferred_priority: str) -> List:
        """Get groups sorted by priority and performance"""
        priority_order = ["primary", "secondary", "tertiary"]
        
        # Start with preferred priority group
        sorted_groups = []
        
        # Add preferred group first
        for group in DESTINATION_GROUPS:
            if group.get("name") == GROUP_PRIORITIES[preferred_priority]["name"]:
                sorted_groups.append(group)
                break
        
        # Add remaining groups by weight
        remaining_groups = [g for g in DESTINATION_GROUPS if g not in sorted_groups]
        remaining_groups.sort(key=lambda x: x["weight"], reverse=True)
        
        sorted_groups.extend(remaining_groups)
        return sorted_groups
    
    def _update_group_performance(self, group_name: str, success: bool):
        """Update group performance tracking"""
        if group_name not in self.group_performance:
            self.group_performance[group_name] = {"success": 0, "total": 0}
        
        self.group_performance[group_name]["total"] += 1
        if success:
            self.group_performance[group_name]["success"] += 1
    
    async def handle_incoming_message(self, event):
        """Handle incoming messages for search responses"""
        try:
            message = event.message
            
            # Check if this is a reply to our search
            if message.reply_to:
                reply_to_id = message.reply_to.reply_to_msg_id
                
                for search_id, search_info in list(self.active_searches.items()):
                    if reply_to_id == search_info["message_id"]:
                        await self._process_search_response(search_id, search_info, message)
                        return
            
            # Check for file messages in same chat
            for search_id, search_info in list(self.active_searches.items()):
                try:
                    if event.chat_id == search_info["chat_id"]:
                        file_check = await self._check_and_process_file(message, search_info)
                        if file_check is not None:
                            logger.info(f"📁 Found file in {search_info['group']['name']}")
                            await self._process_search_response(search_id, search_info, message)
                        return
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Error handling incoming message: {e}")

    async def _check_and_process_file(self, message, search_info: Dict) -> Optional[Dict]:
        """Check if message has file and process it"""
        try:
            # Check for media/document
            if message.media and hasattr(message.media, 'document'):
                logger.info(f"📁 Found document media")
                return await self._process_file(message, search_info)
            
            if hasattr(message, 'document') and message.document:
                logger.info(f"📁 Found document")
                return await self._process_file(message, search_info)
            
            # Check for long text that might be results
            text = message.text or message.raw_text or ""
            if text and len(text) > 1000:
                # Check for TXT file indicators
                txt_indicators = [
                    'Full results available as JSON file',
                    'Total length:',
                    'TRUNCATED - DATA TOO LONG',
                    '───────────────────────',
                    '━━━━━━━━━━━━━━━━━━━━━━━━',
                    'Service: leak',
                    'Requested by:'
                ]
                
                indicator_count = 0
                for indicator in txt_indicators:
                    if indicator in text:
                        indicator_count += 1
                
                if indicator_count >= 2:
                    logger.info(f"📄 Detected TXT file content in message")
                    cleaned_content = TextProcessor.clean_content(text, search_info["search_type"])
                    
                    result = {
                        "success": True,
                        "result": None,
                        "has_file": True,
                        "content": cleaned_content,
                        "raw_bytes": cleaned_content.encode('utf-8'),
                        "filename": f"leak_{search_info['query']}_{int(time.time())}.txt",
                        "is_text_based": True
                    }
                    
                    if search_info["search_type"] != "leak":
                        formatted_result = PremiumFormatter.format_result(
                            cleaned_content,
                            search_info["search_type"],
                            search_info["query"],
                            search_info["group"]["name"]
                        )
                        result["result"] = formatted_result
                    
                    logger.info(f"✅ Processed TXT content with {len(cleaned_content)} characters")
                    return result
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error checking for file: {e}")
            return None
    
    async def _process_search_response(self, search_id: str, search_info: Dict, message):
        """Process a search response message"""
        try:
            text = message.text or message.raw_text or ""
            logger.info(f"📨 Processing message in {search_info['group']['name']}: {text[:100]}...")
            
            # Special handling for leak search
            if search_info["search_type"] == "leak":
                return await self._process_leak_response(search_id, search_info, message)
            
            file_result = await self._check_and_process_file(message, search_info)
            if file_result is not None:
                logger.info(f"✅ Processing file from message")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(file_result)
                    del self.active_searches[search_id]
                return
            
            if TextProcessor.is_file_generated_message(text):
                logger.info(f"📄 File generation message detected")
                search_info["expecting_file"] = True
                search_info["file_wait_start"] = time.time()
                logger.info(f"⏳ Waiting for file to arrive...")
                return
            
            if TextProcessor.is_processing_message(text):
                logger.info(f"⏳ Processing message, waiting...")
                return
            
            if TextProcessor.is_no_info_message(text):
                logger.info(f"🚫 No-info message")
                result = {"success": False}
            elif text and len(text.strip()) > 10:
                logger.info(f"📝 Processing text response")
                result = await self._process_text(text, search_info)
            else:
                logger.info(f"⚠️ Empty or short message, ignoring")
                return
            
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(result)
                del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"❌ Error processing search response: {e}")
    
    async def _process_leak_response(self, search_id: str, search_info: Dict, message):
        """Process leak search response"""
        try:
            # Check for file
            file_result = await self._check_and_process_file(message, search_info)
            
            if file_result is not None:
                logger.info(f"📁 Processing leak search file")
                
                # Add file to received files
                if "files_received" not in search_info:
                    search_info["files_received"] = []
                
                # Determine file type
                filename = ""
                if hasattr(message.file, 'name') and message.file.name:
                    filename = message.file.name.lower()
                
                file_type = "unknown"
                if '.json' in filename:
                    file_type = "json"
                elif '.txt' in filename or '.text' in filename:
                    file_type = "txt"
                
                file_result["file_type"] = file_type
                search_info["files_received"].append(file_result)
                
                logger.info(f"✅ Added {file_type} file to leak search results")
                
                # Check if we have enough files
                if len(search_info["files_received"]) >= 2:
                    await self._complete_leak_search(search_id, search_info)
                return
            
            # Check for text message
            text = message.text or message.raw_text or ""
            
            if text and len(text) > 500:
                logger.info(f"📝 Processing text message for leak search")
                
                # Create a file result from the text
                txt_result = {
                    "success": True,
                    "has_file": True,
                    "content": text,
                    "raw_bytes": text.encode('utf-8'),
                    "file_type": "txt",
                    "filename": f"leak_{search_info['query']}_{int(time.time())}.txt",
                    "is_text_message": True
                }
                
                # Add to received files
                if "files_received" not in search_info:
                    search_info["files_received"] = []
                
                search_info["files_received"].append(txt_result)
                
                # Check if we have enough files
                if len(search_info["files_received"]) >= 2:
                    await self._complete_leak_search(search_id, search_info)
                return
            
        except Exception as e:
            logger.error(f"❌ Error processing leak response: {e}")
    
    async def _complete_leak_search(self, search_id: str, search_info: Dict):
        """Complete leak search and send results"""
        try:
            logger.info(f"✅ Completing leak search with {len(search_info.get('files_received', []))} files")
            
            if not search_info.get("files_received"):
                logger.warning("⚠️ No files received for leak search")
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result({"success": False})
                    del self.active_searches[search_id]
                return
            
            # Create summary
            combined_result = {
                "success": True,
                "result": "🚀 **ADVANCED OSINT SEARCH COMPLETE**\n\n",
                "files": search_info["files_received"],
                "has_multiple_files": len(search_info["files_received"]) > 1
            }
            
            # Format result summary
            summary = f"🔮 **ADVANCED UNIVERSAL SEARCH RESULT**\n"
            summary += f"═══════════════════════════════════\n\n"
            summary += f"🔍 **Query:** `{search_info['query']}`\n"
            summary += f"🚀 **Source:** Advanced OSINT Engine\n"
            summary += f"⚡ **Files Found:** {len(search_info['files_received'])}\n\n"
            
            if search_info["files_received"]:
                summary += f"📁 **Files available for download**\n"
            
            summary += f"⚡ **Powered by DarkBoxes Advanced Intelligence**\n"
            
            combined_result["result"] = summary
            
            if search_id in self.active_searches:
                future = self.active_searches[search_id]["future"]
                if not future.done():
                    future.set_result(combined_result)
                del self.active_searches[search_id]
                logger.info(f"✅ Leak search completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Error completing leak search: {e}")
    
    async def _process_file(self, message, search_info: Dict) -> Dict:
        """Process file message"""
        try:
            if hasattr(message.file, 'size') and message.file.size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                logger.warning(f"📁 File too large: {message.file.size} bytes")
                return {"success": False}
            
            logger.info(f"⬇️ Downloading file from {search_info['group']['name']}")
            file_bytes = await message.download_media(bytes)
            
            if not file_bytes:
                logger.error("❌ Failed to download file")
                return {"success": False}
            
            content = None
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    content = file_bytes.decode(encoding)
                    logger.info(f"✅ Decoded with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file")
                return {"success": False}
            
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 30:
                logger.warning(f"⚠️ Cleaned content too short")
                return {"success": False}
            
            result = {
                "success": True,
                "result": None,
                "has_file": True,
                "content": cleaned_content,
                "raw_bytes": file_bytes,
                "filename": message.file.name if hasattr(message.file, 'name') else f"result_{int(time.time())}.txt"
            }
            
            # Format result for non-leak searches
            if search_info["search_type"] != "leak":
                formatted_result = PremiumFormatter.format_result(
                    cleaned_content,
                    search_info["search_type"],
                    search_info["query"],
                    search_info["group"]["name"]
                )
                result["result"] = formatted_result
            
            logger.info(f"✅ Processed file with {len(cleaned_content)} characters")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing file: {e}")
            return {"success": False}
    
    async def _process_text(self, text: str, search_info: Dict) -> Dict:
        """Process text message"""
        cleaned = TextProcessor.clean_content(text, search_info["search_type"])
        
        if len(cleaned) < 20:
            return {"success": False}
        
        formatted = PremiumFormatter.format_result(
            cleaned,
            search_info["search_type"],
            search_info["query"],
            search_info["group"]["name"]
        )
        
        return {
            "success": True,
            "result": formatted,
            "has_file": False
        }
    
    async def _notify_admin(self, user_id: int, search_type: str, query: str):
        """Notify admin about failed search"""
        try:
            user_info = await self.db.get_user(user_id)
            username = user_info.get('username', 'N/A') if user_info else 'N/A'
            first_name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
            
            admin_msg = (
                f"🚨 **FAILED SEARCH ALERT**\n\n"
                f"👤 User: {first_name} (@{username})\n"
                f"🆔 ID: `{user_id}`\n"
                f"🔍 Type: {search_type}\n"
                f"📝 Query: `{query}`\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            await bot_client.send_message(config.ADMIN_USER_ID, admin_msg, parse_mode="md")
            logger.info(f"📋 Notified admin about {search_type}={query}")
            
        except Exception as e:
            logger.error(f"❌ Error notifying admin: {e}")

# ================== CLEANUP TASK ==================

async def cleanup_expired_searches():
    """Clean up expired searches"""
    while True:
        try:
            await asyncio.sleep(30)
            
            current_time = time.time()
            expired = []
            
            for search_id, search_info in list(search_engine.active_searches.items()):
                timeout = search_info["group"]["timeout"]
                
                if search_info.get("expecting_file") and search_info.get("file_wait_start"):
                    file_wait_time = current_time - search_info["file_wait_start"]
                    if file_wait_time < 20:
                        continue
                    else:
                        logger.info(f"⏱️ File wait timeout in {search_info['group']['name']}")
                
                if current_time - search_info["start_time"] > timeout:
                    expired.append(search_id)
            
            for search_id in expired:
                search_info = search_engine.active_searches.pop(search_id, None)
                if search_info:
                    future = search_info["future"]
                    if not future.done():
                        try:
                            future.set_result({"success": False})
                        except:
                            pass
                    logger.info(f"🧹 Cleaned expired search: {search_id}")
            
            if expired:
                logger.info(f"🧹 Cleaned {len(expired)} expired searches")
                
        except Exception as e:
            logger.error(f"❌ Error in cleanup: {e}")

# ================== WEB SERVER ==================

async def start_web_server():
    """Start simple web server for health checks"""
    app = web.Application()
    
    async def health_check(request):
        return web.json_response({"status": "ok", "timestamp": datetime.now().isoformat()})
    
    async def root_handler(request):
        return web.Response(text="DarkBoxes Intelligence System\n\nStatus: Operational")
    
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    
    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = '*'
        return response
    
    app.middlewares.append(cors_middleware)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    await site.start()
    logger.info(f"🌐 Web server running on port {port}")

# ================== GLOBAL VARIABLES ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

db_manager = DatabaseManager()
search_engine = None
user_states = {}
bot_info = None

# ================== EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Premium start handler"""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.respond("🚫 Your account has been banned. Contact @darkboxesAdmin for assistance.")
            return
        
        # Get or create user
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral_code)
            user_doc = await db_manager.get_user(user_id)
        
        is_admin = user_id == config.ADMIN_USER_ID
        
        # Send welcome message
        welcome_text = PremiumFormatter.format_welcome(user.first_name, user_doc)
        
        # Get keyboard
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.respond(
            welcome_text,
            buttons=buttons,
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in start_handler: {e}")

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    """Handle all callback queries"""
    try:
        data = event.data.decode()
        user_id = event.sender_id
        
        logger.info(f"🔘 Callback received: {data} from {user_id}")
        
        if data == "main_menu":
            user_doc = await db_manager.get_user(user_id)
            is_admin = user_id == config.ADMIN_USER_ID
            welcome_text = PremiumFormatter.format_welcome(event.sender.first_name, user_doc)
            await event.edit(welcome_text, buttons=OneLineKeyboard.main_menu(is_admin), parse_mode="md")
        
        elif data == "profile":
            await profile_callback(event)
        
        elif data == "referrals":
            await referrals_callback(event)
        
        elif data == "support":
            await support_callback(event)
        
        elif data.startswith("search_"):
            await search_callback(event)
        
        elif data.startswith("admin_"):
            await admin_callback(event)
        
        elif data == "contact_admin":
            await event.answer("📞 Contact @darkboxesAdmin for support", alert=True)
        
        elif data == "my_referrals":
            await event.answer("📋 Your referrals will be shown here", alert=True)
        
        elif data == "share_referral":
            user_doc = await db_manager.get_user(user_id)
            referral_link = f"https://t.me/{bot_info.username}?start={user_doc.get('referral_code')}"
            await event.answer(f"🔗 Share this link: {referral_link}", alert=True)
        
        else:
            await event.answer("❌ Unknown command", alert=True)
            
    except Exception as e:
        logger.error(f"❌ Error in callback_handler: {e}")
        await event.answer("❌ Error processing request", alert=True)

async def profile_callback(event):
    """Handle profile callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Format profile
        profile_text = (
            f"👤 **USER PROFILE**\n"
            f"═══════════════════════\n\n"
            f"📋 **Personal Information**\n"
            f"├─ Name: {user_doc.get('first_name', 'N/A')}\n"
            f"├─ Username: @{user_doc.get('username', 'N/A')}\n"
            f"├─ User ID: `{user_id}`\n"
            f"├─ Joined: {user_doc.get('joined_at', 'N/A')[:10]}\n"
            f"└─ Last Seen: {user_doc.get('last_seen', 'N/A')[:16]}\n\n"
        )
        
        # Credits and subscription
        profile_text += f"💰 **Account Status**\n"
        profile_text += f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
        profile_text += f"└─ Total Searches: {user_doc.get('total_searches', 0)}\n\n"
        
        # Referral
        profile_text += f"📊 **Referral Stats**\n"
        profile_text += f"├─ Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
        profile_text += f"├─ Referrals: {user_doc.get('referrals', 0)}\n"
        profile_text += f"└─ Referral Credits: {user_doc.get('referral_credits', 0)}\n"
        
        await event.edit(
            profile_text,
            buttons=OneLineKeyboard.profile_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in profile_callback: {e}")
        await event.answer("❌ Error loading profile", alert=True)

async def referrals_callback(event):
    """Handle referrals callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        referral_code = user_doc.get('referral_code', 'N/A')
        referrals_count = user_doc.get('referrals', 0)
        
        referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
        
        referrals_text = (
            f"📊 **REFER & EARN PROGRAM**\n"
            f"═══════════════════════\n\n"
            f"💰 **How It Works:**\n"
            f"1. Share your referral link below\n"
            f"2. When someone signs up using your link\n"
            f"3. You get **{config.REFERRAL_REWARD} credit** instantly!\n"
            f"4. They get **{config.NEW_USER_CREDITS} free credits**\n\n"
            f"📈 **Your Stats:**\n"
            f"├─ Referral Code: `{referral_code}`\n"
            f"├─ Total Referrals: {referrals_count}\n"
            f"└─ Active Status: ✅\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"{referral_link}"
        )
        
        await event.edit(
            referrals_text,
            buttons=OneLineKeyboard.referrals_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in referrals_callback: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

async def support_callback(event):
    """Handle support callback"""
    try:
        support_text = (
            f"🆘 **DARKBOXES SUPPORT**\n"
            f"═══════════════════════\n\n"
            f"📞 **Contact Admin:** @darkboxesAdmin\n"
            f"⏰ **Response Time:** Within 1 hour\n"
            f"🌐 **Official Channel:** @darkboxesv1\n\n"
            f"❓ **Common Issues:**\n"
            f"• Payment not processed\n"
            f"• Search not working\n"
            f"• Account issues\n"
            f"• Bug reports\n\n"
            f"⚠️ **Before Contacting:**\n"
            f"1. Check if you have sufficient credits\n"
            f"2. Verify your query format\n"
            f"3. Wait 30 seconds for search results\n\n"
            f"🔒 **Security Notice:**\n"
            f"Never share passwords or OTPs\n"
            f"Official admin: @darkboxesAdmin only"
        )
        
        await event.edit(
            support_text,
            buttons=OneLineKeyboard.support_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in support_callback: {e}")
        await event.answer("❌ Error loading support", alert=True)

async def search_callback(event):
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.answer("🚫 Your account has been banned.", alert=True)
            return
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid selection", alert=True)
            return
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Check access
        searches_remaining = user_doc.get('searches_remaining', 0)
        if searches_remaining <= 0:
            await event.edit(
                "🔒 **ACCESS DENIED**\n\n"
                "You have no search credits remaining.\n\n"
                "📞 **Contact @darkboxesAdmin to purchase credits**\n",
                buttons=OneLineKeyboard.cancel_button(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        # Special formatting for leak search
        if search_type == "leak":
            leak_text = (
                f"🚀 **ADVANCED OSINT TOOL - SEARCH ANYTHING**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **ULTRA-FAST PROCESSING**\n"
                f"💎 **Cost:** {cmd['cost']} credits\n"
                f"📁 **Returns:** JSON + TXT files\n"
                f"🌐 **Best For:** Phone numbers with country code\n\n"
                f"📝 **Enter your query below:**\n"
                f"(Email, Phone with country code, Name, etc.)"
            )
            
            await event.edit(
                leak_text,
                buttons=OneLineKeyboard.cancel_button(),
                parse_mode="md"
            )
        else:
            await event.edit(
                f"{cmd['icon']} **{cmd['name']}**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **Cost:** {cmd['cost']} credit{'s' if cmd['cost'] > 1 else ''}\n"
                f"📝 **Example:** `{cmd['example']}`\n\n"
                f"Enter your query below:",
                buttons=OneLineKeyboard.cancel_button(),
                parse_mode="md"
            )
        
        user_states[user_id] = {"action": "search", "type": search_type}
        
    except Exception as e:
        logger.error(f"❌ Error in search_callback: {e}")
        await event.answer("❌ Error", alert=True)

async def admin_callback(event):
    """Handle admin panel callbacks"""
    try:
        user_id = event.sender_id
        
        if user_id != config.ADMIN_USER_ID:
            await event.answer("❌ Access denied", alert=True)
            return
        
        data = event.data.decode()
        
        if data == "admin_panel":
            await show_admin_panel(event)
        
        elif data == "admin_today":
            await show_today_stats(event)
        
        elif data == "admin_users":
            await show_user_management(event)
        
        elif data == "admin_analytics":
            await show_analytics_panel(event)
        
        elif data == "admin_ban":
            await ask_for_ban_user(event)
        
        elif data == "admin_add_credits":
            await ask_for_add_credits(event)
        
        elif data == "admin_broadcast":
            await ask_for_broadcast(event)
        
        else:
            await event.answer("❌ Unknown admin command", alert=True)
            
    except Exception as e:
        logger.error(f"❌ Error in admin_callback: {e}")
        await event.answer("❌ Error processing request", alert=True)

async def show_admin_panel(event):
    """Show main admin panel"""
    try:
        # Get quick stats
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Total users today
        new_users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.users.count_documents({
                "joined_at": {"$gte": today.isoformat()}
            })
        )
        
        # Total searches today
        search_logs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.search_logs.find({
                "timestamp": {"$gte": today.isoformat()}
            }))
        )
        
        total_users = await asyncio.get_running_loop().run_in_executor(
            None, db_manager.db.users.count_documents, {}
        )
        
        admin_text = (
            "⚙️ **DARKBOXES ADMIN PANEL**\n\n"
            f"📊 **Quick Stats**\n"
            f"├─ Today's Users: {new_users}\n"
            f"├─ Today's Searches: {len(search_logs)}\n"
            f"└─ Total Users: {total_users}\n\n"
            f"🔧 **Select an option below:**"
        )
        
        await event.edit(admin_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error showing admin panel: {e}")
        await event.answer("❌ Error loading admin panel", alert=True)

async def show_today_stats(event):
    """Show today's statistics"""
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Total users today
        new_users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.users.count_documents({
                "joined_at": {"$gte": today.isoformat()}
            })
        )
        
        # Total searches today
        search_logs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.search_logs.find({
                "timestamp": {"$gte": today.isoformat()}
            }))
        )
        
        # Search success rate
        successful_searches = len([log for log in search_logs if log.get("success", False)])
        total_searches = len(search_logs)
        success_rate = (successful_searches / total_searches * 100) if total_searches > 0 else 0
        
        stats_text = (
            "📊 **TODAY'S STATISTICS**\n\n"
            f"👥 **Users**\n"
            f"├─ New Users: {new_users}\n"
            f"└─ Total Active: {total_searches}\n\n"
            f"🔍 **Searches**\n"
            f"├─ Total: {total_searches}\n"
            f"├─ Successful: {successful_searches}\n"
            f"├─ Failed: {total_searches - successful_searches}\n"
            f"└─ Success Rate: {success_rate:.1f}%\n\n"
            f"📅 **Date:** {today.strftime('%Y-%m-%d')}"
        )
        
        await event.edit(stats_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error showing today's stats: {e}")
        await event.answer("❌ Error loading stats", alert=True)

async def show_user_management(event):
    """Show user management options"""
    try:
        total_users = await asyncio.get_running_loop().run_in_executor(
            None, db_manager.db.users.count_documents, {}
        )
        
        active_today = await asyncio.get_running_loop().run_in_executor(
            None, db_manager.db.users.count_documents, {
                "last_seen": {"$gte": datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()}
            }
        )
        
        user_text = (
            "👥 **USER MANAGEMENT**\n\n"
            f"📈 **Overview**\n"
            f"├─ Total Users: {total_users}\n"
            f"├─ Active Today: {active_today}\n"
            f"└─ Banned Users: 0\n\n"
            f"🛠️ **Available Actions:**\n"
            f"• View user list\n"
            f"• Ban/unban users\n"
            f"• Add credits\n"
            f"• View user details\n\n"
            f"🔍 **Search Users:**\n"
            f"Type /find_user [user_id] in chat"
        )
        
        await event.edit(user_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error showing user management: {e}")
        await event.answer("❌ Error loading user management", alert=True)

async def show_analytics_panel(event):
    """Show analytics panel"""
    try:
        # Get command usage
        pipeline = [
            {"$group": {
                "_id": "$search_type",
                "count": {"$sum": 1},
                "success": {"$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}}
            }},
            {"$sort": {"count": -1}}
        ]
        
        command_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.search_logs.aggregate(pipeline))
        )
        
        analytics_text = "📈 **SEARCH ANALYTICS**\n\n"
        
        if command_stats:
            analytics_text += "🔝 **Most Used Commands:**\n"
            for stat in command_stats[:5]:
                command_name = SEARCH_COMMANDS.get(stat["_id"], {}).get("name", stat["_id"])
                success_rate = (stat["success"] / stat["count"] * 100) if stat["count"] > 0 else 0
                analytics_text += f"• {command_name}: {stat['count']} searches ({success_rate:.1f}% success)\n"
            analytics_text += "\n"
        else:
            analytics_text += "No search data available yet.\n\n"
        
        # Group performance
        if search_engine.group_performance:
            analytics_text += "📊 **Group Performance:**\n"
            for group_name, perf in search_engine.group_performance.items():
                success_rate = (perf["success"] / perf["total"] * 100) if perf["total"] > 0 else 0
                analytics_text += f"• {group_name}: {perf['total']} req ({success_rate:.1f}% success)\n"
        
        await event.edit(analytics_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error showing analytics: {e}")
        await event.answer("❌ Error loading analytics", alert=True)

async def ask_for_ban_user(event):
    """Ask for user ID to ban"""
    await event.edit(
        "🚫 **BAN/UNBAN USER**\n\n"
        "Enter user ID to ban/unban:\n"
        "(Numeric user ID)\n\n"
        "Type the user ID:",
        buttons=OneLineKeyboard.admin_panel()
    )
    
    user_states[event.sender_id] = {"action": "admin_ban"}

async def ask_for_add_credits(event):
    """Ask for user ID and credits to add"""
    await event.edit(
        "🎯 **ADD CREDITS**\n\n"
        "Enter user ID and credits (separated by space):\n"
        "Example: `123456789 10`\n\n"
        "Type user ID and credits:",
        buttons=OneLineKeyboard.admin_panel()
    )
    
    user_states[event.sender_id] = {"action": "admin_add_credits"}

async def ask_for_broadcast(event):
    """Ask for broadcast message"""
    await event.edit(
        "📢 **BROADCAST MESSAGE**\n\n"
        "Enter message to broadcast to all users:\n"
        "(Supports Markdown formatting)\n\n"
        "Type your message:",
        buttons=OneLineKeyboard.admin_panel()
    )
    
    user_states[event.sender_id] = {"action": "admin_broadcast"}

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def private_message_handler(event):
    """Handle private messages (queries and admin actions)"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        
        if state.get("action") == "search":
            await handle_search_query(event, state)
        
        elif state.get("action") == "admin_ban":
            await handle_admin_ban(event)
        
        elif state.get("action") == "admin_add_credits":
            await handle_admin_add_credits(event)
        
        elif state.get("action") == "admin_broadcast":
            await handle_admin_broadcast(event)
        
    except Exception as e:
        logger.error(f"❌ Error in private_message_handler: {e}")

async def handle_search_query(event, state):
    """Handle search queries"""
    try:
        user_id = event.sender_id
        search_type = state["type"]
        query = event.text.strip()
        
        if not query:
            await event.respond("❌ Please enter a valid query.")
            return
        
        # Validate query
        cmd = SEARCH_COMMANDS[search_type]
        validation = cmd.get("validation")
        if validation and not re.match(validation, query):
            await event.respond(f"❌ Invalid format. Example: `{cmd['example']}`")
            return
        
        # Check access
        user_doc = await db_manager.get_user(user_id)
        searches_remaining = user_doc.get('searches_remaining', 0)
        if searches_remaining <= 0:
            await event.respond(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                "Contact @darkboxesAdmin to purchase credits.",
                buttons=OneLineKeyboard.main_menu()
            )
            user_states.pop(user_id, None)
            return
        
        # Show processing message
        if search_type == "leak":
            leak_warning = (
                "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
                f"🔍 **Query:** `{query}`\n"
                f"⚡ **Processing:** Please wait...\n"
                f"💎 **Cost:** 3 credits\n\n"
                f"⏳ Processing your advanced search..."
            )
            status = await event.respond(leak_warning, parse_mode="md")
        else:
            processing_text = PremiumFormatter.format_processing(search_type, query)
            status = await event.respond(processing_text, parse_mode="md")
        
        # Perform search
        result = await search_engine.perform_search(search_type, query, user_id)
        
        # Delete status
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Handle multiple files for leak search
            if result.get("has_multiple_files"):
                # Send summary first
                await event.respond(result["result"], parse_mode="md")
                
                # Send all files
                for file_data in result.get("files", []):
                    if file_data.get("raw_bytes"):
                        file_type = file_data.get("file_type", "unknown")
                        caption = f"📁 **{file_type.upper()} DATA**\nQuery: `{query}`"
                        
                        filename = file_data.get("filename", "")
                        if not filename:
                            timestamp = int(time.time())
                            filename = f"leak_{query}_{timestamp}.{file_type}"
                        
                        await event.respond(
                            file=file_data["raw_bytes"],
                            caption=caption
                        )
            else:
                await event.respond(result["result"], parse_mode="md")
            
            await db_manager.update_searches(user_id, search_type, query, True)
        else:
            await event.respond(result["error"], parse_mode="md")
            await db_manager.update_searches(user_id, search_type, query, False)
        
        # Clear state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_search_query: {e}")
        await event.respond("❌ An error occurred during processing.")

async def handle_admin_ban(event):
    """Handle admin ban user"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return
        
        target_id = int(user_input)
        user = await db_manager.get_user(target_id)
        
        if not user:
            await event.respond(f"❌ User with ID {target_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        # Toggle ban status
        is_banned = user.get('is_banned', False)
        
        if is_banned:
            # Unban user
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": target_id},
                    {"$set": {"is_banned": False}}
                )
            )
            action = "unbanned"
        else:
            # Ban user
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: db_manager.db.users.update_one(
                    {"user_id": target_id},
                    {"$set": {"is_banned": True}}
                )
            )
            action = "banned"
        
        await event.respond(f"✅ User {target_id} has been {action}.")
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error handling admin ban: {e}")
        await event.respond("❌ Error processing request")

async def handle_admin_add_credits(event):
    """Handle admin add credits"""
    try:
        user_input = event.text.strip().split()
        if len(user_input) != 2:
            await event.respond("❌ Please enter user ID and credits (e.g., '123456789 10')")
            return
        
        target_id = int(user_input[0])
        credits = int(user_input[1])
        
        user = await db_manager.get_user(target_id)
        if not user:
            await event.respond(f"❌ User with ID {target_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        # Add credits
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: db_manager.db.users.update_one(
                {"user_id": target_id},
                {"$inc": {"searches_remaining": credits}}
            )
        )
        
        await event.respond(f"✅ Added {credits} credits to user {target_id}.")
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error handling admin add credits: {e}")
        await event.respond("❌ Error processing request")

async def handle_admin_broadcast(event):
    """Handle admin broadcast"""
    try:
        message = event.text
        
        # Get all users
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
        )
        
        sent_count = 0
        failed_count = 0
        
        for user in users:
            try:
                await bot_client.send_message(user["user_id"], message, parse_mode="md")
                sent_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Failed to send to {user['user_id']}: {e}")
        
        await event.respond(f"✅ Broadcast sent to {sent_count} users. Failed: {failed_count}")
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error handling admin broadcast: {e}")
        await event.respond("❌ Error processing broadcast")

# ================== MAIN FUNCTION ==================

async def main():
    """Main function"""
    global search_engine, bot_info
    
    try:
        logger.info("🚀 Starting DarkBoxes Intelligence System...")
        
        # Start bot client
        logger.info("🤖 Starting Telegram bot client...")
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot started: @{bot_info.username}")
        
        # Start user client if configured
        if USE_USER_ACCOUNT:
            logger.info("👤 Starting user client...")
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        else:
            logger.info("ℹ️ Using bot client for all operations")
        
        # Connect to database
        logger.info("🗄️ Connecting to MongoDB...")
        if not await db_manager.connect():
            logger.error("❌ Database connection failed")
            return
        
        # Initialize search engine
        logger.info("🔍 Initializing search engine...")
        search_engine = SearchEngine(db_manager, db_manager)
        
        # Resolve groups
        logger.info("📡 Connecting to intelligence networks...")
        for group_name, group_data in GROUP_PRIORITIES.items():
            if group_data["enabled"]:
                try:
                    group_data["entity"] = await user_client.get_entity(group_data["identifier"])
                    logger.info(f"✅ Connected: {group_data['name']}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed: {group_data['name']} - {e}")
        
        # Start background tasks
        logger.info("🔄 Starting background tasks...")
        asyncio.create_task(cleanup_expired_searches())
        
        # Start web server
        logger.info("🌐 Starting web server...")
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info(f"🤖 Bot: @{bot_info.username}")
        logger.info("=" * 60)
        
        # Send startup notification
        try:
            await bot_client.send_message(
                config.ADMIN_USER_ID,
                f"🚀 Bot started successfully!\n\n"
                f"🤖 Bot: @{bot_info.username}\n"
                f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="md"
            )
        except:
            pass
        
        # Keep the bot running
        logger.info("⏳ Bot is now running...")
        await bot_client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"💀 Fatal error in main: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("🛑 Shutting down...")
        try:
            await bot_client.disconnect()
            if USE_USER_ACCOUNT:
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except:
            pass

# ================== ENTRY POINT ==================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Received shutdown signal")
    except Exception as e:
        logger.error(f"💀 Main crashed: {e}")
