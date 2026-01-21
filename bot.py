"""
DarkBoxes Intelligence System - Premium Edition
Advanced information retrieval with premium interface
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
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# Third-party imports
try:
    from aiohttp import web
    from telethon import TelegramClient, events, Button
    from telethon.tl.types import PeerChannel, PeerUser, Channel, User, MessageMediaDocument
    from telethon.tl.functions.channels import GetParticipantRequest
    from pymongo import MongoClient
except ImportError as e:
    print(f"Missing required dependency: {e}")
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
    MONGODB_DBNAME: str = "darkboxes_db"
    
    # Timeouts and limits
    GROUP_TIMEOUT: int = int(os.getenv("GROUP_TIMEOUT", "45"))
    FETCH_WAIT_TIME: int = int(os.getenv("FETCH_WAIT_TIME", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
    
    # Credits and rewards
    NEW_USER_CREDITS: int = int(os.getenv("NEW_USER_CREDITS", "3"))
    REFERRAL_REWARD: int = int(os.getenv("REFERRAL_REWARD", "2"))
    
    # Payment
    UPI_ID: str = os.getenv("UPI_ID", "darkboxes@ybl")
    ADMIN_CONTACT: str = "@darkboxesAdmin"
    
    # UI Settings
    PRIMARY_COLOR: str = "#2E86C1"
    ACCENT_COLOR: str = "#E74C3C"

config = BotConfig()

# ================== GROUP PRIORITY MANAGEMENT ==================

GROUP_PRIORITIES = {
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003596998816,  # Your primary group
        "timeout": 30,
        "weight": 10,  # Highest priority
        "enabled": True,
        "entity": None
    },
    "secondary": {
        "name": "🌐 Standard Database",
        "identifier": "IntelXGroup",  # Your secondary group
        "timeout": 35,
        "weight": 7,
        "enabled": True,
        "entity": None
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": "nex_chats",  # Your backup group
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
        "name": "🔰 Basic Plan",
        "price": 100,
        "searches": 5,
        "validity": "7 days",
        "features": ["5 premium searches", "Standard data sources", "7-day access"],
        "icon": "🔰",
        "color": "#27AE60"
    },
    "standard": {
        "name": "⭐ Standard Plan",
        "price": 200,
        "searches": 10,
        "validity": "7 days",
        "features": ["10 premium searches", "Extended data sources", "Priority processing"],
        "icon": "⭐",
        "color": "#F39C12"
    },
    "premium": {
        "name": "👑 Premium Plan",
        "price": 500,
        "searches": "∞",
        "validity": "7 days",
        "features": ["Unlimited searches", "All data sources", "Priority processing", "24/7 support"],
        "icon": "👑",
        "color": "#9B59B6"
    },
    "enterprise": {
        "name": "🚀 Enterprise Plan",
        "price": 800,
        "searches": "∞",
        "validity": "30 days",
        "features": ["Unlimited searches", "All premium sources", "Highest priority", "Dedicated support", "API access"],
        "icon": "🚀",
        "color": "#E74C3C"
    }
}

# ================== SEARCH COMMANDS WITH PRIORITY ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "description": "📊 **Complete Mobile Intelligence**\n\n🔸 **Input:** 10-digit Indian mobile number\n🔸 **Returns:** Full name • Father's name • Aadhar ID • Complete address • Alternate numbers\n🔸 **Sources:** Government databases • Telecom records • Public directories\n🔸 **Confidence:** 98% accurate",
        "commands": ["/num", "/phone", "/mobile"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1,
        "priority": "primary",  # Which group to try first
        "icon": "📱",
        "category": "identity"
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Network",
        "description": "🏠 **Complete Family Analysis**\n\n🔸 **Input:** 12-digit Aadhar number\n🔸 **Returns:** All family members • Names • Relations • Ages • Addresses\n🔸 **Sources:** UIDAI database • Family registration • Government records\n🔸 **Depth:** 3-level relationship mapping",
        "commands": ["/familyinfo", "/family"],
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
        "commands": ["/aadhar", "/adh", "/aadhaar"],
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
        "commands": ["/vehicle", "/vnum", "/car"],
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
        "commands": ["/upiinfo", "/upi"],
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
    }
}

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
        welcome += "• 🔓 Government Database Access\n"
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

# ================== SEARCH ENGINE WITH PRIORITY MANAGEMENT ==================

class SearchEngine:
    def __init__(self, db_manager, user_manager):
        self.db = db_manager
        self.user_manager = user_manager
        self.active_searches = {}
        self.waiting_for_files = {}
        self.group_performance = {}  # Track group success rates
    
    async def perform_search(self, search_type: str, query: str, user_id: int) -> Dict:
        """Perform cascading search with priority management"""
        logger.info(f"🚀 Starting {search_type} search: {query} (User: {user_id})")
        
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
            "error": f"🔍 **INTELLIGENCE GATHERING FAILED**\n\nQuery: `{query}`\n\n⚠️ **Premium Notice:** Your query has been escalated to our premium database.\nAdministrator will review and respond within 24 hours.\n\n💎 **For instant access, upgrade to:**\n• 👑 Premium Plan: Unlimited searches (7 days)\n• 🚀 Enterprise Plan: Unlimited searches (30 days)\n\nContact @darkboxesAdmin for immediate assistance."
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
            logger.error(f"Error handling incoming message: {e}")

# ================== PREMIUM KEYBOARD BUILDER ==================

class PremiumKeyboard:
    @staticmethod
    def main_menu(is_admin: bool = False) -> List[List[Button]]:
        """Build premium main menu"""
        # Top row - Most used services
        top_services = ["phone", "vehicle", "aadhar", "telegram"]
        top_row = []
        for service in top_services:
            if service in SEARCH_COMMANDS:
                cmd = SEARCH_COMMANDS[service]
                top_row.append(Button.inline(f"{cmd['icon']}", f"search_{service}"))
        
        if top_row:
            # Create single row with all buttons
            return [top_row]
        
        return [[Button.inline("📱 Phone", "search_phone"), Button.inline("🚗 Vehicle", "search_vehicle")]]
    
    @staticmethod
    def services_menu() -> List[List[Button]]:
        """All services in organized layout"""
        buttons = []
        
        # Identity Services
        identity_services = [k for k, v in SEARCH_COMMANDS.items() if v.get("category") == "identity"]
        row = []
        for service in identity_services[:4]:  # First 4 identity services
            cmd = SEARCH_COMMANDS[service]
            row.append(Button.inline(cmd["icon"], f"search_{service}"))
        if row:
            buttons.append(row)
        
        # Financial Services
        finance_services = [k for k, v in SEARCH_COMMANDS.items() if v.get("category") == "finance"]
        row = []
        for service in finance_services[:4]:
            cmd = SEARCH_COMMANDS[service]
            row.append(Button.inline(cmd["icon"], f"search_{service}"))
        if row:
            buttons.append(row)
        
        # Digital Services
        digital_services = [k for k, v in SEARCH_COMMANDS.items() if v.get("category") in ["digital", "social"]]
        row = []
        for service in digital_services[:4]:
            cmd = SEARCH_COMMANDS[service]
            row.append(Button.inline(cmd["icon"], f"search_{service}"))
        if row:
            buttons.append(row)
        
        # Action Buttons
        buttons.append([
            Button.inline("👤 Profile", "profile"),
            Button.inline("💎 Premium", "premium"),
            Button.inline("📊 Referral", "referrals")
        ])
        
        buttons.append([
            Button.inline("🔄 Refresh", "main_menu"),
            Button.inline("🆘 Support", "support")
        ])
        
        return buttons
    
    @staticmethod
    def search_type_menu(search_type: str) -> List[List[Button]]:
        """Menu for specific search type"""
        cmd = SEARCH_COMMANDS.get(search_type, {})
        return [
            [Button.inline(f"{cmd.get('icon', '🔍')} {cmd.get('name', 'Search')}", f"info_{search_type}")],
            [Button.inline("« Back to Services", "services")]
        ]
    
    @staticmethod
    def subscription_plans() -> List[List[Button]]:
        """Premium subscription plans"""
        buttons = []
        
        for plan_id, plan in SUBSCRIPTION_PLANS.items():
            label = f"{plan['icon']} {plan['name']} - ₹{plan['price']}"
            buttons.append([Button.inline(label, f"buy_{plan_id}")])
        
        buttons.append([Button.inline("« Back to Menu", "main_menu")])
        return buttons
    
    @staticmethod
    def cancel_button() -> List[List[Button]]:
        """Cancel button"""
        return [[Button.inline("❌ Cancel", "main_menu")]]
    
    @staticmethod
    def payment_buttons(plan_id: str) -> List[List[Button]]:
        """Payment confirmation buttons"""
        return [
            [Button.inline("✅ Payment Done", f"confirm_{plan_id}")],
            [Button.inline("❌ Cancel", "premium")]
        ]
    
    @staticmethod
    def admin_controls() -> List[List[Button]]:
        """Admin control panel"""
        return [
            [Button.inline("📊 Statistics", "admin_stats"), Button.inline("📢 Broadcast", "admin_broadcast")],
            [Button.inline("⚙️ Settings", "admin_settings"), Button.inline("👥 Users", "admin_users")],
            [Button.inline("« Main Menu", "main_menu")]
        ]

# ================== ENHANCED EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    """Premium start handler"""
    try:
        user = await event.get_sender()
        user_id = user.id
        referral_code = event.pattern_match.group(1)
        
        # Get or create user
        user_doc = await db_manager.get_user(user_id)
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral_code)
            user_doc = await db_manager.get_user(user_id)
            
            # Handle referral
            if referral_code and referral_code.isdigit():
                referrer_id = int(referral_code)
                referrer = await db_manager.get_user(referrer_id)
                if referrer:
                    await db_manager.add_referral_credit(referrer_id, config.REFERRAL_REWARD)
        
        is_admin = user_id == config.ADMIN_USER_ID
        
        # Send welcome message
        welcome_text = PremiumFormatter.format_welcome(user.first_name, user_doc)
        
        # Use single row inline keyboard
        await event.respond(
            welcome_text,
            buttons=PremiumKeyboard.main_menu(is_admin),
            parse_mode="md"
        )
        
    except Exception as e:
        logger.error(f"Error in start_handler: {e}")

@bot_client.on(events.CallbackQuery(pattern='^services$'))
async def services_menu_callback(event):
    """Show all services menu"""
    try:
        await event.edit(
            "🛠️ **INTELLIGENCE SERVICES**\n\n"
            "Select a service category:\n\n"
            "🔍 **Identity Services**\n"
            "📱 Phone • 👨‍👩‍👧‍👦 Family • 🆔 Aadhar\n\n"
            "💰 **Financial Services**\n"
            "💳 UPI • 🏢 GST • 🏦 Banking\n\n"
            "🌐 **Digital Services**\n"
            "📲 Telegram • 📸 Instagram • 📧 Email\n\n"
            "Select service:",
            buttons=PremiumKeyboard.services_menu(),
            parse_mode="md"
        )
    except Exception as e:
        logger.error(f"Error in services_menu_callback: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    """Handle search type selection"""
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid selection", alert=True)
            return
        
        user_doc = await db_manager.get_user(user_id)
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
                "🔰 **Basic Plan** - ₹100\n"
                "├─ 5 Premium Searches\n"
                "├─ Standard Databases\n"
                "└─ 7-day Access\n\n"
                "⭐ **Standard Plan** - ₹200\n"
                "├─ 10 Premium Searches\n"
                "├─ Extended Databases\n"
                "└─ Priority Processing\n\n"
                "👑 **Premium Plan** - ₹500\n"
                "├─ Unlimited Searches\n"
                "├─ All Databases\n"
                "├─ Priority Processing\n"
                "└─ 24/7 Support\n\n"
                "🚀 **Enterprise Plan** - ₹800\n"
                "├─ Unlimited Searches\n"
                "├─ Premium Sources\n"
                "├─ Highest Priority\n"
                "├─ Dedicated Support\n"
                "└─ 30-day Access\n\n"
                "Select a plan to continue:",
                buttons=PremiumKeyboard.subscription_plans(),
                parse_mode="md"
            )
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        await event.edit(
            f"{cmd['icon']} **{cmd['name']}**\n\n"
            f"{cmd['description']}\n\n"
            f"⚡ **Cost:** {cmd['cost']} credit{'s' if cmd['cost'] > 1 else ''}\n"
            f"📝 **Example:** `{cmd['example']}`\n\n"
            f"Enter your query below:",
            buttons=PremiumKeyboard.cancel_button(),
            parse_mode="md"
        )
        
        user_states[user_id] = {"action": "search", "type": search_type}
        
    except Exception as e:
        logger.error(f"Error in search_callback: {e}")
        await event.answer("❌ Error", alert=True)

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def query_handler(event):
    """Handle search queries with premium UI"""
    try:
        user_id = event.sender_id
        
        if user_id not in user_states:
            return
        
        state = user_states[user_id]
        if state.get("action") != "search":
            return
        
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
                "💎 **Premium Plan** - ₹500\n"
                "• Unlimited searches (7 days)\n"
                "• All databases\n"
                "• Priority processing\n\n"
                "Contact @darkboxesAdmin for assistance.",
                buttons=PremiumKeyboard.subscription_plans()
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
            await event.respond(result["result"], parse_mode="md")
            await db_manager.update_searches(user_id)
        else:
            await event.respond(result["error"], parse_mode="md")
        
        # Clear state
        user_states.pop(user_id, None)
        
    except Exception as e:
        logger.error(f"Error in query_handler: {e}")
        await event.respond("❌ An error occurred during processing.")

# ================== ADMIN COMMANDS FOR GROUP MANAGEMENT ==================

@bot_client.on(events.NewMessage(pattern=r'/priority (\w+) (\w+)'))
async def set_priority_handler(event):
    """Set group priority for specific search type"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        search_type = event.pattern_match.group(1)
        priority = event.pattern_match.group(2)
        
        if search_type not in SEARCH_COMMANDS:
            await event.respond("❌ Invalid search type")
            return
        
        if priority not in ["primary", "secondary", "tertiary"]:
            await event.respond("❌ Invalid priority. Use: primary, secondary, tertiary")
            return
        
        SEARCH_COMMANDS[search_type]["priority"] = priority
        await event.respond(f"✅ Set {search_type} priority to {priority}")
        
    except Exception as e:
        logger.error(f"Error in set_priority_handler: {e}")

@bot_client.on(events.NewMessage(pattern=r'/groupstats'))
async def group_stats_handler(event):
    """Show group performance statistics"""
    try:
        if event.sender_id != config.ADMIN_USER_ID:
            return
        
        if not hasattr(search_engine, 'group_performance'):
            await event.respond("No group statistics available")
            return
        
        stats_text = "📊 **GROUP PERFORMANCE STATISTICS**\n\n"
        
        for group_name, performance in search_engine.group_performance.items():
            total = performance["total"]
            success = performance["success"]
            success_rate = (success / total * 100) if total > 0 else 0
            
            stats_text += f"**{group_name}**\n"
            stats_text += f"├─ Total Requests: {total}\n"
            stats_text += f"├─ Success: {success}\n"
            stats_text += f"├─ Success Rate: {success_rate:.1f}%\n"
            stats_text += f"└─ Current Priority: {performance.get('weight', 'N/A')}\n\n"
        
        await event.respond(stats_text, parse_mode="md")
        
    except Exception as e:
        logger.error(f"Error in group_stats_handler: {e}")

# ================== REST OF THE CODE (DatabaseManager, TextProcessor, etc.) ==================
# (Keep the DatabaseManager, TextProcessor, and other classes from previous code)
# Just update the imports and ensure they work with new structure

# Initialize
bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = (
    TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH)
    if config.USER_API_ID and config.USER_API_HASH and config.USER_PHONE
    else bot_client
)

db_manager = DatabaseManager()
search_engine = None
user_states = {}
bot_info = None

async def main():
    """Main function"""
    global search_engine, bot_info
    
    try:
        logger.info("🚀 Starting DarkBoxes Intelligence System...")
        
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot: @{bot_info.username}")
        
        if user_client != bot_client:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        
        if not await db_manager.connect():
            logger.error("❌ DB connection failed")
            return
        
        search_engine = SearchEngine(db_manager, db_manager)
        
        logger.info("📡 Connecting to intelligence networks...")
        for group_name, group_data in GROUP_PRIORITIES.items():
            if group_data["enabled"]:
                try:
                    group_data["entity"] = await user_client.get_entity(group_data["identifier"])
                    logger.info(f"✅ Connected: {group_data['name']}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed: {group_data['name']} - {e}")
        
        asyncio.create_task(cleanup_expired_searches())
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 60)
        logger.info("🎭 DARK BOXES INTELLIGENCE SYSTEM - OPERATIONAL")
        logger.info("=" * 60)
        
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except Exception as e:
        logger.error(f"💀 Fatal error: {e}")
    finally:
        try:
            await bot_client.disconnect()
            if user_client != bot_client:
                await user_client.disconnect()
            if db_manager.client:
                db_manager.client.close()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(main())
