"""
DarkBoxes Intelligence System - Premium Edition
Advanced information retrieval with premium interface
Professional Admin Panel
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
    "advanced": {
        "name": "🚀 Advanced OSINT Engine",
        "identifier": "IntelXGroup",  # Replace with your advanced group ID
        "timeout": 5,
        "weight": 20,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak"
    },
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003596998816,
        "timeout": 30,
        "weight": 10,
        "enabled": True,
        "entity": None
    },
    "secondary": {
        "name": "🌐 IntelX Network",
        "identifier": "IntelXGroup",
        "timeout": 35,
        "weight": 7,
        "enabled": True,
        "entity": None
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": "nex_chats",
        "timeout": 40,
        "weight": 5,
        "enabled": True,
        "entity": None
    }
}

# Sort groups by weight (priority)
DESTINATION_GROUPS = sorted(
    [group for group in GROUP_PRIORITIES.values() if group["enabled"]],
    key=lambda x: x["weight"],
    reverse=True
)

# ================== SUBSCRIPTION PLANS ==================

SUBSCRIPTION_PLANS = {
    "basic": {
        "name": "💰 BASIC TIER",
        "price": 99,
        "searches": 10,
        "validity": "7 days",
        "features": ["10 Premium Searches", "Standard Databases", "7-day Access", "Email Support"],
        "icon": "💰",
        "color": "#27AE60",
        "for": "New users trying the service"
    },
    "standard": {
        "name": "🚀 STANDARD TIER",
        "price": 249,
        "searches": 30,
        "validity": "15 days",
        "features": ["30 Premium Searches", "All Databases", "15-day Access", "Priority Support", "Search History Saved"],
        "icon": "🚀",
        "color": "#F39C12",
        "for": "Regular users needing more searches"
    },
    "premium": {
        "name": "👑 PREMIUM TIER",
        "price": 499,
        "searches": "Unlimited",
        "validity": "30 days",
        "features": ["Unlimited Searches (30 days)", "All Premium Databases", "Priority Processing", "24/7 WhatsApp Support", "Extended Search History"],
        "icon": "👑",
        "color": "#9B59B6",
        "for": "Power users & professionals"
    }
}

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
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
        "group": "advanced",
        "expects_files": True,
        "file_types": ["json", "txt"]
    },
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • Aadhar ID • Complete address • Alternate numbers\n🔸 **Sources:** Government databases • Telecom records • Public directories\n🔸 **Confidence:** 98% accurate",
        "commands": ["/num", "/num", "/num"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1,
        "priority": "primary",
        "icon": "📱",
        "category": "identity"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Network",
        "description": "🏠 **Complete Family Analysis**\n\n🔸 **Input:** 12-digit Aadhar number\n🔸 **Returns:** All family members • Names • Relations • Ages • Addresses\n🔸 **Sources:** UIDAI database • Family registration • Government records\n🔸 **Depth:** 3-level relationship mapping",
        "commands": ["/familyinfo", "/familyinfo"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 1,
        "priority": "primary",
        "icon": "👨‍👩‍👧‍👦",
        "category": "identity"
    },
    "aadhar": {
        "name": "🆔 Aadhar Comprehensive",
        "description": "📈 **Complete Aadhar Cross-Reference**\n\n🔸 **Input:** 12-digit Aadhar number\n🔸 **Returns:** All linked numbers • Bank accounts • Addresses • Biometric status • Registration history\n🔸 **Sources:** UIDAI • Bank linkages • Government databases\n🔸 **Scope:** Pan-India coverage",
        "commands": ["/aadhar", "/aadhar", "/aadhar"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 2,
        "priority": "primary",
        "icon": "🆔",
        "category": "finance"
    },
    "vehicle": {
        "name": "🚗 Vehicle Intelligence",
        "description": "🏎️ **Complete Vehicle & Owner Analysis**\n\n🔸 **Input:** Vehicle number (Format: UP53CZ3391)\n🔸 **Returns:** Vehicle details • Owner information • Mobile number • Address • Registration history • Insurance\n🔸 **Premium Feature:** Celebrity vehicle database access\n🔸 **Real-time:** Current registration status",
        "commands": ["/vehicle", "/vnum", "/rc"],
        "example": "UP53CZ3391",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "cost": 2,
        "priority": "secondary",
        "icon": "🚗",
        "category": "assets"
    },
    "upi": {
        "name": "💳 UPI Financial Intelligence",
        "description": "💰 **UPI Account & Transaction Analysis**\n\n🔸 **Input:** UPI ID (username@paytm/bank)\n🔸 **Returns:** Account holder • Linked bank • Transaction patterns • KYC status • Last active\n🔸 **Sources:** NPCI databases • Bank records • Financial institutions\n🔸 **Security:** Bank-grade encryption",
        "commands": ["/upiinfo", "/upiinfo"],
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "cost": 1,
        "priority": "secondary",
        "icon": "💳",
        "category": "finance"
    },
    "email": {
        "name": "📧 Email Intelligence",
        "description": "🖥️ **Complete Email Profile Analysis**\n\n🔸 **Input:** Email address\n🔸 **Returns:** Personal information • Social media links • Data breach history • Associated accounts • Location data\n🔸 **Sources:** Breach databases • Social media • Public records\n🔸 **Monitoring:** Real-time alerts",
        "commands": ["/email", "/mail"],
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "cost": 1,
        "priority": "secondary",
        "icon": "📧",
        "category": "digital"
    },
    "telegram": {
        "name": "📲 Telegram Intelligence",
        "description": "⚡ **Telegram Profile Deep Analysis**\n\n🔸 **Input:** Telegram username or phone\n🔸 **Returns:** Mobile number • Profile details • Linked accounts • Activity patterns • Group memberships\n🔸 **Daily Limit:** 1 search for security\n🔸 **Privacy:** Encrypted processing",
        "commands": ["/tg", "/telegram"],
        "example": "@username or 9876543210",
        "validation": r"^(@?\w{5,32}|\d{10})$",
        "daily_limit": 1,
        "cost": 2,
        "priority": "primary",
        "icon": "📲",
        "category": "digital"
    },
    "imei": {
        "name": "📱 Device Intelligence",
        "description": "🔧 **Mobile Device Comprehensive Analysis**\n\n🔸 **Input:** 15-digit IMEI number\n🔸 **Returns:** Device make/model • Purchase details • Location history • Current user • Service history\n🔸 **Sources:** Manufacturer databases • Carrier records • Global databases\n🔸 **Tracking:** Real-time status",
        "commands": ["/imei", "/device"],
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "cost": 2,
        "priority": "secondary",
        "icon": "📱",
        "category": "assets"
    },
    "gst": {
        "name": "🏢 Business Intelligence",
        "description": "📊 **GST Business Comprehensive Analysis**\n\n🔸 **Input:** GST number\n🔸 **Returns:** Business details • Owner information • Financial patterns • Compliance status • Tax history\n🔸 **Sources:** Government registries • Financial databases • Corporate records\n🔸 **Verification:** GST portal integration",
        "commands": ["/gst", "/gstin"],
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🏢",
        "category": "business"
    },
    "insta": {
        "name": "📸 Instagram Intelligence",
        "description": "✨ **Instagram Profile Deep Analysis**\n\n🔸 **Input:** Instagram username\n🔸 **Returns:** Personal information • Contact details • Location data • Linked accounts • Activity history\n🔸 **Sources:** Social media APIs • Public databases • Metadata analysis\n🔸 **Insights:** Engagement patterns",
        "commands": ["/insta", "/instagram"],
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "cost": 1,
        "priority": "tertiary",
        "icon": "📸",
        "category": "social"
    },
    "pak": {
        "name": "🌐 Pakistan Intelligence",
        "description": "🕌 **Pakistan Number Comprehensive Analysis**\n\n🔸 **Input:** Pakistan mobile number (+92 format)\n🔸 **Returns:** Complete subscriber information • Location • Network details • Registration data\n🔸 **Sources:** International telecom databases • Government records\n🔸 **Coverage:** All major Pakistani networks",
        "commands": ["/pak", "/pk"],
        "example": "+923001234567",
        "validation": r"^\+92\d{10}$",
        "cost": 3,
        "priority": "tertiary",
        "icon": "🌐",
        "category": "international"
    },
    "ip": {
        "name": "🌍 IP Location",
        "description": "📍 **IP Address Geolocation Analysis**\n\n🔸 **Input:** IP address (IPv4/IPv6)\n🔸 **Returns:** Country • City • ISP • Coordinates • Timezone • Threat level\n🔸 **Sources:** GeoIP databases • Threat intelligence • ASN records\n🔸 **Accuracy:** Street-level precision",
        "commands": ["/ip", "/location", "/geo"],
        "example": "8.8.8.8",
        "validation": r"^(\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🌍",
        "category": "digital"
    },
    "ifsc": {
        "name": "🏦 IFSC Code Lookup",
        "description": "💼 **Bank Branch Information**\n\n🔸 **Input:** 11-digit IFSC code\n🔸 **Returns:** Bank name • Branch • Address • Contact • MICR code • Services\n🔸 **Sources:** RBI database • Bank records • Financial institutions\n🔸 **Verification:** Real-time validation",
        "commands": ["/ifsc", "/bank"],
        "example": "SBIN0001707",
        "validation": r"^[A-Z]{4}0[A-Z0-9]{6}$",
        "cost": 1,
        "priority": "secondary",
        "icon": "🏦",
        "category": "finance"
    }
}

# ================== PREMIUM TEXT FORMATTER ==================

class PremiumFormatter:
    @staticmethod
    def format_header(title: str, icon: str = "⚡") -> str:
        """Format premium header"""
        line = "═" * 40
        return f"{icon} **{title}**\n{line}\n"
    
    @staticmethod
    def format_section(title: str, content: str, icon: str = "▸") -> str:
        """Format section with icon"""
        return f"{icon} **{title}:** {content}\n"
    
    @staticmethod
    def format_list(items: List[str], icon: str = "•") -> str:
        """Format list with icons"""
        return "\n".join(f"{icon} {item}" for item in items) + "\n"
    
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
    
    @staticmethod
    def format_leak_summary(query: str, files_count: int, has_json: bool, has_txt: bool) -> str:
        """Format leak search summary"""
        summary = "🚀 **ADVANCED OSINT SEARCH COMPLETE**\n"
        summary += "═══════════════════════════════════\n\n"
        summary += f"🔍 **Query:** `{query}`\n"
        summary += f"🚀 **Source:** Advanced OSINT Engine\n"
        summary += f"⚡ **Speed:** Ultra-fast processing\n"
        summary += f"📊 **Files Received:** {files_count}\n\n"
        
        if has_json:
            summary += "✅ JSON Data File (Detailed structured data)\n"
        if has_txt:
            summary += "✅ Text Report File (Human readable report)\n"
        
        summary += "\n📁 **Files available for download below**\n"
        summary += "⚡ **Powered by DarkBoxes Advanced Intelligence**\n"
        
        return summary

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

# ================== ADMIN DATABASE MANAGER ==================

class AdminDatabaseManager:
    def __init__(self, db_manager):
        self.db = db_manager.db
    
    async def get_today_stats(self) -> Dict:
        """Get today's statistics"""
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Total users today
        new_users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.users.count_documents({
                "joined_at": {"$gte": today.isoformat()}
            })
        )
        
        # Total searches today
        search_logs = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.find({
                "timestamp": {"$gte": today.isoformat()}
            }))
        )
        
        # Total payments today
        payments = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.payments.find({
                "timestamp": {"$gte": today.isoformat()},
                "status": "completed"
            }))
        )
        
        total_payments = sum(p.get('amount', 0) for p in payments)
        
        return {
            "new_users": new_users,
            "total_searches": len(search_logs),
            "total_payments": total_payments,
            "payment_count": len(payments)
        }
    
    async def get_user_stats(self, user_id: int) -> Dict:
        """Get detailed user statistics"""
        user = await asyncio.get_running_loop().run_in_executor(
            None, self.db.users.find_one, {"user_id": user_id}
        )
        
        if not user:
            return {}
        
        # User's searches
        user_searches = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.find({"user_id": user_id}))
        )
        
        # User's referrals
        referrals = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.users.count_documents({"referred_by": str(user.get('referral_code', ''))})
        )
        
        return {
            "user_info": user,
            "total_searches": len(user_searches),
            "referrals": referrals,
            "last_searches": user_searches[-10:] if len(user_searches) > 10 else user_searches
        }
    
    async def get_top_users(self, limit: int = 10) -> List[Dict]:
        """Get top users by searches"""
        pipeline = [
            {"$group": {
                "_id": "$user_id",
                "total_searches": {"$sum": 1},
                "last_search": {"$max": "$timestamp"}
            }},
            {"$sort": {"total_searches": -1}},
            {"$limit": limit},
            {"$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "user_info"
            }},
            {"$unwind": "$user_info"},
            {"$project": {
                "user_id": "$_id",
                "username": "$user_info.username",
                "first_name": "$user_info.first_name",
                "total_searches": 1,
                "last_search": 1,
                "searches_remaining": "$user_info.searches_remaining",
                "subscription": "$user_info.subscription"
            }}
        ]
        
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(pipeline))
        )
    
    async def get_command_stats(self) -> Dict:
        """Get command usage statistics"""
        pipeline = [
            {"$group": {
                "_id": "$search_type",
                "count": {"$sum": 1},
                "unique_users": {"$addToSet": "$user_id"}
            }},
            {"$project": {
                "command": "$_id",
                "count": 1,
                "unique_users": {"$size": "$unique_users"}
            }},
            {"$sort": {"count": -1}}
        ]
        
        command_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(pipeline))
        )
        
        # Get today's command stats
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_pipeline = [
            {"$match": {"timestamp": {"$gte": today.isoformat()}}},
            {"$group": {
                "_id": "$search_type",
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}}
        ]
        
        today_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.search_logs.aggregate(today_pipeline))
        )
        
        return {
            "all_time": command_stats,
            "today": today_stats
        }
    
    async def get_referral_stats(self) -> Dict:
        """Get referral statistics"""
        pipeline = [
            {"$match": {"referrals": {"$gt": 0}}},
            {"$sort": {"referrals": -1}},
            {"$limit": 20},
            {"$project": {
                "user_id": 1,
                "username": 1,
                "first_name": 1,
                "referrals": 1,
                "referral_code": 1,
                "referral_credits": 1
            }}
        ]
        
        top_referrers = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.users.aggregate(pipeline))
        )
        
        total_referrals = sum(user.get('referrals', 0) for user in top_referrers)
        
        return {
            "top_referrers": top_referrers,
            "total_referrals": total_referrals
        }
    
    async def get_payment_stats(self) -> Dict:
        """Get payment statistics"""
        pipeline = [
            {"$match": {"status": "completed"}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                "total_amount": {"$sum": "$amount"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": -1}},
            {"$limit": 30}
        ]
        
        daily_stats = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.payments.aggregate(pipeline))
        )
        
        # Total revenue
        total_revenue = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self.db.payments.aggregate([
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ])
        )
        
        total_revenue = list(total_revenue)
        total = total_revenue[0]['total'] if total_revenue else 0
        
        return {
            "daily_stats": daily_stats,
            "total_revenue": total
        }
    
    async def get_user_list(self, page: int = 1, limit: int = 20) -> Dict:
        """Get paginated user list"""
        skip = (page - 1) * limit
        
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(self.db.users.find(
                {},
                {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
            ).sort("joined_at", -1).skip(skip).limit(limit))
        )
        
        total_users = await asyncio.get_running_loop().run_in_executor(
            None, self.db.users.count_documents, {}
        )
        
        total_pages = (total_users + limit - 1) // limit
        
        return {
            "users": users,
            "page": page,
            "total_pages": total_pages,
            "total_users": total_users
        }
    
    async def search_users(self, query: str) -> List[Dict]:
        """Search users by username, name, or user_id"""
        try:
            # Try user_id if query is numeric
            if query.isdigit():
                user_id = int(query)
                users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(self.db.users.find(
                        {"user_id": user_id},
                        {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
                    ))
                )
            else:
                # Search by username or first name
                regex = re.compile(f".*{re.escape(query)}.*", re.IGNORECASE)
                users = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: list(self.db.users.find(
                        {"$or": [
                            {"username": regex},
                            {"first_name": regex}
                        ]},
                        {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1, "total_searches": 1}
                    ))
                )
            
            return users
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []

# ================== DATABASE MANAGER ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.admin_db = None
    
    async def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            logger.info("🔌 Connecting to MongoDB...")
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            self.admin_db = AdminDatabaseManager(self)
            
            # Create indexes
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.create_index([("user_id", 1)], unique=True)
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.create_index([("timestamp", -1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.create_index([("user_id", 1), ("timestamp", -1)])
            )
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.payments.create_index([("timestamp", -1)])
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
                "wallet_balance": 0,
                "is_banned": False,
                "is_admin": False
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
            
            # Check subscription first
            subscription = user.get("subscription")
            subscription_expiry = user.get("subscription_expiry")
            
            if subscription and subscription_expiry:
                expiry_date = datetime.fromisoformat(subscription_expiry)
                if expiry_date > datetime.now(timezone.utc):
                    # User has active subscription
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.users.update_one(
                            {"user_id": user_id},
                            {
                                "$inc": {"total_searches": 1},
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
                        "credits_used": 0,
                        "subscription_used": subscription
                    }
                    
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: self.db.search_logs.insert_one(search_log)
                    )
                    return True
            
            # Use credits
            searches_remaining = user.get("searches_remaining", 0)
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
                "credits_used": credits_used,
                "subscription_used": None
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.search_logs.insert_one(search_log)
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error updating searches: {e}")
            return False
    
    async def add_subscription(self, user_id: int, plan_id: str, days: int) -> bool:
        """Add subscription to user"""
        try:
            plan = SUBSCRIPTION_PLANS[plan_id]
            expiry_date = datetime.now(timezone.utc) + timedelta(days=days)
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "subscription": plan_id,
                            "subscription_expiry": expiry_date.isoformat(),
                            "searches_remaining": 0  # Reset as unlimited
                        }
                    }
                )
            )
            
            # Log payment
            payment_log = {
                "user_id": user_id,
                "plan_id": plan_id,
                "amount": plan["price"],
                "status": "completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "admin_added": True
            }
            
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.payments.insert_one(payment_log)
            )
            
            return True
        except Exception as e:
            logger.error(f"❌ Error adding subscription: {e}")
            return False
    
    async def add_referral_credit(self, referrer_id: int, credits: int = 1) -> bool:
        """Add referral credits to referrer"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": referrer_id},
                    {
                        "$inc": {
                            "referrals": 1,
                            "referral_credits": credits,
                            "searches_remaining": credits
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding referral credit: {e}")
            return False
    
    async def ban_user(self, user_id: int, reason: str = "Violation of terms") -> bool:
        """Ban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "is_banned": True,
                            "ban_reason": reason,
                            "banned_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error banning user: {e}")
            return False
    
    async def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "is_banned": False
                        },
                        "$unset": {
                            "ban_reason": "",
                            "banned_at": ""
                        }
                    }
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error unbanning user: {e}")
            return False
    
    async def add_admin(self, user_id: int) -> bool:
        """Add user as admin"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_admin": True}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding admin: {e}")
            return False
    
    async def remove_admin(self, user_id: int) -> bool:
        """Remove user from admin"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_admin": False}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error removing admin: {e}")
            return False
    
    async def add_credits(self, user_id: int, credits: int) -> bool:
        """Add credits to user"""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.db.users.update_one(
                    {"user_id": user_id},
                    {"$inc": {"searches_remaining": credits}}
                )
            )
            return True
        except Exception as e:
            logger.error(f"❌ Error adding credits: {e}")
            return False

# ================== ONE COMMAND PER LINE KEYBOARD ==================

class OneLineKeyboard:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build keyboard with ONE COMMAND PER LINE"""
        buttons = []
        
        # Add each command in its own line - LEAK COMMAND FIRST
        commands_in_order = [
            "leak",  # Advanced OSINT tool first
            "phone", "family", "aadhar", "vehicle", 
            "upi", "email", "telegram", "imei",
            "gst", "insta", "pak", "ip", "ifsc"
        ]
        
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
        buttons.append([Button.inline("💎 Premium Plans", "premium")])
        buttons.append([Button.inline("📊 Refer & Earn", "referrals")])
        buttons.append([Button.inline("🆘 Support", "support")])
        
        # Add admin button if admin
        if is_admin:
            buttons.append([Button.inline("⚙️ Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium plan selection"""
        buttons = [
            [Button.inline("💰 Basic Tier - ₹99", "plan_basic")],
            [Button.inline("🚀 Standard Tier - ₹249", "plan_standard")],
            [Button.inline("👑 Premium Tier - ₹499", "plan_premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def admin_panel() -> List[List[Button]]:
        """Professional admin panel with all features"""
        buttons = [
            [Button.inline("📊 Today's Stats", "admin_today")],
            [Button.inline("👥 User Management", "admin_users")],
            [Button.inline("📈 Search Analytics", "admin_analytics")],
            [Button.inline("💰 Payment Stats", "admin_payments")],
            [Button.inline("🔍 Search Users", "admin_search_user")],
            [Button.inline("📢 Broadcast", "admin_broadcast")],
            [Button.inline("⚙️ Bot Settings", "admin_settings")],
            [Button.inline("🚫 Ban/Unban User", "admin_ban")],
            [Button.inline("👑 Add/Remove Admin", "admin_admin")],
            [Button.inline("🎯 Add Credits", "admin_add_credits")],
            [Button.inline("📊 Export Data", "admin_export")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        return buttons
    
    @staticmethod
    def user_management_panel() -> List[List[Button]]:
        """User management panel"""
        buttons = [
            [Button.inline("📋 User List", "admin_user_list_1")],
            [Button.inline("🏆 Top Users", "admin_top_users")],
            [Button.inline("📊 Referral Stats", "admin_referrals")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def analytics_panel() -> List[List[Button]]:
        """Analytics panel"""
        buttons = [
            [Button.inline("📈 Command Usage", "admin_command_stats")],
            [Button.inline("📊 Daily Stats Graph", "admin_graph_daily")],
            [Button.inline("📋 Most Used Commands", "admin_top_commands")],
            [Button.inline("👤 User Activity", "admin_user_activity")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def payment_panel() -> List[List[Button]]:
        """Payment management panel"""
        buttons = [
            [Button.inline("💰 Today's Revenue", "admin_today_payments")],
            [Button.inline("📊 Revenue Graph", "admin_graph_revenue")],
            [Button.inline("💸 Total Revenue", "admin_total_revenue")],
            [Button.inline("« Admin Panel", "admin_panel")]
        ]
        return buttons
    
    @staticmethod
    def user_list_buttons(page: int, total_pages: int) -> List[List[Button]]:
        """User list pagination buttons"""
        buttons = []
        
        # Navigation buttons
        nav_row = []
        if page > 1:
            nav_row.append(Button.inline("⬅️ Previous", f"admin_user_list_{page-1}"))
        nav_row.append(Button.inline(f"{page}/{total_pages}", "noop"))
        if page < total_pages:
            nav_row.append(Button.inline("Next ➡️", f"admin_user_list_{page+1}"))
        
        if nav_row:
            buttons.append(nav_row)
        
        buttons.append([Button.inline("« User Management", "admin_users")])
        buttons.append([Button.inline("« Admin Panel", "admin_panel")])
        
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]
    
    @staticmethod
    def back_to_admin() -> List[List[Button]]:
        """Back to admin panel button"""
        return [[Button.inline("« Back to Admin", "admin_panel")]]
    
    @staticmethod
    def confirm_buttons(action: str, target_id: int) -> List[List[Button]]:
        """Confirmation buttons for actions"""
        return [
            [Button.inline(f"✅ Confirm {action}", f"confirm_{action}_{target_id}")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
    
    @staticmethod
    def profile_menu() -> List[List[Button]]:
        """Profile menu buttons"""
        return [
            [Button.inline("🔄 Refresh", "profile")],
            [Button.inline("💳 Add Credits", "buy_credits")],
            [Button.inline("💎 Upgrade Plan", "premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def support_menu() -> List[List[Button]]:
        """Support menu buttons"""
        return [
            [Button.inline("📞 Contact Admin", "contact_admin")],
            [Button.inline("❓ FAQ", "faq")],
            [Button.inline("⚠️ Report Issue", "report_issue")],
            [Button.inline("📖 Tutorial", "tutorial")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
    
    @staticmethod
    def referrals_menu() -> List[List[Button]]:
        """Referrals menu buttons"""
        return [
            [Button.inline("📋 My Referrals", "my_referrals")],
            [Button.inline("📊 Referral Stats", "referral_stats")],
            [Button.inline("📢 Share Referral", "share_referral")],
            [Button.inline("« Main Menu", "main_menu")]
        ]

# ================== ADMIN PANEL HANDLER ==================

class AdminPanelHandler:
    def __init__(self, db_manager: DatabaseManager, bot_client: TelegramClient):
        self.db = db_manager
        self.bot = bot_client
        self.admin_users = set()
        
        # Load admin users from database
        asyncio.create_task(self.load_admin_users())
    
    async def load_admin_users(self):
        """Load admin users from database"""
        try:
            admins = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.users.find({"is_admin": True}, {"user_id": 1}))
            )
            self.admin_users = {admin["user_id"] for admin in admins}
            logger.info(f"✅ Loaded {len(self.admin_users)} admin users")
        except Exception as e:
            logger.error(f"❌ Error loading admin users: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_users or user_id == config.ADMIN_USER_ID
    
    async def handle_admin_callback(self, event):
        """Handle admin panel callbacks"""
        try:
            user_id = event.sender_id
            
            if not self.is_admin(user_id):
                await event.answer("❌ Access denied", alert=True)
                return
            
            data = event.data.decode()
            
            if data == "admin_panel":
                await self.show_admin_panel(event)
            
            elif data == "admin_today":
                await self.show_today_stats(event)
            
            elif data.startswith("admin_user_list_"):
                page = int(data.split("_")[-1])
                await self.show_user_list(event, page)
            
            elif data == "admin_users":
                await self.show_user_management(event)
            
            elif data == "admin_top_users":
                await self.show_top_users(event)
            
            elif data == "admin_referrals":
                await self.show_referral_stats(event)
            
            elif data == "admin_analytics":
                await self.show_analytics_panel(event)
            
            elif data == "admin_command_stats":
                await self.show_command_stats(event)
            
            elif data == "admin_top_commands":
                await self.show_top_commands(event)
            
            elif data == "admin_user_activity":
                await self.show_user_activity(event)
            
            elif data == "admin_graph_daily":
                await self.generate_daily_graph(event)
            
            elif data == "admin_payments":
                await self.show_payment_panel(event)
            
            elif data == "admin_today_payments":
                await self.show_today_payments(event)
            
            elif data == "admin_total_revenue":
                await self.show_total_revenue(event)
            
            elif data == "admin_graph_revenue":
                await self.generate_revenue_graph(event)
            
            elif data == "admin_search_user":
                await self.ask_for_user_search(event)
            
            elif data == "admin_broadcast":
                await self.ask_for_broadcast(event)
            
            elif data == "admin_ban":
                await self.ask_for_ban_user(event)
            
            elif data == "admin_admin":
                await self.ask_for_admin_management(event)
            
            elif data == "admin_add_credits":
                await self.ask_for_add_credits(event)
            
            elif data == "admin_settings":
                await self.show_bot_settings(event)
            
            elif data == "admin_export":
                await self.export_data(event)
            
            elif data.startswith("confirm_ban_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_ban_user(event, target_id)
            
            elif data.startswith("confirm_unban_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_unban_user(event, target_id)
            
            elif data.startswith("confirm_add_admin_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_add_admin(event, target_id)
            
            elif data.startswith("confirm_remove_admin_"):
                target_id = int(data.split("_")[-1])
                await self.confirm_remove_admin(event, target_id)
            
            elif data.startswith("user_detail_"):
                target_id = int(data.split("_")[-1])
                await self.show_user_detail(event, target_id)
            
        except Exception as e:
            logger.error(f"❌ Error in admin callback: {e}")
            await event.answer("❌ Error processing request", alert=True)
    
    async def show_admin_panel(self, event):
        """Show main admin panel"""
        admin_text = (
            "⚙️ **DARKBOXES ADMIN PANEL**\n\n"
            "📊 **Quick Stats**\n"
        )
        
        # Get quick stats
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            admin_text += f"├─ Today's Users: {today_stats['new_users']}\n"
            admin_text += f"├─ Today's Searches: {today_stats['total_searches']}\n"
            admin_text += f"├─ Today's Payments: ₹{today_stats['total_payments']}\n"
            
            total_users = await asyncio.get_running_loop().run_in_executor(
                None, self.db.db.users.count_documents, {}
            )
            admin_text += f"└─ Total Users: {total_users}\n"
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            admin_text += "⚠️ Error loading stats\n"
        
        admin_text += "\n🔧 **Select an option below:**"
        
        await event.edit(admin_text, buttons=OneLineKeyboard.admin_panel(), parse_mode="md")
    
    async def show_today_stats(self, event):
        """Show today's statistics in detail"""
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            command_stats = await self.db.admin_db.get_command_stats()
            
            stats_text = (
                "📊 **TODAY'S STATISTICS**\n"
                "═══════════════════════\n\n"
                f"📈 **User Statistics**\n"
                f"├─ New Users: {today_stats['new_users']}\n"
                f"├─ Total Searches: {today_stats['total_searches']}\n"
                f"├─ Total Payments: ₹{today_stats['total_payments']}\n"
                f"└─ Payment Count: {today_stats['payment_count']}\n\n"
            )
            
            if command_stats['today']:
                stats_text += "🔍 **Top Commands Today**\n"
                for i, cmd in enumerate(command_stats['today'][:5], 1):
                    cmd_name = SEARCH_COMMANDS.get(cmd['_id'], {}).get('name', cmd['_id'])
                    stats_text += f"{i}. {cmd_name}: {cmd['count']} searches\n"
            
            await event.edit(stats_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing today stats: {e}")
            await event.edit("❌ Error loading statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_list(self, event, page: int = 1):
        """Show paginated user list"""
        try:
            user_list = await self.db.admin_db.get_user_list(page, 15)
            
            users_text = f"👥 **USER LIST** (Page {page}/{user_list['total_pages']})\n"
            users_text += "═══════════════════════\n\n"
            
            for i, user in enumerate(user_list['users'], 1):
                idx = (page - 1) * 15 + i
                username = f"@{user['username']}" if user.get('username') else "No username"
                joined = user.get('joined_at', '')[:10]
                searches = user.get('total_searches', 0)
                
                users_text += (
                    f"{idx}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Joined: {joined}\n"
                    f"   └─ Searches: {searches}\n\n"
                )
            
            users_text += f"📊 **Total Users:** {user_list['total_users']}"
            
            await event.edit(
                users_text,
                buttons=OneLineKeyboard.user_list_buttons(page, user_list['total_pages']),
                parse_mode="md"
            )
        except Exception as e:
            logger.error(f"Error showing user list: {e}")
            await event.edit("❌ Error loading user list", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_management(self, event):
        """Show user management panel"""
        management_text = (
            "👥 **USER MANAGEMENT**\n"
            "═══════════════════════\n\n"
            "📋 **Available Actions:**\n"
            "• View all users with pagination\n"
            "• View top users by searches\n"
            "• View referral statistics\n"
            "• Search for specific users\n"
            "• View user details\n\n"
            "Select an option below:"
        )
        
        await event.edit(management_text, buttons=OneLineKeyboard.user_management_panel(), parse_mode="md")
    
    async def show_top_users(self, event):
        """Show top users by searches"""
        try:
            top_users = await self.db.admin_db.get_top_users(15)
            
            top_text = "🏆 **TOP USERS BY SEARCHES**\n"
            top_text += "═══════════════════════\n\n"
            
            for i, user in enumerate(top_users, 1):
                username = f"@{user['username']}" if user.get('username') else "No username"
                sub_status = user.get('subscription', 'None')
                
                top_text += (
                    f"{i}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Searches: {user['total_searches']}\n"
                    f"   ├─ Credits: {user.get('searches_remaining', 0)}\n"
                    f"   ├─ Subscription: {sub_status}\n"
                    f"   └─ Last: {user.get('last_search', '')[:10]}\n\n"
                )
            
            await event.edit(top_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing top users: {e}")
            await event.edit("❌ Error loading top users", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_referral_stats(self, event):
        """Show referral statistics"""
        try:
            referral_stats = await self.db.admin_db.get_referral_stats()
            
            ref_text = "📊 **REFERRAL STATISTICS**\n"
            ref_text += "═══════════════════════\n\n"
            
            ref_text += f"📈 **Total Referrals:** {referral_stats['total_referrals']}\n\n"
            
            if referral_stats['top_referrers']:
                ref_text += "🏆 **TOP REFERRERS**\n"
                for i, user in enumerate(referral_stats['top_referrers'][:10], 1):
                    username = f"@{user['username']}" if user.get('username') else "No username"
                    ref_text += (
                        f"{i}. **{user['first_name']}**\n"
                        f"   ├─ {username}\n"
                        f"   ├─ Referrals: {user['referrals']}\n"
                        f"   ├─ Code: `{user.get('referral_code', 'N/A')}`\n"
                        f"   └─ Credits: {user.get('referral_credits', 0)}\n\n"
                    )
            else:
                ref_text += "No referrals yet.\n"
            
            await event.edit(ref_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing referral stats: {e}")
            await event.edit("❌ Error loading referral statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_analytics_panel(self, event):
        """Show analytics panel"""
        analytics_text = (
            "📈 **SEARCH ANALYTICS**\n"
            "═══════════════════════\n\n"
            "📊 **Available Reports:**\n"
            "• Command usage statistics\n"
            "• Daily activity graphs\n"
            "• Most used commands\n"
            "• User activity patterns\n\n"
            "Select an option below:"
        )
        
        await event.edit(analytics_text, buttons=OneLineKeyboard.analytics_panel(), parse_mode="md")
    
    async def show_command_stats(self, event):
        """Show command usage statistics"""
        try:
            command_stats = await self.db.admin_db.get_command_stats()
            
            stats_text = "🔍 **COMMAND USAGE STATISTICS**\n"
            stats_text += "═══════════════════════\n\n"
            
            # All-time stats
            stats_text += "📊 **ALL-TIME STATS**\n"
            total_searches = sum(cmd['count'] for cmd in command_stats['all_time'])
            stats_text += f"Total Searches: {total_searches}\n\n"
            
            for cmd in command_stats['all_time'][:10]:
                cmd_name = SEARCH_COMMANDS.get(cmd['command'], {}).get('name', cmd['command'])
                percentage = (cmd['count'] / total_searches * 100) if total_searches > 0 else 0
                stats_text += (
                    f"• **{cmd_name}**\n"
                    f"  ├─ Searches: {cmd['count']}\n"
                    f"  ├─ Unique Users: {cmd['unique_users']}\n"
                    f"  └─ Usage: {percentage:.1f}%\n\n"
                )
            
            # Today's stats
            if command_stats['today']:
                stats_text += "📅 **TODAY'S STATS**\n"
                for cmd in command_stats['today'][:5]:
                    cmd_name = SEARCH_COMMANDS.get(cmd['_id'], {}).get('name', cmd['_id'])
                    stats_text += f"• {cmd_name}: {cmd['count']}\n"
            
            await event.edit(stats_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing command stats: {e}")
            await event.edit("❌ Error loading command statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_top_commands(self, event):
        """Show most used commands"""
        try:
            command_stats = await self.db.admin_db.get_command_stats()
            
            top_text = "🎯 **MOST USED COMMANDS**\n"
            top_text += "═══════════════════════\n\n"
            
            # Prepare data for bar chart
            commands = []
            counts = []
            
            for cmd in command_stats['all_time'][:8]:
                cmd_name = SEARCH_COMMANDS.get(cmd['command'], {}).get('name', cmd['command'])
                commands.append(cmd_name[:15])  # Truncate long names
                counts.append(cmd['count'])
            
            # Create bar chart
            plt.figure(figsize=(10, 6))
            bars = plt.bar(commands, counts, color='skyblue')
            plt.title('Most Used Commands', fontsize=14, fontweight='bold')
            plt.xlabel('Commands', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                plt.text(bar.get_x() + bar.get_width()/2., height,
                        f'{int(height)}', ha='center', va='bottom')
            
            plt.tight_layout()
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption="📊 **Command Usage Visualization**",
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating command chart: {e}")
            await event.edit("❌ Error generating visualization", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_activity(self, event):
        """Show user activity patterns"""
        try:
            # Get activity data for last 7 days
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": seven_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "count": {"$sum": 1},
                    "unique_users": {"$addToSet": "$user_id"}
                }},
                {"$project": {
                    "date": "$_id",
                    "searches": "$count",
                    "unique_users": {"$size": "$unique_users"}
                }},
                {"$sort": {"date": 1}}
            ]
            
            activity_data = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.aggregate(pipeline))
            )
            
            if not activity_data:
                await event.edit("📊 No activity data available for the last 7 days.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Create visualization
            dates = [data['date'][5:] for data in activity_data]  # Remove year
            searches = [data['searches'] for data in activity_data]
            users = [data['unique_users'] for data in activity_data]
            
            plt.figure(figsize=(12, 6))
            
            x = range(len(dates))
            width = 0.35
            
            plt.bar([i - width/2 for i in x], searches, width, label='Searches', color='skyblue')
            plt.bar([i + width/2 for i in x], users, width, label='Unique Users', color='lightcoral')
            
            plt.title('User Activity (Last 7 Days)', fontsize=14, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Count', fontsize=12)
            plt.xticks(x, dates, rotation=45)
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # Add value labels
            for i, (s, u) in enumerate(zip(searches, users)):
                plt.text(i - width/2, s + max(searches)*0.01, str(s), 
                        ha='center', va='bottom', fontsize=8)
                plt.text(i + width/2, u + max(users)*0.01, str(u), 
                        ha='center', va='bottom', fontsize=8)
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            # Calculate totals
            total_searches = sum(searches)
            total_users = sum(users)
            avg_searches = total_searches / len(activity_data)
            
            caption = (
                f"📊 **User Activity Analysis**\n\n"
                f"📈 **Last 7 Days Summary:**\n"
                f"├─ Total Searches: {total_searches}\n"
                f"├─ Total Unique Users: {total_users}\n"
                f"├─ Average Daily Searches: {avg_searches:.1f}\n"
                f"└─ Peak Day: {dates[searches.index(max(searches))]} ({max(searches)} searches)"
            )
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating activity chart: {e}")
            await event.edit("❌ Error generating activity visualization", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def generate_daily_graph(self, event):
        """Generate daily activity graph"""
        try:
            # Get daily stats for last 30 days
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": thirty_days_ago.isoformat()}}},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": {"$toDate": "$timestamp"}}},
                    "searches": {"$sum": 1},
                    "users": {"$addToSet": "$user_id"}
                }},
                {"$project": {
                    "date": "$_id",
                    "searches": 1,
                    "users": {"$size": "$users"}
                }},
                {"$sort": {"date": 1}}
            ]
            
            daily_data = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.aggregate(pipeline))
            )
            
            if not daily_data:
                await event.edit("📊 No activity data available.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Prepare data
            dates = [data['date'][5:] for data in daily_data]  # Remove year
            searches = [data['searches'] for data in daily_data]
            
            # Create line chart
            plt.figure(figsize=(14, 7))
            plt.plot(dates, searches, marker='o', linewidth=2, markersize=6, color='royalblue')
            plt.fill_between(dates, searches, alpha=0.3, color='skyblue')
            
            plt.title('Daily Search Activity (Last 30 Days)', fontsize=16, fontweight='bold')
            plt.xlabel('Date', fontsize=12)
            plt.ylabel('Number of Searches', fontsize=12)
            plt.xticks(rotation=45, ha='right')
            plt.grid(True, alpha=0.3)
            
            # Highlight max point
            max_idx = searches.index(max(searches))
            plt.plot(dates[max_idx], searches[max_idx], 'ro', markersize=10)
            plt.annotate(f'Peak: {searches[max_idx]}', 
                        xy=(dates[max_idx], searches[max_idx]),
                        xytext=(10, 10), textcoords='offset points',
                        fontsize=10, color='red', fontweight='bold')
            
            plt.tight_layout()
            
            # Calculate statistics
            total_searches = sum(searches)
            avg_searches = total_searches / len(searches)
            growth = ((searches[-1] - searches[0]) / searches[0] * 100) if searches[0] > 0 else 0
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            caption = (
                f"📈 **Daily Activity Analysis**\n\n"
                f"📊 **Statistics (Last 30 Days):**\n"
                f"├─ Total Searches: {total_searches}\n"
                f"├─ Average Daily: {avg_searches:.1f}\n"
                f"├─ Peak Activity: {searches[max_idx]} searches\n"
                f"└─ Growth Rate: {growth:+.1f}%\n\n"
                f"📅 **Trend Analysis:**\n"
            )
            
            if growth > 0:
                caption += "📈 Positive growth trend detected\n"
            else:
                caption += "📉 Negative growth trend detected\n"
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating daily graph: {e}")
            await event.edit("❌ Error generating daily graph", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def show_payment_panel(self, event):
        """Show payment management panel"""
        payment_text = (
            "💰 **PAYMENT MANAGEMENT**\n"
            "═══════════════════════\n\n"
            "📊 **Available Reports:**\n"
            "• Today's revenue\n"
            "• Revenue graphs\n"
            "• Total revenue\n"
            "• Payment history\n\n"
            "Select an option below:"
        )
        
        await event.edit(payment_text, buttons=OneLineKeyboard.payment_panel(), parse_mode="md")
    
    async def show_today_payments(self, event):
        """Show today's payment statistics"""
        try:
            today_stats = await self.db.admin_db.get_today_stats()
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            # Get today's payments
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_payments = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.payments.find({
                    "timestamp": {"$gte": today.isoformat()},
                    "status": "completed"
                }).sort("timestamp", -1).limit(10))
            )
            
            payment_text = "💰 **TODAY'S PAYMENTS**\n"
            payment_text += "═══════════════════════\n\n"
            
            payment_text += f"📊 **Summary**\n"
            payment_text += f"├─ Total Revenue: ₹{today_stats['total_payments']}\n"
            payment_text += f"├─ Number of Payments: {today_stats['payment_count']}\n"
            payment_text += f"└─ Average Payment: ₹{today_stats['total_payments']/today_stats['payment_count']:.2f}\n\n"
            
            if today_payments:
                payment_text += "📋 **Recent Payments**\n"
                for i, payment in enumerate(today_payments[:5], 1):
                    plan = SUBSCRIPTION_PLANS.get(payment.get('plan_id', ''), {})
                    plan_name = plan.get('name', payment.get('plan_id', 'N/A'))
                    time_str = payment.get('timestamp', '')[:16]
                    
                    payment_text += (
                        f"{i}. **₹{payment.get('amount', 0)}**\n"
                        f"   ├─ Plan: {plan_name}\n"
                        f"   ├─ User: `{payment.get('user_id', 'N/A')}`\n"
                        f"   └─ Time: {time_str}\n\n"
                    )
            else:
                payment_text += "No payments today.\n"
            
            await event.edit(payment_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing today payments: {e}")
            await event.edit("❌ Error loading payment statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_total_revenue(self, event):
        """Show total revenue statistics"""
        try:
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            revenue_text = "💰 **TOTAL REVENUE**\n"
            revenue_text += "═══════════════════════\n\n"
            
            revenue_text += f"📊 **Overall Statistics**\n"
            revenue_text += f"├─ Total Revenue: ₹{payment_stats['total_revenue']}\n"
            revenue_text += f"├─ Daily Average: ₹{payment_stats['total_revenue']/30:.2f}\n"
            revenue_text += f"└─ Projected Monthly: ₹{payment_stats['total_revenue']:.2f}\n\n"
            
            if payment_stats['daily_stats']:
                revenue_text += "📅 **Last 30 Days Revenue**\n"
                total_last_30 = sum(day['total_amount'] for day in payment_stats['daily_stats'])
                avg_last_30 = total_last_30 / len(payment_stats['daily_stats'])
                
                revenue_text += f"├─ Total (30 days): ₹{total_last_30}\n"
                revenue_text += f"├─ Daily Average: ₹{avg_last_30:.2f}\n"
                revenue_text += f"└─ Growth Potential: ₹{avg_last_30 * 30:.2f}/month\n\n"
                
                revenue_text += "📈 **Top 5 Revenue Days**\n"
                top_days = sorted(payment_stats['daily_stats'], key=lambda x: x['total_amount'], reverse=True)[:5]
                for i, day in enumerate(top_days, 1):
                    revenue_text += f"{i}. {day['_id']}: ₹{day['total_amount']} ({day['count']} payments)\n"
            
            await event.edit(revenue_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        except Exception as e:
            logger.error(f"Error showing total revenue: {e}")
            await event.edit("❌ Error loading revenue statistics", buttons=OneLineKeyboard.back_to_admin())
    
    async def generate_revenue_graph(self, event):
        """Generate revenue graph"""
        try:
            payment_stats = await self.db.admin_db.get_payment_stats()
            
            if not payment_stats['daily_stats']:
                await event.edit("💰 No revenue data available.", 
                               buttons=OneLineKeyboard.back_to_admin())
                return
            
            # Prepare data
            dates = [day['_id'][5:] for day in payment_stats['daily_stats']]  # Remove year
            amounts = [day['total_amount'] for day in payment_stats['daily_stats']]
            counts = [day['count'] for day in payment_stats['daily_stats']]
            
            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            
            # Revenue line chart
            ax1.plot(dates, amounts, marker='o', linewidth=2, markersize=6, color='green')
            ax1.fill_between(dates, amounts, alpha=0.3, color='lightgreen')
            ax1.set_title('Daily Revenue (Last 30 Days)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('Revenue (₹)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.tick_params(axis='x', rotation=45)
            
            # Add value labels for peaks
            for i, (date, amount) in enumerate(zip(dates, amounts)):
                if amount == max(amounts):
                    ax1.annotate(f'₹{amount}', xy=(date, amount),
                                xytext=(0, 10), textcoords='offset points',
                                fontsize=10, color='red', fontweight='bold',
                                ha='center')
            
            # Payment count bar chart
            bars = ax2.bar(dates, counts, color='orange', alpha=0.7)
            ax2.set_title('Daily Payment Count', fontsize=14, fontweight='bold')
            ax2.set_xlabel('Date', fontsize=12)
            ax2.set_ylabel('Number of Payments', fontsize=12)
            ax2.grid(True, alpha=0.3)
            ax2.tick_params(axis='x', rotation=45)
            
            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax2.text(bar.get_x() + bar.get_width()/2., height,
                            f'{int(height)}', ha='center', va='bottom', fontsize=9)
            
            plt.tight_layout()
            
            # Calculate statistics
            total_revenue = sum(amounts)
            total_payments = sum(counts)
            avg_revenue = total_revenue / len(amounts)
            avg_payments = total_payments / len(counts)
            
            # Save to bytes
            buf = BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            caption = (
                f"📊 **Revenue Analysis**\n\n"
                f"💰 **Last 30 Days Summary:**\n"
                f"├─ Total Revenue: ₹{total_revenue}\n"
                f"├─ Total Payments: {total_payments}\n"
                f"├─ Average Daily Revenue: ₹{avg_revenue:.2f}\n"
                f"├─ Average Daily Payments: {avg_payments:.1f}\n"
                f"└─ Average Payment Value: ₹{total_revenue/total_payments:.2f}\n\n"
                f"📈 **Insights:**\n"
            )
            
            if avg_revenue > 1000:
                caption += "• 📈 Strong revenue performance\n"
            elif avg_revenue > 500:
                caption += "• 📊 Moderate revenue growth\n"
            else:
                caption += "• ⚠️ Revenue needs improvement\n"
            
            # Send image
            await event.delete()
            await self.bot.send_file(
                event.chat_id,
                buf,
                caption=caption,
                buttons=OneLineKeyboard.back_to_admin()
            )
            
        except Exception as e:
            logger.error(f"Error generating revenue graph: {e}")
            await event.edit("❌ Error generating revenue visualization", 
                           buttons=OneLineKeyboard.back_to_admin())
    
    async def ask_for_user_search(self, event):
        """Ask for user search query"""
        await event.edit(
            "🔍 **SEARCH USER**\n\n"
            "Enter search criteria:\n"
            "• User ID (numeric)\n"
            "• Username (with or without @)\n"
            "• First name\n\n"
            "Type your search query:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        # Set state for message handler
        user_states[event.sender_id] = {"action": "admin_search_user"}
    
    async def ask_for_broadcast(self, event):
        """Ask for broadcast message"""
        await event.edit(
            "📢 **BROADCAST MESSAGE**\n\n"
            "Enter your broadcast message:\n"
            "(Supports Markdown formatting)\n\n"
            "Type your message:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_broadcast"}
    
    async def ask_for_ban_user(self, event):
        """Ask for user ID to ban/unban"""
        await event.edit(
            "🚫 **BAN/UNBAN USER**\n\n"
            "Enter user ID to ban/unban:\n"
            "(Numeric user ID)\n\n"
            "Type the user ID:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_ban"}
    
    async def ask_for_admin_management(self, event):
        """Ask for user ID for admin management"""
        await event.edit(
            "👑 **ADMIN MANAGEMENT**\n\n"
            "Enter user ID to add/remove as admin:\n"
            "(Numeric user ID)\n\n"
            "Type the user ID:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_management"}
    
    async def ask_for_add_credits(self, event):
        """Ask for user ID and credits to add"""
        await event.edit(
            "🎯 **ADD CREDITS**\n\n"
            "Enter in format:\n"
            "`user_id credits`\n\n"
            "Example: `123456789 10`\n"
            "This will add 10 credits to user 123456789\n\n"
            "Type the command:",
            buttons=OneLineKeyboard.back_to_admin()
        )
        
        user_states[event.sender_id] = {"action": "admin_add_credits"}
    
    async def show_bot_settings(self, event):
        """Show bot settings"""
        settings_text = (
            "⚙️ **BOT SETTINGS**\n"
            "═══════════════════════\n\n"
            "📊 **Current Configuration:**\n"
            f"├─ Bot: @{bot_info.username}\n"
            f"├─ Admin: {config.ADMIN_USER_ID}\n"
            f"├─ New User Credits: {config.NEW_USER_CREDITS}\n"
            f"├─ Referral Reward: {config.REFERRAL_REWARD}\n"
            f"├─ Max File Size: {config.MAX_FILE_SIZE_MB}MB\n"
            f"├─ Group Timeout: {config.GROUP_TIMEOUT}s\n"
            f"└─ UPI ID: {config.UPI_ID}\n\n"
            "🔄 **Available Actions:**\n"
            "• Adjust user credits\n"
            "• Modify referral rewards\n"
            "• Update configuration\n"
            "• Restart services\n\n"
            "⚠️ **Note:** Some settings require bot restart."
        )
        
        await event.edit(settings_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
    
    async def export_data(self, event):
        """Export bot data"""
        try:
            await event.edit("📥 **EXPORTING DATA...**\n\nThis may take a moment...")
            
            # Get all data
            users = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.users.find({}, {
                    "user_id": 1, "username": 1, "first_name": 1, 
                    "joined_at": 1, "total_searches": 1, "searches_remaining": 1,
                    "subscription": 1, "referrals": 1, "is_banned": 1
                }))
            )
            
            payments = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.payments.find({}, {
                    "user_id": 1, "amount": 1, "plan_id": 1, 
                    "timestamp": 1, "status": 1
                }))
            )
            
            searches = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(self.db.db.search_logs.find({}, {
                    "user_id": 1, "search_type": 1, "query": 1,
                    "timestamp": 1, "success": 1, "credits_used": 1
                }).limit(10000))  # Limit to prevent memory issues
            )
            
            # Create CSV data
            import csv
            from io import StringIO
            
            # Users CSV
            users_csv = StringIO()
            users_writer = csv.writer(users_csv)
            users_writer.writerow(['User ID', 'Username', 'Name', 'Joined', 'Searches', 'Credits', 'Subscription', 'Referrals', 'Banned'])
            for user in users:
                users_writer.writerow([
                    user.get('user_id', ''),
                    user.get('username', ''),
                    user.get('first_name', ''),
                    user.get('joined_at', '')[:10],
                    user.get('total_searches', 0),
                    user.get('searches_remaining', 0),
                    user.get('subscription', 'None'),
                    user.get('referrals', 0),
                    'Yes' if user.get('is_banned') else 'No'
                ])
            
            users_csv.seek(0)
            
            # Payments CSV
            payments_csv = StringIO()
            payments_writer = csv.writer(payments_csv)
            payments_writer.writerow(['User ID', 'Amount', 'Plan', 'Date', 'Status'])
            for payment in payments:
                payments_writer.writerow([
                    payment.get('user_id', ''),
                    payment.get('amount', 0),
                    payment.get('plan_id', ''),
                    payment.get('timestamp', '')[:10],
                    payment.get('status', '')
                ])
            
            payments_csv.seek(0)
            
            # Prepare message
            export_text = (
                "📊 **DATA EXPORT COMPLETE**\n\n"
                f"✅ **Exported Data:**\n"
                f"├─ Users: {len(users)} records\n"
                f"├─ Payments: {len(payments)} records\n"
                f"└─ Searches: {len(searches)} records\n\n"
                "📁 **Files are ready for download.**\n"
                "Use the buttons below to download:"
            )
            
            buttons = [
                [Button.inline("📥 Download Users CSV", "export_users")],
                [Button.inline("📥 Download Payments CSV", "export_payments")],
                [Button.inline("📥 Download Searches CSV", "export_searches")],
                [Button.inline("« Admin Panel", "admin_panel")]
            ]
            
            # Store export data temporarily
            export_data_storage[event.sender_id] = {
                "users": users_csv.getvalue(),
                "payments": payments_csv.getvalue(),
                "timestamp": datetime.now().isoformat()
            }
            
            await event.edit(export_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            await event.edit("❌ Error exporting data", buttons=OneLineKeyboard.back_to_admin())
    
    async def show_user_detail(self, event, user_id: int):
        """Show detailed user information"""
        try:
            user_stats = await self.db.admin_db.get_user_stats(user_id)
            
            if not user_stats.get('user_info'):
                await event.answer("❌ User not found", alert=True)
                return
            
            user = user_stats['user_info']
            
            detail_text = f"👤 **USER DETAILS**\n"
            detail_text += "═══════════════════════\n\n"
            
            detail_text += f"📋 **Basic Information**\n"
            detail_text += f"├─ Name: {user.get('first_name', 'N/A')}\n"
            detail_text += f"├─ Username: @{user.get('username', 'N/A')}\n"
            detail_text += f"├─ User ID: `{user_id}`\n"
            detail_text += f"├─ Joined: {user.get('joined_at', 'N/A')[:10]}\n"
            detail_text += f"├─ Last Seen: {user.get('last_seen', 'N/A')[:16]}\n"
            detail_text += f"├─ Credits: {user.get('searches_remaining', 0)}\n"
            detail_text += f"├─ Total Searches: {user_stats['total_searches']}\n"
            detail_text += f"├─ Referrals: {user_stats['referrals']}\n"
            detail_text += f"└─ Banned: {'Yes' if user.get('is_banned') else 'No'}\n\n"
            
            # Subscription info
            if user.get('subscription'):
                expiry = user.get('subscription_expiry', '')
                if expiry:
                    expiry_date = datetime.fromisoformat(expiry)
                    days_left = (expiry_date - datetime.now(timezone.utc)).days
                    detail_text += f"💎 **Subscription**\n"
                    detail_text += f"├─ Plan: {user['subscription']}\n"
                    detail_text += f"└─ Expires in: {days_left} days\n\n"
            
            # Recent searches
            if user_stats.get('last_searches'):
                detail_text += "🔍 **Recent Searches**\n"
                for search in user_stats['last_searches'][:5]:
                    search_type = search.get('search_type', 'N/A')
                    cmd_name = SEARCH_COMMANDS.get(search_type, {}).get('name', search_type)
                    time_str = search.get('timestamp', '')[:16]
                    success = "✅" if search.get('success') else "❌"
                    
                    detail_text += f"{success} {cmd_name}\n"
                    detail_text += f"   ├─ Query: `{search.get('query', 'N/A')}`\n"
                    detail_text += f"   └─ Time: {time_str}\n\n"
            
            # Action buttons
            buttons = []
            if user.get('is_banned'):
                buttons.append([Button.inline("🔓 Unban User", f"confirm_unban_{user_id}")])
            else:
                buttons.append([Button.inline("🚫 Ban User", f"confirm_ban_{user_id}")])
            
            if user.get('is_admin'):
                buttons.append([Button.inline("👑 Remove Admin", f"confirm_remove_admin_{user_id}")])
            else:
                buttons.append([Button.inline("👑 Add Admin", f"confirm_add_admin_{user_id}")])
            
            buttons.append([Button.inline("🎯 Add Credits", f"admin_add_credits_user_{user_id}")])
            buttons.append([Button.inline("« User Management", "admin_users")])
            
            await event.edit(detail_text, buttons=buttons, parse_mode="md")
            
        except Exception as e:
            logger.error(f"Error showing user detail: {e}")
            await event.answer("❌ Error loading user details", alert=True)
    
    async def confirm_ban_user(self, event, user_id: int):
        """Confirm ban user"""
        try:
            success = await self.db.ban_user(user_id, "Admin action")
            if success:
                # Remove from admin cache if they were admin
                if user_id in self.admin_users:
                    self.admin_users.remove(user_id)
                
                await event.answer("✅ User banned successfully", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to ban user", alert=True)
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            await event.answer("❌ Error banning user", alert=True)
    
    async def confirm_unban_user(self, event, user_id: int):
        """Confirm unban user"""
        try:
            success = await self.db.unban_user(user_id)
            if success:
                await event.answer("✅ User unbanned successfully", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to unban user", alert=True)
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            await event.answer("❌ Error unbanning user", alert=True)
    
    async def confirm_add_admin(self, event, user_id: int):
        """Confirm add admin"""
        try:
            success = await self.db.add_admin(user_id)
            if success:
                self.admin_users.add(user_id)
                await event.answer("✅ User added as admin", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to add admin", alert=True)
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await event.answer("❌ Error adding admin", alert=True)
    
    async def confirm_remove_admin(self, event, user_id: int):
        """Confirm remove admin"""
        try:
            success = await self.db.remove_admin(user_id)
            if success:
                self.admin_users.remove(user_id)
                await event.answer("✅ Admin privileges removed", alert=True)
                await self.show_admin_panel(event)
            else:
                await event.answer("❌ Failed to remove admin", alert=True)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await event.answer("❌ Error removing admin", alert=True)

# ================== SEARCH ENGINE WITH PRIORITY MANAGEMENT ==================

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
                    "chat_id": group["entity"].id if hasattr(group["entity"], 'id') else str(group["entity"]),
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
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to:**\n• 👑 Premium Tier: Unlimited searches (30 days)\n• 🚀 Standard Tier: 30 searches (15 days)\n\nContact @darkboxesAdmin for immediate assistance."
        }
    
    async def perform_leak_search(self, query: str, user_id: int) -> Dict:
        """Perform advanced leak search (Search Anything)"""
        try:
            logger.info(f"🚀 ADVANCED LEAK SEARCH: {query} (User: {user_id})")
            
            # Get the advanced group
            advanced_group = GROUP_PRIORITIES["advanced"]
            if not advanced_group.get("entity"):
                logger.error("❌ Advanced group not resolved")
                return {
                    "success": False,
                    "error": "❌ Advanced search engine is currently unavailable. Please try again later."
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
                "chat_id": advanced_group["entity"].id if hasattr(advanced_group["entity"], 'id') else str(advanced_group["entity"]),
                "expecting_file": True,
                "file_wait_start": None,
                "priority": advanced_group["weight"],
                "expect_multiple_files": True,
                "files_received": [],
                "file_types": ["json", "txt"]
            }
            
            # Wait for response (10 seconds timeout for leak search - increased for multiple files)
            try:
                result = await asyncio.wait_for(future, timeout=10)
                
                if result["success"]:
                    logger.info(f"✅ Advanced leak search successful")
                    return result
                else:
                    logger.info(f"⚠️ No result from advanced search")
                    return {
                        "success": False,
                        "error": "❌ No information found in our advanced databases.\n\n⚠️ **Note:** For phone searches, include country code (e.g., 917204764637)\n💎 **Try our premium sources for better results.**"
                    }
                    
            except asyncio.TimeoutError:
                logger.info(f"⏱️ Timeout from advanced search")
                # Check if we received any files
                if search_id in self.active_searches:
                    search_info = self.active_searches[search_id]
                    if search_info.get("files_received"):
                        # We have some files, process them
                        return await self._finalize_leak_search(search_id, search_info)
                
                return {
                    "success": False,
                    "error": "⏱️ **ADVANCED SEARCH TIMEOUT**\n\nOur advanced engine is processing your query.\nResults will be delivered shortly if available.\n\n⚠️ **For immediate results:**\n• Use specific search types (Phone, Email, etc.)\n• Ensure phone numbers include country code\n• Contact @darkboxesAdmin for premium support"
                }
                
        except Exception as e:
            logger.error(f"❌ Error in leak search: {e}")
            return {
                "success": False,
                "error": "❌ Advanced search engine error. Please try again or use specific search types."
            }
    
    async def _finalize_leak_search(self, search_id: str, search_info: Dict) -> Dict:
        """Finalize leak search with received files"""
        try:
            files_received = search_info.get("files_received", [])
            
            if not files_received:
                return {"success": False}
            
            # Process received files
            json_data = None
            txt_data = None
            json_bytes = None
            txt_bytes = None
            
            for file in files_received:
                if file.get("file_type") == "json":
                    json_data = file.get("content", "")
                    json_bytes = file.get("raw_bytes")
                elif file.get("file_type") == "txt":
                    txt_data = file.get("content", "")
                    txt_bytes = file.get("raw_bytes")
            
            # Create summary
            has_json = json_data is not None
            has_txt = txt_data is not None
            
            summary = PremiumFormatter.format_leak_summary(
                search_info["query"],
                len(files_received),
                has_json,
                has_txt
            )
            
            # Create result
            result = {
                "success": True,
                "result": summary,
                "has_multiple_files": True,
                "files": files_received,
                "json_data": json_data,
                "txt_data": txt_data,
                "json_bytes": json_bytes,
                "txt_bytes": txt_bytes
            }
            
            # Clean up
            if search_id in self.active_searches:
                del self.active_searches[search_id]
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error finalizing leak search: {e}")
            return {"success": False}
    
    def _get_priority_groups(self, preferred_priority: str) -> List:
        """Get groups sorted by priority and performance"""
        priority_order = ["advanced", "primary", "secondary", "tertiary"]
        
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
                    chat_match = False
                    if hasattr(search_info["group"]["entity"], 'id'):
                        chat_match = event.chat_id == search_info["group"]["entity"].id
                    elif search_info.get("chat_id"):
                        chat_match = str(event.chat_id) == str(search_info["chat_id"])
                    
                    if chat_match:
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
        if message.media and hasattr(message.media, 'document'):
            logger.info(f"📁 Found document media in message")
            return await self._process_file(message, search_info)
        
        if hasattr(message, 'file') and message.file:
            logger.info(f"📁 Found file attribute in message")
            return await self._process_file(message, search_info)
        
        if message.document:
            logger.info(f"📁 Found document in message")
            return await self._process_file(message, search_info)
        
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
                logger.info(f"📄 File generation message detected in {search_info['group']['name']}")
                
                if message.reply_to:
                    logger.info(f"🔗 File message is a reply, checking replied message...")
                    try:
                        replied_msg = await message.get_reply_message()
                        if replied_msg:
                            replied_file_result = await self._check_and_process_file(replied_msg, search_info)
                            if replied_file_result:
                                logger.info(f"✅ Found file in replied message")
                                if search_id in self.active_searches:
                                    future = self.active_searches[search_id]["future"]
                                    if not future.done():
                                        future.set_result(replied_file_result)
                                    del self.active_searches[search_id]
                                return
                    except Exception as e:
                        logger.error(f"❌ Error checking replied message: {e}")
                
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
                elif hasattr(message, 'file') and message.file and hasattr(message.file, 'name'):
                    filename = message.file.name.lower()
                
                file_type = "unknown"
                if '.json' in filename:
                    file_type = "json"
                elif '.txt' in filename:
                    file_type = "txt"
                elif 'json' in filename:
                    file_type = "json"
                elif 'txt' in filename or 'text' in filename:
                    file_type = "txt"
                
                file_result["file_type"] = file_type
                search_info["files_received"].append(file_result)
                
                logger.info(f"✅ Added {file_type} file to leak search. Total files: {len(search_info['files_received'])}")
                
                # Check if we have enough files
                expected_types = SEARCH_COMMANDS.get("leak", {}).get("file_types", ["json", "txt"])
                received_types = [f.get("file_type") for f in search_info["files_received"]]
                
                # Check if we have both expected file types or have been waiting long enough
                has_all_types = all(ft in received_types for ft in expected_types)
                
                if has_all_types or len(search_info["files_received"]) >= 2:
                    # We have both files or enough files
                    logger.info(f"✅ Received sufficient files for leak search. Finalizing...")
                    
                    # Finalize the search
                    result = await self._finalize_leak_search(search_id, search_info)
                    
                    if search_id in self.active_searches:
                        future = self.active_searches[search_id]["future"]
                        if not future.done():
                            future.set_result(result)
                        del self.active_searches[search_id]
                
                return
            
            # Check for text response
            text = message.text or message.raw_text or ""
            if text and len(text.strip()) > 20:
                if TextProcessor.is_processing_message(text):
                    logger.info(f"⏳ Processing message for leak search")
                    return
                
                if TextProcessor.is_no_info_message(text):
                    logger.info(f"🚫 No info for leak search")
                    result = {"success": False}
                else:
                    result = await self._process_text(text, search_info)
                
                if search_id in self.active_searches:
                    future = self.active_searches[search_id]["future"]
                    if not future.done():
                        future.set_result(result)
                    del self.active_searches[search_id]
                
        except Exception as e:
            logger.error(f"❌ Error processing leak response: {e}")
    
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
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    content = file_bytes.decode(encoding)
                    logger.info(f"✅ Decoded with {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not content:
                logger.error("❌ Could not decode file with any encoding")
                return {"success": False}
            
            # Clean content - remove usernames and links
            cleaned_content = TextProcessor.clean_content(content, search_info["search_type"])
            
            if len(cleaned_content.strip()) < 10:
                logger.warning(f"⚠️ Cleaned content too short: {len(cleaned_content)} chars")
                # Try to get original content
                cleaned_content = content[:2000]  # Limit to 2000 chars
            
            # For leak searches, don't format the result yet
            if search_info["search_type"] == "leak":
                result = {
                    "success": True,
                    "result": None,
                    "has_file": True,
                    "content": cleaned_content,
                    "raw_bytes": file_bytes,
                    "filename": message.file.name if hasattr(message.file, 'name') else f"result_{int(time.time())}.txt"
                }
            else:
                # For non-leak searches, format the result
                formatted_result = PremiumFormatter.format_result(
                    cleaned_content,
                    search_info["search_type"],
                    search_info["query"],
                    search_info["group"]["name"]
                )
                result = {
                    "success": True,
                    "result": formatted_result,
                    "has_file": True,
                    "content": cleaned_content,
                    "raw_bytes": file_bytes,
                    "filename": message.file.name if hasattr(message.file, 'name') else f"result_{int(time.time())}.txt"
                }
            
            logger.info(f"✅ Processed file with {len(cleaned_content)} characters")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing file: {e}")
            return {"success": False}
    
    async def _process_text(self, text: str, search_info: Dict) -> Dict:
        """Process text message"""
        cleaned = TextProcessor.clean_content(text, search_info["search_type"])
        
        if len(cleaned) < 10:
            return {"success": False}
        
        # For leak searches, handle differently
        if search_info["search_type"] == "leak":
            # Check if this is a file notification
            if "file" in text.lower() or "download" in text.lower() or ".txt" in text.lower() or ".json" in text.lower():
                # This might be a file notification, wait for file
                search_info["expecting_file"] = True
                search_info["file_wait_start"] = time.time()
                logger.info(f"⏳ File notification detected, waiting for file...")
                return {"success": False, "waiting_for_file": True}
        
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
            user_info = await self.user_manager.get_user(user_id)
            username = user_info.get('username', 'N/A') if user_info else 'N/A'
            first_name = user_info.get('first_name', 'N/A') if user_info else 'N/A'
            
            admin_msg = (
                f"🚨 **FAILED SEARCH ALERT**\n\n"
                f"👤 User: {first_name} (@{username})\n"
                f"🆔 ID: `{user_id}`\n"
                f"🔍 Type: {search_type}\n"
                f"📝 Query: `{query}`\n"
                f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"💡 Use `/reply {user_id} [message]` to send result"
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
                    if file_wait_time < 25:  # Increased file wait time
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
                            # For leak searches, check if we have any files
                            if search_info.get("search_type") == "leak" and search_info.get("files_received"):
                                result = await search_engine._finalize_leak_search(search_id, search_info)
                                future.set_result(result)
                            else:
                                future.set_result({"success": False})
                        except:
                            future.set_result({"success": False})
                    logger.info(f"🧹 Cleaned expired search: {search_id}")
            
            if expired:
                logger.info(f"🧹 Cleaned {len(expired)} expired searches")
                
        except Exception as e:
            logger.error(f"❌ Error in cleanup: {e}")

# ================== WEB SERVER ==================

async def start_web_server():
    """Start web server"""
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK")
    
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server running on port {config.PORT}")
    except Exception as e:
        logger.error(f"❌ Web server failed: {e}")

# ================== GLOBAL VARIABLES ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if USE_USER_ACCOUNT
    else bot_client
)

db_manager = DatabaseManager()
search_engine = None
admin_panel = None
user_states = {}
bot_info = None
export_data_storage = {}

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
            
            # Handle referral
            if referral_code and referral_code.isdigit():
                referrer_id = int(referral_code)
                referrer = await db_manager.get_user(referrer_id)
                if referrer:
                    await db_manager.add_referral_credit(referrer_id, config.REFERRAL_REWARD)
        
        is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
        
        # Send welcome message
        welcome_text = PremiumFormatter.format_welcome(user.first_name, user_doc)
        
        # Get keyboard - ONE COMMAND PER LINE with LEAK first
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.respond(
            welcome_text,
            buttons=buttons,
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in start_handler: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^admin_'))
async def admin_callback_handler(event):
    """Handle admin panel callbacks"""
    await admin_panel.handle_admin_callback(event)

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
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
        can_search = False
        searches_remaining = user_doc.get('searches_remaining', 0)
        subscription = user_doc.get('subscription')
        subscription_expiry = user_doc.get('subscription_expiry')
        
        if subscription and subscription_expiry:
            expiry_date = datetime.fromisoformat(subscription_expiry)
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and searches_remaining <= 0:
            await event.edit(
                "🔒 **ACCESS DENIED**\n\n"
                "You have no search credits remaining.\n\n"
                "💎 **UPGRADE TO PREMIUM**\n\n"
                "💰 **BASIC TIER** - ₹99\n"
                "├─ 10 Premium Searches\n"
                "├─ Standard Databases\n"
                "├─ 7-day Access\n"
                "└─ Email Support\n\n"
                "🚀 **STANDARD TIER** - ₹249\n"
                "├─ 30 Premium Searches\n"
                "├─ All Databases\n"
                "├─ 15-day Access\n"
                "├─ Priority Support\n"
                "└─ Search History Saved\n\n"
                "👑 **PREMIUM TIER** - ₹499\n"
                "├─ Unlimited Searches (30 days)\n"
                "├─ All Premium Databases\n"
                "├─ Priority Processing\n"
                "├─ 24/7 WhatsApp Support\n"
                "└─ Extended Search History\n\n"
                "Select a plan to continue:",
                buttons=OneLineKeyboard.subscription_plans(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        # Special formatting for leak search
        if search_type == "leak":
            leak_text = (
                f"🚀 **ADVANCED OSINT TOOL - SEARCH ANYTHING**\n\n"
                f"{cmd['description']}\n\n"
                f"⚡ **ULTRA-FAST PROCESSING** (5-10 seconds)\n"
                f"💎 **Cost:** {cmd['cost']} credits\n"
                f"📁 **Returns:** JSON + TXT files\n"
                f"🌐 **Best For:** Phone numbers with country code (e.g., 917204764637)\n\n"
                f"📝 **Enter your query below:**\n"
                f"(Email, Phone with country code, Name, Document, Username, etc.)"
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

@bot_client.on(events.CallbackQuery(pattern=r'^profile$'))
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
        
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            days_left = (expiry_date - datetime.now(timezone.utc)).days
            
            if days_left > 0:
                profile_text += f"├─ Subscription: {user_doc['subscription']}\n"
                profile_text += f"├─ Status: Active ({days_left} days left)\n"
                profile_text += f"└─ Searches: Unlimited\n\n"
            else:
                profile_text += f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
                profile_text += f"└─ Subscription: Expired\n\n"
        else:
            profile_text += f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
            profile_text += f"└─ Subscription: None\n\n"
        
        # Statistics
        profile_text += f"📊 **Statistics**\n"
        profile_text += f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
        profile_text += f"├─ Successful: {user_doc.get('total_searches', 0) - user_doc.get('failed_searches', 0)}\n"
        profile_text += f"├─ Referral Code: `{user_doc.get('referral_code', 'N/A')}`\n"
        profile_text += f"├─ Referrals: {user_doc.get('referrals', 0)}\n"
        profile_text += f"└─ Referral Credits: {user_doc.get('referral_credits', 0)}\n\n"
        
        # Referral link
        referral_link = f"https://t.me/{bot_info.username}?start={user_doc.get('referral_code')}"
        profile_text += f"📢 **Referral Link**\n"
        profile_text += f"🔗 {referral_link}\n\n"
        profile_text += f"💎 **Earn 1 credit for each successful referral!**"
        
        await event.edit(
            profile_text,
            buttons=OneLineKeyboard.profile_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in profile_callback: {e}")
        await event.answer("❌ Error loading profile", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^premium$'))
async def premium_callback(event):
    """Handle premium plans callback"""
    try:
        premium_text = (
            "💎 **DARKBOXES PREMIUM PLANS**\n"
            "═══════════════════════\n\n"
            "💰 **BASIC TIER** - ₹99\n"
            "├─ 10 Premium Searches\n"
            "├─ Standard Databases\n"
            "├─ 7-day Access\n"
            "├─ Email Support\n"
            "└─ 🎯 For: New users trying the service\n\n"
            "🚀 **STANDARD TIER** - ₹249\n"
            "├─ 30 Premium Searches\n"
            "├─ All Databases\n"
            "├─ 15-day Access\n"
            "├─ Priority Support\n"
            "├─ Search History Saved\n"
            "└─ 🎯 For: Regular users needing more searches\n\n"
            "👑 **PREMIUM TIER** - ₹499\n"
            "├─ Unlimited Searches (30 days)\n"
            "├─ All Premium Databases\n"
            "├─ Priority Processing\n"
            "├─ 24/7 WhatsApp Support\n"
            "├─ Extended Search History\n"
            "└─ 🎯 For: Power users & professionals\n\n"
            "📞 **Contact @darkboxesAdmin to purchase**\n"
            "💳 **UPI ID:** `{config.UPI_ID}`\n\n"
            "🔒 **Payment Instructions:**\n"
            "1. Send payment via UPI\n"
            "2. Send screenshot to @darkboxesAdmin\n"
            "3. Your account will be upgraded within 5 minutes"
        )
        
        await event.edit(
            premium_text,
            buttons=OneLineKeyboard.subscription_plans(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in premium_callback: {e}")
        await event.answer("❌ Error loading premium plans", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^plan_(.+)$'))
async def plan_selection_callback(event):
    """Handle plan selection"""
    try:
        plan_id = event.data.decode().split('_', 1)[1]
        
        if plan_id not in SUBSCRIPTION_PLANS:
            await event.answer("❌ Invalid plan selection", alert=True)
            return
        
        plan = SUBSCRIPTION_PLANS[plan_id]
        
        plan_details = (
            f"{plan['icon']} **{plan['name']}**\n"
            f"═══════════════════════\n\n"
            f"💰 **Price:** ₹{plan['price']}\n"
            f"🔍 **Searches:** {plan['searches']}\n"
            f"📅 **Validity:** {plan['validity']}\n\n"
            f"🌟 **Features:**\n"
        )
        
        for feature in plan['features']:
            plan_details += f"• {feature}\n"
        
        plan_details += f"\n🎯 **Perfect For:** {plan['for']}\n\n"
        
        plan_details += f"📞 **To Purchase:**\n"
        plan_details += f"1. Send ₹{plan['price']} to UPI: `{config.UPI_ID}`\n"
        plan_details += f"2. Send payment screenshot to @darkboxesAdmin\n"
        plan_details += f"3. Include your User ID: `{event.sender_id}`\n"
        plan_details += f"4. Your account will be upgraded within 5 minutes\n\n"
        plan_details += f"💡 **Note:** Contact @darkboxesAdmin for bulk discounts"
        
        buttons = [
            [Button.inline("« Back to Plans", "premium")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(plan_details, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in plan_selection_callback: {e}")
        await event.answer("❌ Error loading plan details", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^referrals$'))
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
        referral_credits = user_doc.get('referral_credits', 0)
        
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
            f"├─ Credits Earned: {referral_credits}\n"
            f"└─ Active Status: ✅\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"{referral_link}\n\n"
            f"📢 **Share Message:**\n"
            f"```\n"
            f"🚀 Join DarkBoxes Intelligence System!\n"
            f"🔍 Access powerful OSINT tools\n"
            f"📊 Phone, Email, Aadhar, Vehicle searches\n"
            f"💎 Get {config.NEW_USER_CREDITS} free credits\n"
            f"🔗 Sign up: {referral_link}\n"
            f"```\n\n"
            f"💡 **Tips:** Share in groups, with friends, on social media!"
        )
        
        await event.edit(
            referrals_text,
            buttons=OneLineKeyboard.referrals_menu(),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in referrals_callback: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^support$'))
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
            f"• Bug reports\n"
            f"• Feature requests\n\n"
            f"⚠️ **Before Contacting:**\n"
            f"1. Check if you have sufficient credits\n"
            f"2. Verify your query format\n"
            f"3. Wait 30 seconds for search results\n"
            f"4. Check @darkboxesv1 for announcements\n\n"
            f"💳 **Payment Support:**\n"
            f"UPI: `{config.UPI_ID}`\n"
            f"Send screenshot after payment\n\n"
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

@bot_client.on(events.CallbackQuery(pattern=r'^my_referrals$'))
async def my_referrals_callback(event):
    """Handle my referrals callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        # Get referrals from database
        referral_code = user_doc.get('referral_code', '')
        referrals = []
        
        if referral_code:
            referrals = await asyncio.get_running_loop().run_in_executor(
                None, lambda: list(db_manager.db.users.find(
                    {"referred_by": referral_code},
                    {"user_id": 1, "username": 1, "first_name": 1, "joined_at": 1}
                ).limit(20))
            )
        
        referrals_text = (
            f"📋 **MY REFERRALS**\n"
            f"═══════════════════════\n\n"
        )
        
        if referrals:
            referrals_text += f"👥 **Total Referrals:** {len(referrals)}\n\n"
            
            for i, ref in enumerate(referrals[:10], 1):
                username = f"@{ref['username']}" if ref.get('username') else "No username"
                joined = ref.get('joined_at', '')[:10]
                
                referrals_text += (
                    f"{i}. **{ref['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{ref['user_id']}`\n"
                    f"   └─ Joined: {joined}\n\n"
                )
            
            if len(referrals) > 10:
                referrals_text += f"... and {len(referrals) - 10} more referrals\n"
        else:
            referrals_text += "📭 No referrals yet.\n\n"
            referrals_text += f"🔗 **Your Referral Code:** `{user_doc.get('referral_code', 'N/A')}`\n"
            referrals_text += "💡 Share your referral link to earn credits!"
        
        buttons = [
            [Button.inline("📢 Share Referral", "share_referral")],
            [Button.inline("« Refer & Earn", "referrals")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(referrals_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in my_referrals_callback: {e}")
        await event.answer("❌ Error loading referrals", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^share_referral$'))
async def share_referral_callback(event):
    """Handle share referral callback"""
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("❌ User not found", alert=True)
            return
        
        referral_code = user_doc.get('referral_code', '')
        referral_link = f"https://t.me/{bot_info.username}?start={referral_code}"
        
        share_text = (
            f"📢 **SHARE REFERRAL LINK**\n"
            f"═══════════════════════\n\n"
            f"🔗 **Your Referral Link:**\n"
            f"{referral_link}\n\n"
            f"📝 **Copy-Paste Message:**\n"
            f"```\n"
            f"🚀 Join DarkBoxes Intelligence System!\n\n"
            f"🔍 **Powerful OSINT Tools:**\n"
            f"• Phone Number Lookup\n"
            f"• Email Intelligence\n"
            f"• Aadhar Information\n"
            f"• Vehicle Details\n"
            f"• Telegram Analysis\n"
            f"• ADVANCED OSINT TOOL (Search Anything)\n"
            f"• And much more!\n\n"
            f"💎 **Get {config.NEW_USER_CREDITS} FREE Credits**\n"
            f"🔗 Sign up now: {referral_link}\n\n"
            f"⚡ **Features:**\n"
            f"• Fast & Accurate Results\n"
            f"• Premium Databases\n"
            f"• 24/7 Support\n"
            f"• Affordable Plans\n"
            f"```\n\n"
            f"💡 **Where to Share:**\n"
            f"• Telegram Groups\n"
            f"• Friends & Family\n"
            f"• Social Media\n"
            f"• Forums\n\n"
            f"💰 **Earn {config.REFERRAL_REWARD} credit for each successful referral!**"
        )
        
        buttons = [
            [Button.inline("« Back to Referrals", "referrals")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(share_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in share_referral_callback: {e}")
        await event.answer("❌ Error loading share referral", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^contact_admin$'))
async def contact_admin_callback(event):
    """Handle contact admin callback"""
    try:
        contact_text = (
            f"📞 **CONTACT ADMINISTRATOR**\n"
            f"═══════════════════════\n\n"
            f"👤 **Official Admin:** @darkboxesAdmin\n\n"
            f"📧 **Contact Methods:**\n"
            f"• Telegram: @darkboxesAdmin (Preferred)\n"
            f"• Email: darkboxes.admin@gmail.com\n"
            f"• Channel: @darkboxesv1\n\n"
            f"⏰ **Response Time:**\n"
            f"• General: Within 1 hour\n"
            f"• Urgent: 15-30 minutes\n"
            f"• Payment: 5-10 minutes\n\n"
            f"💳 **Payment Issues:**\n"
            f"1. Send payment to: `{config.UPI_ID}`\n"
            f"2. Take screenshot\n"
            f"3. Send to @darkboxesAdmin\n"
            f"4. Include your User ID: `{event.sender_id}`\n\n"
            f"⚠️ **Important:**\n"
            f"• Never share passwords/OTPs\n"
            f"• Official admin ONLY: @darkboxesAdmin\n"
            f"• Beware of impersonators\n"
            f"• Report suspicious accounts"
        )
        
        buttons = [
            [Button.inline("📋 Report Issue", "report_issue")],
            [Button.inline("« Support", "support")],
            [Button.inline("« Main Menu", "main_menu")]
        ]
        
        await event.edit(contact_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in contact_admin_callback: {e}")
        await event.answer("❌ Error loading contact info", alert=True)

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
        
        elif state.get("action") == "admin_search_user":
            await handle_admin_search_user(event)
        
        elif state.get("action") == "admin_broadcast":
            await handle_admin_broadcast(event)
        
        elif state.get("action") == "admin_ban":
            await handle_admin_ban(event)
        
        elif state.get("action") == "admin_management":
            await handle_admin_management(event)
        
        elif state.get("action") == "admin_add_credits":
            await handle_admin_add_credits(event)
        
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
        
        # Special handling for leak search
        if search_type == "leak":
            leak_warning = (
                "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
                f"🔍 **Query:** `{query}`\n"
                f"⚡ **Processing:** Ultra-fast (5-10 seconds)\n"
                f"📁 **Output:** JSON + TXT files\n"
                f"💎 **Cost:** 3 credits\n\n"
                f"⚠️ **Note:** For phone numbers, include country code (e.g., 917204764637)\n"
                f"⏳ Processing your advanced search..."
            )
            status = await event.respond(leak_warning, parse_mode="md")
        else:
            # Show premium processing message
            processing_text = PremiumFormatter.format_processing(search_type, query)
            status = await event.respond(processing_text, parse_mode="md")
        
        # Check access
        user_doc = await db_manager.get_user(user_id)
        can_search = False
        
        if user_doc.get('subscription') and user_doc.get('subscription_expiry'):
            expiry_date = datetime.fromisoformat(user_doc['subscription_expiry'])
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and user_doc.get('searches_remaining', 0) <= 0:
            await status.delete()
            await event.respond(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                "Upgrade to Premium for unlimited access:\n\n"
                "👑 **Premium Tier** - ₹499\n"
                "• Unlimited searches (30 days)\n"
                "• All premium databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=OneLineKeyboard.subscription_plans()
            )
            user_states.pop(user_id, None)
            return
        
        # Perform search
        result = await search_engine.perform_search(search_type, query, user_id)
        
        # Delete status
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Handle multiple files for leak search
            if search_type == "leak" and result.get("has_multiple_files"):
                # Send summary first
                await event.respond(result["result"], parse_mode="md")
                
                # Send JSON file if available
                if result.get("json_bytes"):
                    await event.respond(
                        file=result["json_bytes"],
                        caption=f"📁 **JSON DATA**\nQuery: `{query}`"
                    )
                
                # Send TXT file if available
                if result.get("txt_bytes"):
                    await event.respond(
                        file=result["txt_bytes"],
                        caption=f"📄 **TEXT REPORT**\nQuery: `{query}`"
                    )
                
                # Also send TXT content as message if it's small
                if result.get("txt_data") and len(result["txt_data"]) < 2000:
                    await event.respond(
                        f"📄 **TEXT REPORT CONTENT**\n\n{result['txt_data'][:1500]}...",
                        parse_mode="md"
                    )
            else:
                # Regular search result
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

async def handle_admin_search_user(event):
    """Handle admin user search"""
    try:
        query = event.text.strip()
        if not query:
            await event.respond("❌ Please enter a search query.")
            return
        
        users = await db_manager.admin_db.search_users(query)
        
        if not users:
            await event.respond("❌ No users found matching your query.")
            user_states.pop(event.sender_id, None)
            return
        
        if len(users) == 1:
            # Show single user detail
            user = users[0]
            await admin_panel.show_user_detail(event, user['user_id'])
        else:
            # Show list of users
            result_text = f"🔍 **SEARCH RESULTS** ({len(users)} users found)\n\n"
            
            for i, user in enumerate(users[:10], 1):
                username = f"@{user['username']}" if user.get('username') else "No username"
                joined = user.get('joined_at', '')[:10]
                searches = user.get('total_searches', 0)
                
                result_text += (
                    f"{i}. **{user['first_name']}**\n"
                    f"   ├─ {username}\n"
                    f"   ├─ ID: `{user['user_id']}`\n"
                    f"   ├─ Joined: {joined}\n"
                    f"   └─ Searches: {searches}\n\n"
                )
            
            if len(users) > 10:
                result_text += f"... and {len(users) - 10} more users\n"
            
            result_text += "\nClick on a user ID to view details:"
            
            # Create buttons with user IDs
            buttons = []
            for user in users[:5]:
                buttons.append([Button.inline(
                    f"👤 {user['first_name']} (ID: {user['user_id']})",
                    f"user_detail_{user['user_id']}"
                )])
            
            buttons.append([Button.inline("« Back to Admin", "admin_panel")])
            
            await event.respond(result_text, buttons=buttons, parse_mode="md")
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_search_user: {e}")
        await event.respond("❌ Error searching users.")

async def handle_admin_broadcast(event):
    """Handle admin broadcast"""
    try:
        message = event.text.strip()
        if not message or len(message) < 5:
            await event.respond("❌ Message too short. Minimum 5 characters required.")
            return
        
        # Confirm broadcast
        confirm_text = (
            f"📢 **BROADCAST CONFIRMATION**\n\n"
            f"**Message:**\n{message[:500]}...\n\n"
            f"**This message will be sent to all users.**\n"
            f"Estimated recipients: [Calculating...]\n\n"
            f"Are you sure you want to proceed?"
        )
        
        # Store message for confirmation
        user_states[event.sender_id] = {
            "action": "confirm_broadcast",
            "message": message
        }
        
        buttons = [
            [Button.inline("✅ Yes, Send Broadcast", "confirm_broadcast_yes")],
            [Button.inline("❌ Cancel", "admin_panel")]
        ]
        
        await event.respond(confirm_text, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_broadcast: {e}")
        await event.respond("❌ Error processing broadcast message.")

async def handle_admin_ban(event):
    """Handle admin ban user"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return
        
        user_id = int(user_input)
        user = await db_manager.get_user(user_id)
        
        if not user:
            await event.respond(f"❌ User with ID {user_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_banned'):
            # User is already banned, show unban option
            buttons = OneLineKeyboard.confirm_buttons("unban", user_id)
            await event.respond(
                f"🚫 **USER IS ALREADY BANNED**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Banned on: {user.get('banned_at', 'N/A')[:10]}\n"
                f"📝 Reason: {user.get('ban_reason', 'N/A')}\n\n"
                f"Do you want to unban this user?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            # User is not banned, show ban option
            buttons = OneLineKeyboard.confirm_buttons("ban", user_id)
            await event.respond(
                f"🚫 **BAN USER CONFIRMATION**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n"
                f"📊 Searches: {user.get('total_searches', 0)}\n\n"
                f"Are you sure you want to ban this user?",
                buttons=buttons,
                parse_mode="md"
            )
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_ban: {e}")
        await event.respond("❌ Error processing ban request.")

async def handle_admin_management(event):
    """Handle admin management"""
    try:
        user_input = event.text.strip()
        if not user_input.isdigit():
            await event.respond("❌ Please enter a valid numeric user ID.")
            return
        
        user_id = int(user_input)
        user = await db_manager.get_user(user_id)
        
        if not user:
            await event.respond(f"❌ User with ID {user_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        if user.get('is_admin'):
            # User is already admin, show remove option
            buttons = OneLineKeyboard.confirm_buttons("remove_admin", user_id)
            await event.respond(
                f"👑 **REMOVE ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n\n"
                f"This user currently has admin privileges.\n"
                f"Do you want to remove admin privileges?",
                buttons=buttons,
                parse_mode="md"
            )
        else:
            # User is not admin, show add option
            buttons = OneLineKeyboard.confirm_buttons("add_admin", user_id)
            await event.respond(
                f"👑 **ADD ADMIN PRIVILEGES**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📅 Joined: {user.get('joined_at', 'N/A')[:10]}\n"
                f"📊 Searches: {user.get('total_searches', 0)}\n\n"
                f"Are you sure you want to add this user as admin?",
                buttons=buttons,
                parse_mode="md"
            )
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_management: {e}")
        await event.respond("❌ Error processing admin management request.")

async def handle_admin_add_credits(event):
    """Handle admin add credits"""
    try:
        user_input = event.text.strip()
        parts = user_input.split()
        
        if len(parts) != 2:
            await event.respond("❌ Invalid format. Use: `user_id credits`")
            return
        
        if not parts[0].isdigit() or not parts[1].isdigit():
            await event.respond("❌ Both user ID and credits must be numbers.")
            return
        
        user_id = int(parts[0])
        credits = int(parts[1])
        
        if credits <= 0 or credits > 1000:
            await event.respond("❌ Credits must be between 1 and 1000.")
            return
        
        user = await db_manager.get_user(user_id)
        if not user:
            await event.respond(f"❌ User with ID {user_id} not found.")
            user_states.pop(event.sender_id, None)
            return
        
        # Add credits
        success = await db_manager.add_credits(user_id, credits)
        
        if success:
            await event.respond(
                f"✅ **CREDITS ADDED SUCCESSFULLY**\n\n"
                f"👤 User: {user.get('first_name', 'N/A')}\n"
                f"🆔 ID: `{user_id}`\n"
                f"🎯 Credits Added: {credits}\n"
                f"💰 New Balance: {user.get('searches_remaining', 0) + credits}\n\n"
                f"User has been notified.",
                parse_mode="md"
            )
            
            # Notify user
            await bot_client.send_message(
                user_id,
                f"🎁 **CREDITS ADDED**\n\n"
                f"Administrator has added {credits} credits to your account.\n"
                f"💰 New Balance: {user.get('searches_remaining', 0) + credits}\n\n"
                f"Thank you for using DarkBoxes!",
                parse_mode="md"
            )
        else:
            await event.respond("❌ Failed to add credits.")
        
        user_states.pop(event.sender_id, None)
        
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_add_credits: {e}")
        await event.respond("❌ Error adding credits.")

@bot_client.on(events.CallbackQuery(pattern=r'^confirm_broadcast_yes$'))
async def confirm_broadcast_handler(event):
    """Handle broadcast confirmation"""
    try:
        user_id = event.sender_id
        state = user_states.get(user_id, {})
        
        if state.get("action") != "confirm_broadcast":
            await event.answer("❌ No broadcast pending", alert=True)
            return
        
        message = state.get("message", "")
        if not message:
            await event.answer("❌ No message found", alert=True)
            return
        
        await event.edit("📢 **SENDING BROADCAST...**\n\nPlease wait...")
        
        # Get all users
        users = await asyncio.get_running_loop().run_in_executor(
            None, lambda: list(db_manager.db.users.find({}, {"user_id": 1}))
        )
        
        sent = 0
        failed = 0
        
        broadcast_text = f"📢 **ANNOUNCEMENT**\n\n{message}\n\n— DarkBoxes Administration"
        
        for user in users:
            try:
                await bot_client.send_message(
                    user["user_id"],
                    broadcast_text,
                    parse_mode="md"
                )
                sent += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                failed += 1
        
        # Clear state
        user_states.pop(user_id, None)
        
        result_text = (
            f"✅ **BROADCAST COMPLETE**\n\n"
            f"📊 **Results:**\n"
            f"├─ Total Users: {len(users)}\n"
            f"├─ Successfully Sent: {sent}\n"
            f"└─ Failed: {failed}\n\n"
            f"📝 **Message Preview:**\n{message[:200]}..."
        )
        
        await event.edit(result_text, buttons=OneLineKeyboard.back_to_admin(), parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in confirm_broadcast_handler: {e}")
        await event.answer("❌ Error sending broadcast", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^main_menu$'))
async def main_menu_callback(event):
    """Return to main menu"""
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)
        
        user_doc = await db_manager.get_user(user_id)
        is_admin = admin_panel.is_admin(user_id) if admin_panel else (user_id == config.ADMIN_USER_ID)
        
        message = (
            f"🎭 **DARK BOXES INTELLIGENCE**\n\n"
            f"📊 **ACCOUNT STATUS**\n"
            f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"├─ Total Searches: {user_doc.get('total_searches', 0)}\n"
            f"└─ Subscription: {user_doc.get('subscription', 'None')}\n\n"
            f"🛠️ **SELECT SERVICE**"
        )
        
        # Get keyboard - ONE COMMAND PER LINE with LEAK first
        buttons = OneLineKeyboard.main_menu(is_admin)
        
        await event.edit(message, buttons=buttons, parse_mode="md")
        
    except Exception as e:
        logger.error(f"❌ Error in main_menu_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^user_detail_(\d+)$'))
async def user_detail_callback(event):
    """Handle user detail callback"""
    try:
        user_id = int(event.data.decode().split('_')[-1])
        await admin_panel.show_user_detail(event, user_id)
    except Exception as e:
        logger.error(f"❌ Error in user_detail_callback: {e}")
        await event.answer("❌ Error loading user details", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^export_'))
async def export_data_callback(event):
    """Handle export data callbacks"""
    try:
        data_type = event.data.decode().split('_', 1)[1]
        user_id = event.sender_id
        
        if user_id not in export_data_storage:
            await event.answer("❌ No export data available", alert=True)
            return
        
        data = export_data_storage[user_id].get(data_type)
        if not data:
            await event.answer("❌ No data available for export", alert=True)
            return
        
        # Create file
        filename = f"darkboxes_{data_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Send file
        await event.delete()
        await bot_client.send_file(
            event.chat_id,
            bytes(data, 'utf-8'),
            filename=filename,
            caption=f"📊 **{data_type.upper()} DATA EXPORT**\n\nExported on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
    except Exception as e:
        logger.error(f"❌ Error in export_data_callback: {e}")
        await event.answer("❌ Error exporting data", alert=True)

# ================== ADMIN COMMANDS ==================

@bot_client.on(events.NewMessage(pattern=r'/admin'))
async def admin_command_handler(event):
    """Handle /admin command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        await admin_panel.show_admin_panel(event)
        
    except Exception as e:
        logger.error(f"❌ Error in admin_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/stats'))
async def stats_command_handler(event):
    """Handle /stats command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        await admin_panel.show_today_stats(event)
        
    except Exception as e:
        logger.error(f"❌ Error in stats_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/broadcast (.+)'))
async def broadcast_command_handler(event):
    """Handle /broadcast command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        message = event.pattern_match.group(1)
        user_states[user_id] = {
            "action": "confirm_broadcast",
            "message": message
        }
        
        await admin_panel.ask_for_broadcast(event)
        
    except Exception as e:
        logger.error(f"❌ Error in broadcast_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/ban (\d+)'))
async def ban_command_handler(event):
    """Handle /ban command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        target_id = int(event.pattern_match.group(1))
        user_states[user_id] = {"action": "admin_ban"}
        
        # Simulate message event
        event.text = str(target_id)
        await handle_admin_ban(event)
        
    except Exception as e:
        logger.error(f"❌ Error in ban_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/addcredits (\d+) (\d+)'))
async def add_credits_command_handler(event):
    """Handle /addcredits command"""
    try:
        user_id = event.sender_id
        
        if not admin_panel.is_admin(user_id):
            await event.respond("❌ Access denied. Admin privileges required.")
            return
        
        target_id = int(event.pattern_match.group(1))
        credits = int(event.pattern_match.group(2))
        user_states[user_id] = {"action": "admin_add_credits"}
        
        # Simulate message event
        event.text = f"{target_id} {credits}"
        await handle_admin_add_credits(event)
        
    except Exception as e:
        logger.error(f"❌ Error in add_credits_command_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)'))
async def admin_reply_handler(event):
    """Handle admin reply command"""
    try:
        if not admin_panel.is_admin(event.sender_id):
            return
        
        user_id = int(event.pattern_match.group(1))
        message = event.pattern_match.group(2)
        
        await bot_client.send_message(
            user_id,
            f"👤 **ADMINISTRATOR RESPONSE**\n\n{message}\n\n— DarkBoxes Support Team"
        )
        
        await event.respond(f"✅ Reply sent to user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Error in admin_reply_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/leak (.+)'))
async def leak_command_handler(event):
    """Handle /leak command directly"""
    try:
        user_id = event.sender_id
        query = event.pattern_match.group(1).strip()
        
        if not query:
            await event.respond("❌ Please provide a query. Example: `/leak 917204764637`")
            return
        
        # Check if user is banned
        user_doc = await db_manager.get_user(user_id)
        if user_doc and user_doc.get('is_banned'):
            await event.respond("🚫 Your account has been banned. Contact @darkboxesAdmin for assistance.")
            return
        
        if not user_doc:
            await event.respond("❌ User not found. Please use /start first.")
            return
        
        # Check access
        can_search = False
        searches_remaining = user_doc.get('searches_remaining', 0)
        subscription = user_doc.get('subscription')
        subscription_expiry = user_doc.get('subscription_expiry')
        
        if subscription and subscription_expiry:
            expiry_date = datetime.fromisoformat(subscription_expiry)
            if expiry_date > datetime.now(timezone.utc):
                can_search = True
        
        if not can_search and searches_remaining <= 0:
            await event.respond(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                "You need 3 credits for advanced search.\n\n"
                "👑 **Premium Tier** - ₹499\n"
                "• Unlimited searches (30 days)\n"
                "• All premium databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=OneLineKeyboard.subscription_plans()
            )
            return
        
        # Perform leak search
        leak_warning = (
            "🚀 **ADVANCED OSINT SEARCH INITIATED**\n\n"
            f"🔍 **Query:** `{query}`\n"
            f"⚡ **Processing:** Ultra-fast (5-10 seconds)\n"
            f"📁 **Output:** JSON + TXT files\n"
            f"💎 **Cost:** 3 credits\n\n"
            f"⚠️ **Note:** For phone numbers, include country code (e.g., 917204764637)\n"
            f"⏳ Processing your advanced search..."
        )
        status = await event.respond(leak_warning, parse_mode="md")
        
        result = await search_engine.perform_search("leak", query, user_id)
        
        try:
            await status.delete()
        except:
            pass
        
        if result["success"]:
            # Handle multiple files for leak search
            if result.get("has_multiple_files"):
                # Send summary first
                await event.respond(result["result"], parse_mode="md")
                
                # Send JSON file if available
                if result.get("json_bytes"):
                    await event.respond(
                        file=result["json_bytes"],
                        caption=f"📁 **JSON DATA**\nQuery: `{query}`"
                    )
                
                # Send TXT file if available
                if result.get("txt_bytes"):
                    await event.respond(
                        file=result["txt_bytes"],
                        caption=f"📄 **TEXT REPORT**\nQuery: `{query}`"
                    )
                
                # Also send TXT content as message if it's small
                if result.get("txt_data") and len(result["txt_data"]) < 2000:
                    await event.respond(
                        f"📄 **TEXT REPORT CONTENT**\n\n{result['txt_data'][:1500]}...",
                        parse_mode="md"
                    )
            else:
                await event.respond(result["result"], parse_mode="md")
            
            await db_manager.update_searches(user_id, "leak", query, True)
        else:
            await event.respond(result["error"], parse_mode="md")
            await db_manager.update_searches(user_id, "leak", query, False)
        
    except Exception as e:
        logger.error(f"❌ Error in leak_command_handler: {e}")
        await event.respond("❌ An error occurred during advanced search.")

@user_client.on(events.NewMessage())
async def handle_all_messages(event):
    """Handle all incoming messages for search responses"""
    try:
        await search_engine.handle_incoming_message(event)
    except Exception as e:
        pass

# ================== MAIN FUNCTION ==================

async def main():
    """Main function"""
    global search_engine, admin_panel, bot_info
    
    try:
        logger.info("🚀 Starting DarkBoxes Intelligence System...")
        
        # Start bot client
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot: @{bot_info.username}")
        
        # Start user client if configured
        if USE_USER_ACCOUNT:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        else:
            logger.info("ℹ️ Using bot client for all operations")
        
        # Connect to database
        if not await db_manager.connect():
            logger.error("❌ Database connection failed")
            return
        
        # Initialize admin panel
        admin_panel = AdminPanelHandler(db_manager, bot_client)
        
        # Initialize search engine
        search_engine = SearchEngine(db_manager, db_manager)
        
        # Resolve groups - LEAK GROUP FIRST
        logger.info("📡 Connecting to intelligence networks...")
        for group_name, group_data in GROUP_PRIORITIES.items():
            if group_data["enabled"]:
                try:
                    group_data["entity"] = await user_client.get_entity(group_data["identifier"])
                    logger.info(f"✅ Connected: {group_data['name']}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed: {group_data['name']} - {e}")
        
        # Start background tasks
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info("=" * 60)
        
        # Keep the bot running
        await bot_client.run_until_disconnected()
        
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"💀 Fatal error: {e}")
        logger.error(traceback.format_exc())
    finally:
        # Clean shutdown
        try:
            await bot_client.disconnect()
            if USE_USER_ACCOUNT:
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except:
            pass

if __name__ == "__main__":
    # Set event loop policy for Windows if needed
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run the bot
    asyncio.run(main())
