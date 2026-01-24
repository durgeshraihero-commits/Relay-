"""
DarkBoxes Intelligence System - Premium Edition
Fixed and Working Version
"""

import os
import sys
import re
import json
import time
import logging
import asyncio
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from io import BytesIO

# Third-party imports
try:
    from aiohttp import web
    from telethon import TelegramClient, events, Button
    from telethon.tl.types import MessageMediaDocument
    from pymongo import MongoClient
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install telethon aiohttp pymongo")
    sys.exit(1)

# ================== CONFIGURATION ==================

@dataclass
class BotConfig:
    PORT: int = int(os.getenv("PORT", "10000"))
    BOT_API_ID: int = int(os.getenv("API_ID", "0"))
    BOT_API_HASH: str = os.getenv("API_HASH", "").strip()
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    BOT_SESSION_FILE: str = "bot_session.session"
    USER_API_ID: int = int(os.getenv("USER_API_ID", "0"))
    USER_API_HASH: str = os.getenv("API_HASH", "").strip()
    USER_PHONE: str = os.getenv("USER_PHONE", "").strip()
    USER_SESSION_FILE: str = "relay_session.session"
    ADMIN_USER_ID: int = int(os.getenv("ADMIN_USER_ID", "0"))
    MANDATORY_CHANNEL: str = os.getenv("MANDATORY_CHANNEL", "darkboxesv1")
    MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DBNAME: str = "darkboxes_db"
    GROUP_TIMEOUT: int = 45
    MAX_FILE_SIZE_MB: int = 20
    NEW_USER_CREDITS: int = 1
    REFERRAL_REWARD: int = 1
    UPI_ID: str = os.getenv("UPI_ID", "durgeshraihero@oksbi")

config = BotConfig()

# ================== LOGGING ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("DarkBoxes")

# ================== VALIDATION ==================

def validate_config() -> bool:
    required = [
        (config.BOT_API_ID, "BOT_API_ID"),
        (config.BOT_API_HASH, "BOT_API_HASH"),
        (config.BOT_TOKEN, "BOT_TOKEN"),
        (config.ADMIN_USER_ID, "ADMIN_USER_ID"),
        (config.MONGODB_URI, "MONGODB_URI"),
    ]
    for val, name in required:
        if not val:
            logger.error(f"Missing: {name}")
            return False
    return True

if not validate_config():
    sys.exit(1)

USE_USER_ACCOUNT = config.USER_API_ID != 0 and config.USER_API_HASH and config.USER_PHONE

# ================== GROUPS ==================

GROUP_CONFIG = {
    "primary": {
        "name": "⚡ Premium Database",
        "identifier": -1003596998816,
        "timeout": 30,
        "enabled": True,
        "entity": None
    },
    "secondary": {
        "name": "🌐 IntelX Network", 
        "identifier": "IntelXGroup",
        "timeout": 35,
        "enabled": True,
        "entity": None
    },
    "tertiary": {
        "name": "🔍 Basic Database",
        "identifier": "nex_chats",
        "timeout": 40,
        "enabled": True,
        "entity": None
    },
    "advanced": {
        "name": "🚀 Advanced OSINT",
        "identifier": "IntelXGroup",
        "timeout": 30,
        "enabled": True,
        "entity": None,
        "leak_command": "/leak"
    }
}

# ================== SEARCH COMMANDS ==================

SEARCH_COMMANDS = {
    "phone": {
        "name": "📱 Phone Intelligence",
        "commands": ["/num"],
        "example": "9876543210",
        "validation": r"^\d{10,15}$",
        "cost": 1,
        "icon": "📱",
        "groups": ["primary", "secondary", "tertiary"]
    },
    "family": {
        "name": "👨‍👩‍👧‍👦 Family Network",
        "commands": ["/familyinfo"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 1,
        "icon": "👨‍👩‍👧‍👦",
        "groups": ["primary", "secondary"]
    },
    "aadhar": {
        "name": "🆔 Aadhar Lookup",
        "commands": ["/aadhar"],
        "example": "123456789012",
        "validation": r"^\d{12}$",
        "cost": 2,
        "icon": "🆔",
        "groups": ["primary", "secondary", "tertiary"]
    },
    "vehicle": {
        "name": "🚗 Vehicle Intelligence",
        "commands": ["/vehicle"],
        "example": "UP53CZ3391",
        "validation": r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$",
        "cost": 2,
        "icon": "🚗",
        "groups": ["primary", "secondary"]
    },
    "upi": {
        "name": "💳 UPI Lookup",
        "commands": ["/upiinfo"],
        "example": "username@paytm",
        "validation": r"^[\w\.-]+@[\w\.-]+$",
        "cost": 1,
        "icon": "💳",
        "groups": ["primary", "secondary"]
    },
    "email": {
        "name": "📧 Email Intelligence",
        "commands": ["/email"],
        "example": "user@example.com",
        "validation": r"^[\w\.-]+@[\w\.-]+\.\w+$",
        "cost": 1,
        "icon": "📧",
        "groups": ["primary", "secondary"]
    },
    "telegram": {
        "name": "📲 Telegram Lookup",
        "commands": ["/tg"],
        "example": "@username",
        "validation": r"^(@?\w{5,32}|\d{10})$",
        "cost": 2,
        "icon": "📲",
        "groups": ["primary", "secondary"]
    },
    "imei": {
        "name": "📱 IMEI Lookup",
        "commands": ["/imei"],
        "example": "123456789012345",
        "validation": r"^\d{15}$",
        "cost": 2,
        "icon": "📱",
        "groups": ["primary", "secondary"]
    },
    "gst": {
        "name": "🏢 GST Lookup",
        "commands": ["/gst"],
        "example": "29ABCDE1234F1Z5",
        "validation": r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$",
        "cost": 1,
        "icon": "🏢",
        "groups": ["primary", "secondary"]
    },
    "insta": {
        "name": "📸 Instagram Lookup",
        "commands": ["/insta"],
        "example": "username",
        "validation": r"^[a-zA-Z0-9_.]{1,30}$",
        "cost": 1,
        "icon": "📸",
        "groups": ["primary", "secondary"]
    },
    "ip": {
        "name": "🌍 IP Lookup",
        "commands": ["/ip"],
        "example": "8.8.8.8",
        "validation": r"^(\d{1,3}\.){3}\d{1,3}$",
        "cost": 1,
        "icon": "🌍",
        "groups": ["primary", "secondary"]
    },
    "ifsc": {
        "name": "🏦 IFSC Lookup",
        "commands": ["/ifsc"],
        "example": "SBIN0001707",
        "validation": r"^[A-Z]{4}0[A-Z0-9]{6}$",
        "cost": 1,
        "icon": "🏦",
        "groups": ["primary", "secondary"]
    },
    "leak": {
        "name": "🚀 Advanced OSINT",
        "commands": ["/leak"],
        "example": "917204764637",
        "validation": r"^.+$",
        "cost": 3,
        "icon": "🚀",
        "groups": ["advanced"]
    }
}

SUBSCRIPTION_PLANS = {
    "basic": {"name": "💰 Basic", "price": 99, "searches": 10, "days": 7},
    "standard": {"name": "🚀 Standard", "price": 249, "searches": 30, "days": 15},
    "premium": {"name": "👑 Premium", "price": 499, "searches": "Unlimited", "days": 30}
}

# ================== GLOBALS ==================

bot_client = TelegramClient(config.BOT_SESSION_FILE, config.BOT_API_ID, config.BOT_API_HASH)
user_client = TelegramClient(config.USER_SESSION_FILE, config.USER_API_ID, config.USER_API_HASH) if USE_USER_ACCOUNT else bot_client

db_manager = None
bot_info = None
user_states = {}

# Active searches: {search_id: {user_id, chat_id, query, search_type, message_ids, start_time, results_sent}}
active_searches = {}

# ================== DATABASE ==================

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
    
    async def connect(self) -> bool:
        try:
            self.client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            self.client.server_info()
            self.db = self.client[config.MONGODB_DBNAME]
            self.db.users.create_index([("user_id", 1)], unique=True)
            logger.info("✅ MongoDB connected")
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB failed: {e}")
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        try:
            return self.db.users.find_one({"user_id": user_id})
        except:
            return None
    
    async def create_user(self, user_id: int, username: str, first_name: str, referral_code: str = None):
        try:
            user_doc = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "joined_at": datetime.now(timezone.utc).isoformat(),
                "searches_remaining": config.NEW_USER_CREDITS,
                "total_searches": 0,
                "referral_code": str(user_id)[-6:],
                "referrals": 0,
                "subscription": None,
                "subscription_expiry": None,
                "is_banned": False,
                "is_admin": False
            }
            if referral_code:
                user_doc["referred_by"] = referral_code
            
            self.db.users.update_one(
                {"user_id": user_id},
                {"$setOnInsert": user_doc},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    async def can_search(self, user_id: int, cost: int = 1) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        if user.get('is_banned'):
            return False
        
        # Check subscription
        if user.get('subscription') and user.get('subscription_expiry'):
            try:
                expiry = datetime.fromisoformat(user['subscription_expiry'])
                if expiry > datetime.now(timezone.utc):
                    return True
            except:
                pass
        
        return user.get('searches_remaining', 0) >= cost
    
    async def deduct_credits(self, user_id: int, cost: int = 1):
        try:
            user = await self.get_user(user_id)
            if user.get('subscription') and user.get('subscription_expiry'):
                try:
                    expiry = datetime.fromisoformat(user['subscription_expiry'])
                    if expiry > datetime.now(timezone.utc):
                        self.db.users.update_one(
                            {"user_id": user_id},
                            {"$inc": {"total_searches": 1}}
                        )
                        return True
                except:
                    pass
            
            self.db.users.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": -cost, "total_searches": 1}}
            )
            return True
        except:
            return False
    
    async def add_credits(self, user_id: int, credits: int):
        try:
            self.db.users.update_one(
                {"user_id": user_id},
                {"$inc": {"searches_remaining": credits}}
            )
            return True
        except:
            return False
    
    async def add_referral(self, referrer_code: str):
        try:
            self.db.users.update_one(
                {"referral_code": referrer_code},
                {"$inc": {"referrals": 1, "searches_remaining": config.REFERRAL_REWARD}}
            )
        except:
            pass

# ================== HELPER FUNCTIONS ==================

def clean_text(text: str) -> str:
    """Remove usernames, links, and promotional content"""
    if not text:
        return ""
    
    patterns = [
        r'https?://\S+',
        r't\.me/\S+',
        r'@\w+',
        r'tg://\S+',
        r'Powered by.*',
        r'Developed by.*',
        r'Join.*channel.*',
        r'Subscribe.*',
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def is_valid_result(text: str) -> bool:
    """Check if text is a valid result (not processing/error message)"""
    if not text or len(text) < 50:
        return False
    
    skip_keywords = [
        'processing', 'please wait', 'fetching', 'loading',
        'no info', 'not found', 'no data', 'invalid'
    ]
    
    text_lower = text.lower()
    for kw in skip_keywords:
        if kw in text_lower and len(text) < 200:
            return False
    
    return True

def split_message(text: str, max_len: int = 4000) -> List[str]:
    """Split long messages"""
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks

def get_search_id(user_id: int, query: str) -> str:
    return f"{user_id}_{hash(query)}_{int(time.time())}"

# ================== KEYBOARDS ==================

def main_menu_keyboard(is_admin: bool = False) -> List[List[Button]]:
    buttons = []
    for key, cmd in SEARCH_COMMANDS.items():
        if key == "leak":
            buttons.append([Button.inline("🚀 ADVANCED OSINT", f"search_{key}")])
        else:
            buttons.append([Button.inline(f"{cmd['icon']} {cmd['name'].split()[1]}", f"search_{key}")])
    
    buttons.append([Button.inline("👤 Profile", "profile")])
    buttons.append([Button.inline("💎 Premium", "premium")])
    buttons.append([Button.inline("📊 Referrals", "referrals")])
    buttons.append([Button.inline("🆘 Support", "support")])
    
    if is_admin:
        buttons.append([Button.inline("⚙️ Admin", "admin_panel")])
    
    return buttons

def back_button() -> List[List[Button]]:
    return [[Button.inline("« Back", "main_menu")]]

# ================== SEARCH ENGINE ==================

class SearchEngine:
    def __init__(self):
        self.pending_searches = {}  # {group_chat_id: {msg_id: search_info}}
    
    async def perform_search(self, search_type: str, query: str, user_id: int, user_chat_id: int) -> Dict:
        """Perform search and return results"""
        cmd = SEARCH_COMMANDS.get(search_type)
        if not cmd:
            return {"success": False, "error": "Invalid search type"}
        
        groups_to_search = cmd.get("groups", ["primary"])
        command = cmd["commands"][0]
        
        if search_type == "leak":
            command = GROUP_CONFIG.get("advanced", {}).get("leak_command", "/leak")
        
        all_results = {
            "texts": [],
            "files": []
        }
        
        search_id = get_search_id(user_id, query)
        
        # Search each group
        for group_key in groups_to_search:
            group = GROUP_CONFIG.get(group_key)
            if not group or not group.get("enabled") or not group.get("entity"):
                continue
            
            try:
                logger.info(f"📤 Sending to {group['name']}: {command} {query}")
                
                # Send search command
                sent_msg = await user_client.send_message(
                    group["entity"],
                    f"{command} {query}"
                )
                
                # Store search info
                group_chat_id = group["entity"].id if hasattr(group["entity"], 'id') else 0
                
                if group_chat_id not in self.pending_searches:
                    self.pending_searches[group_chat_id] = {}
                
                self.pending_searches[group_chat_id][sent_msg.id] = {
                    "search_id": search_id,
                    "user_id": user_id,
                    "user_chat_id": user_chat_id,
                    "query": query,
                    "search_type": search_type,
                    "group_name": group["name"],
                    "start_time": time.time(),
                    "collected_texts": [],
                    "collected_files": []
                }
                
                # Wait for responses
                timeout = group.get("timeout", 30)
                await asyncio.sleep(timeout)
                
                # Collect results
                if group_chat_id in self.pending_searches and sent_msg.id in self.pending_searches[group_chat_id]:
                    search_info = self.pending_searches[group_chat_id].pop(sent_msg.id, {})
                    
                    if search_info.get("collected_texts"):
                        all_results["texts"].extend(search_info["collected_texts"])
                    if search_info.get("collected_files"):
                        all_results["files"].extend(search_info["collected_files"])
                
            except Exception as e:
                logger.error(f"❌ Error searching {group.get('name', group_key)}: {e}")
                continue
        
        # Check if we got any results
        if all_results["texts"] or all_results["files"]:
            return {"success": True, "results": all_results}
        else:
            return {"success": False, "error": "No results found from any database."}
    
    async def handle_group_message(self, event):
        """Handle incoming messages from groups"""
        try:
            chat_id = event.chat_id
            message = event.message
            
            if chat_id not in self.pending_searches:
                return
            
            # Check if this is a reply to any of our searches
            reply_to_id = None
            if message.reply_to:
                reply_to_id = message.reply_to.reply_to_msg_id
            
            # Find matching search
            matching_search = None
            matching_msg_id = None
            
            # First try reply matching
            if reply_to_id and reply_to_id in self.pending_searches[chat_id]:
                matching_search = self.pending_searches[chat_id][reply_to_id]
                matching_msg_id = reply_to_id
            else:
                # Try to match by recent searches
                current_time = time.time()
                for msg_id, search_info in self.pending_searches[chat_id].items():
                    if current_time - search_info["start_time"] < search_info.get("timeout", 45):
                        matching_search = search_info
                        matching_msg_id = msg_id
                        break
            
            if not matching_search:
                return
            
            # Process the message
            text = message.text or message.raw_text or ""
            
            # Check for file
            if message.media:
                try:
                    file_bytes = await message.download_media(bytes)
                    if file_bytes:
                        # Determine file type
                        filename = ""
                        if hasattr(message.file, 'name') and message.file.name:
                            filename = message.file.name.lower()
                        
                        file_type = "txt"
                        if "json" in filename:
                            file_type = "json"
                        
                        # Decode content
                        content = ""
                        for enc in ['utf-8', 'latin-1', 'cp1252']:
                            try:
                                content = file_bytes.decode(enc)
                                break
                            except:
                                continue
                        
                        if content:
                            cleaned = clean_text(content)
                            matching_search["collected_files"].append({
                                "type": file_type,
                                "content": cleaned,
                                "raw": file_bytes,
                                "filename": filename or f"result.{file_type}"
                            })
                            logger.info(f"📁 Collected {file_type} file from {matching_search['group_name']}")
                            
                            # Send immediately to user
                            await self.send_file_to_user(matching_search, cleaned, file_bytes, file_type)
                
                except Exception as e:
                    logger.error(f"Error processing file: {e}")
            
            # Check for text result
            if text and is_valid_result(text):
                cleaned = clean_text(text)
                if cleaned and len(cleaned) > 50:
                    matching_search["collected_texts"].append({
                        "content": cleaned,
                        "source": matching_search["group_name"]
                    })
                    logger.info(f"📝 Collected text from {matching_search['group_name']} ({len(cleaned)} chars)")
                    
                    # Send immediately to user
                    await self.send_text_to_user(matching_search, cleaned)
        
        except Exception as e:
            logger.error(f"Error handling group message: {e}")
    
    async def send_text_to_user(self, search_info: Dict, text: str):
        """Send text result to user"""
        try:
            user_chat_id = search_info["user_chat_id"]
            query = search_info["query"]
            source = search_info["group_name"]
            search_type = search_info["search_type"]
            cmd = SEARCH_COMMANDS.get(search_type, {})
            
            header = f"{cmd.get('icon', '🔍')} **{cmd.get('name', 'Search Result')}**\n"
            header += f"🔍 Query: `{query}`\n"
            header += f"📊 Source: {source}\n"
            header += "─" * 30 + "\n\n"
            
            footer = "\n\n" + "─" * 30
            footer += "\n⚡ **DarkBoxes Intelligence**"
            footer += f"\n🕒 {datetime.now().strftime('%H:%M:%S')}"
            
            full_text = header + text + footer
            
            # Split if too long
            chunks = split_message(full_text, 4000)
            
            for i, chunk in enumerate(chunks):
                if i > 0:
                    chunk = f"📄 **Continued ({i+1}/{len(chunks)})**\n\n" + chunk
                
                await bot_client.send_message(
                    user_chat_id,
                    chunk,
                    parse_mode="md"
                )
            
            logger.info(f"✅ Sent text result to user {search_info['user_id']}")
        
        except Exception as e:
            logger.error(f"Error sending text to user: {e}")
    
    async def send_file_to_user(self, search_info: Dict, content: str, raw_bytes: bytes, file_type: str):
        """Send file result to user"""
        try:
            user_chat_id = search_info["user_chat_id"]
            query = search_info["query"]
            source = search_info["group_name"]
            
            # First send content as text
            if content and len(content) > 100:
                text_header = f"📄 **{file_type.upper()} DATA** from {source}\n"
                text_header += f"🔍 Query: `{query}`\n"
                text_header += "─" * 30 + "\n\n"
                
                full_text = text_header + content[:3500]
                if len(content) > 3500:
                    full_text += "\n\n... (see file for complete data)"
                
                await bot_client.send_message(
                    user_chat_id,
                    full_text,
                    parse_mode="md"
                )
            
            # Then send as file
            filename = f"result_{query}_{int(time.time())}.{file_type}"
            caption = f"📁 **{file_type.upper()} File**\n🔍 Query: `{query}`\n📊 Source: {source}"
            
            await bot_client.send_file(
                user_chat_id,
                file=raw_bytes,
                filename=filename,
                caption=caption
            )
            
            logger.info(f"✅ Sent {file_type} file to user {search_info['user_id']}")
        
        except Exception as e:
            logger.error(f"Error sending file to user: {e}")

search_engine = SearchEngine()

# ================== EVENT HANDLERS ==================

@bot_client.on(events.NewMessage(pattern=r'/start(?: (.+))?'))
async def start_handler(event):
    try:
        user = await event.get_sender()
        user_id = user.id
        referral = event.pattern_match.group(1)
        
        # Get or create user
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await db_manager.create_user(user_id, user.username, user.first_name, referral)
            user_doc = await db_manager.get_user(user_id)
            
            # Process referral
            if referral:
                await db_manager.add_referral(referral)
        
        if user_doc and user_doc.get('is_banned'):
            await event.respond("🚫 Your account has been banned.")
            return
        
        is_admin = user_id == config.ADMIN_USER_ID or (user_doc and user_doc.get('is_admin'))
        
        welcome = (
            f"🎭 **DARKBOXES INTELLIGENCE**\n\n"
            f"Welcome, **{user.first_name}**!\n\n"
            f"📊 **Your Account:**\n"
            f"├─ Credits: {user_doc.get('searches_remaining', 0) if user_doc else config.NEW_USER_CREDITS}\n"
            f"├─ Searches: {user_doc.get('total_searches', 0) if user_doc else 0}\n"
            f"└─ Referral Code: `{user_doc.get('referral_code', 'N/A') if user_doc else 'N/A'}`\n\n"
            f"🛠️ **Select a service below:**"
        )
        
        await event.respond(welcome, buttons=main_menu_keyboard(is_admin), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in start: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^search_(.+)$'))
async def search_callback(event):
    try:
        user_id = event.sender_id
        search_type = event.data.decode().split('_', 1)[1]
        
        if search_type not in SEARCH_COMMANDS:
            await event.answer("❌ Invalid", alert=True)
            return
        
        cmd = SEARCH_COMMANDS[search_type]
        
        # Check credits
        if not await db_manager.can_search(user_id, cmd["cost"]):
            await event.edit(
                "🔒 **INSUFFICIENT CREDITS**\n\n"
                f"This search requires {cmd['cost']} credit(s).\n\n"
                "💎 **Get Premium:**\n"
                "• Basic: ₹99 (10 searches)\n"
                "• Standard: ₹249 (30 searches)\n"
                "• Premium: ₹499 (Unlimited)\n\n"
                "Contact @darkboxesAdmin",
                buttons=back_button(),
                parse_mode="md"
            )
            return
        
        # Ask for query
        await event.edit(
            f"{cmd['icon']} **{cmd['name']}**\n\n"
            f"💎 Cost: {cmd['cost']} credit(s)\n"
            f"📝 Example: `{cmd['example']}`\n\n"
            f"**Enter your query:**",
            buttons=back_button(),
            parse_mode="md"
        )
        
        user_states[user_id] = {"action": "search", "type": search_type}
    
    except Exception as e:
        logger.error(f"Error in search callback: {e}")
        await event.answer("Error", alert=True)

@bot_client.on(events.CallbackQuery(pattern=r'^profile$'))
async def profile_callback(event):
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("User not found", alert=True)
            return
        
        profile = (
            f"👤 **YOUR PROFILE**\n\n"
            f"📋 **Info:**\n"
            f"├─ ID: `{user_id}`\n"
            f"├─ Credits: {user_doc.get('searches_remaining', 0)}\n"
            f"├─ Searches: {user_doc.get('total_searches', 0)}\n"
            f"├─ Subscription: {user_doc.get('subscription', 'None')}\n"
            f"└─ Referrals: {user_doc.get('referrals', 0)}\n\n"
            f"🔗 **Referral Link:**\n"
            f"`https://t.me/{bot_info.username}?start={user_doc.get('referral_code', '')}`\n\n"
            f"💎 Earn {config.REFERRAL_REWARD} credit per referral!"
        )
        
        await event.edit(profile, buttons=back_button(), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in profile: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^premium$'))
async def premium_callback(event):
    try:
        premium = (
            f"💎 **PREMIUM PLANS**\n\n"
            f"💰 **BASIC** - ₹99\n"
            f"├─ 10 Searches\n"
            f"└─ 7 Days\n\n"
            f"🚀 **STANDARD** - ₹249\n"
            f"├─ 30 Searches\n"
            f"└─ 15 Days\n\n"
            f"👑 **PREMIUM** - ₹499\n"
            f"├─ Unlimited Searches\n"
            f"└─ 30 Days\n\n"
            f"💳 **UPI:** `{config.UPI_ID}`\n\n"
            f"📞 Contact @darkboxesAdmin after payment"
        )
        
        await event.edit(premium, buttons=back_button(), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in premium: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^referrals$'))
async def referrals_callback(event):
    try:
        user_id = event.sender_id
        user_doc = await db_manager.get_user(user_id)
        
        if not user_doc:
            await event.answer("User not found", alert=True)
            return
        
        referral_link = f"https://t.me/{bot_info.username}?start={user_doc.get('referral_code', '')}"
        
        text = (
            f"📊 **REFERRAL PROGRAM**\n\n"
            f"💰 Earn {config.REFERRAL_REWARD} credit per referral!\n\n"
            f"📈 **Your Stats:**\n"
            f"├─ Referrals: {user_doc.get('referrals', 0)}\n"
            f"└─ Code: `{user_doc.get('referral_code', 'N/A')}`\n\n"
            f"🔗 **Your Link:**\n"
            f"`{referral_link}`\n\n"
            f"Share this link to earn credits!"
        )
        
        await event.edit(text, buttons=back_button(), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in referrals: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^support$'))
async def support_callback(event):
    try:
        text = (
            f"🆘 **SUPPORT**\n\n"
            f"📞 **Contact:** @darkboxesAdmin\n"
            f"📢 **Channel:** @darkboxesv1\n\n"
            f"💳 **Payment UPI:** `{config.UPI_ID}`\n\n"
            f"⏰ Response: Within 1 hour"
        )
        
        await event.edit(text, buttons=back_button(), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in support: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^main_menu$'))
async def main_menu_callback(event):
    try:
        user_id = event.sender_id
        user_states.pop(user_id, None)
        
        user_doc = await db_manager.get_user(user_id)
        is_admin = user_id == config.ADMIN_USER_ID or (user_doc and user_doc.get('is_admin'))
        
        text = (
            f"🎭 **DARKBOXES INTELLIGENCE**\n\n"
            f"📊 Credits: {user_doc.get('searches_remaining', 0) if user_doc else 0}\n"
            f"🔍 Searches: {user_doc.get('total_searches', 0) if user_doc else 0}\n\n"
            f"🛠️ **Select a service:**"
        )
        
        await event.edit(text, buttons=main_menu_keyboard(is_admin), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in main menu: {e}")

@bot_client.on(events.CallbackQuery(pattern=r'^admin_panel$'))
async def admin_panel_callback(event):
    try:
        user_id = event.sender_id
        if user_id != config.ADMIN_USER_ID:
            user_doc = await db_manager.get_user(user_id)
            if not user_doc or not user_doc.get('is_admin'):
                await event.answer("Access denied", alert=True)
                return
        
        # Get stats
        total_users = db_manager.db.users.count_documents({})
        
        text = (
            f"⚙️ **ADMIN PANEL**\n\n"
            f"📊 **Stats:**\n"
            f"├─ Total Users: {total_users}\n"
            f"└─ Bot: @{bot_info.username}\n\n"
            f"**Commands:**\n"
            f"• /addcredits [id] [amount]\n"
            f"• /ban [id]\n"
            f"• /unban [id]\n"
            f"• /user [id]\n"
            f"• /broadcast [msg]"
        )
        
        await event.edit(text, buttons=back_button(), parse_mode="md")
    
    except Exception as e:
        logger.error(f"Error in admin panel: {e}")

@bot_client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/')))
async def handle_private_message(event):
    """Handle private messages for search queries"""
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
        
        cmd = SEARCH_COMMANDS.get(search_type)
        if not cmd:
            user_states.pop(user_id, None)
            return
        
        # Validate
        validation = cmd.get("validation")
        if validation and not re.match(validation, query, re.IGNORECASE):
            await event.respond(f"❌ Invalid format.\nExample: `{cmd['example']}`", parse_mode="md")
            return
        
        # Check credits again
        if not await db_manager.can_search(user_id, cmd["cost"]):
            await event.respond("🔒 Insufficient credits. Use /start to check balance.")
            user_states.pop(user_id, None)
            return
        
        # Clear state
        user_states.pop(user_id, None)
        
        # Send processing message
        status_msg = await event.respond(
            f"🔍 **Searching...**\n\n"
            f"Query: `{query}`\n"
            f"Type: {cmd['name']}\n\n"
            f"⏳ Please wait (up to 45 seconds)...",
            parse_mode="md"
        )
        
        # Deduct credits
        await db_manager.deduct_credits(user_id, cmd["cost"])
        
        # Perform search
        result = await search_engine.perform_search(
            search_type, 
            query, 
            user_id,
            event.chat_id
        )
        
        # Delete status
        try:
            await status_msg.delete()
        except:
            pass
        
        if not result.get("success"):
            # Results might have been sent during search, check
            if result.get("results") and (result["results"].get("texts") or result["results"].get("files")):
                # Results were sent during the search
                await event.respond(
                    f"✅ **Search Complete**\n\n"
                    f"Query: `{query}`\n"
                    f"Results sent above.",
                    parse_mode="md"
                )
            else:
                # No results
                await event.respond(
                    f"❌ **No Results Found**\n\n"
                    f"Query: `{query}`\n\n"
                    f"Try:\n"
                    f"• Different search type\n"
                    f"• Different format\n"
                    f"• Advanced OSINT (🚀)\n\n"
                    f"Contact @darkboxesAdmin for help.",
                    parse_mode="md"
                )
        else:
            # If results weren't sent during search, send summary
            results = result.get("results", {})
            if not results.get("texts") and not results.get("files"):
                await event.respond(
                    f"✅ **Search Complete**\n\n"
                    f"Query: `{query}`\n"
                    f"Check messages above for results.",
                    parse_mode="md"
                )
    
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        traceback.print_exc()
        await event.respond("❌ An error occurred. Please try again.")

# ================== ADMIN COMMANDS ==================

@bot_client.on(events.NewMessage(pattern=r'/addcredits (\d+) (\d+)'))
async def add_credits_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        target_id = int(event.pattern_match.group(1))
        credits = int(event.pattern_match.group(2))
        
        if await db_manager.add_credits(target_id, credits):
            await event.respond(f"✅ Added {credits} credits to {target_id}")
            try:
                await bot_client.send_message(target_id, f"🎁 You received {credits} credits!")
            except:
                pass
        else:
            await event.respond("❌ Failed")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/ban (\d+)'))
async def ban_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        target_id = int(event.pattern_match.group(1))
        db_manager.db.users.update_one({"user_id": target_id}, {"$set": {"is_banned": True}})
        await event.respond(f"✅ Banned {target_id}")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/unban (\d+)'))
async def unban_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        target_id = int(event.pattern_match.group(1))
        db_manager.db.users.update_one({"user_id": target_id}, {"$set": {"is_banned": False}})
        await event.respond(f"✅ Unbanned {target_id}")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/user (\d+)'))
async def user_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        target_id = int(event.pattern_match.group(1))
        user = await db_manager.get_user(target_id)
        
        if user:
            text = (
                f"👤 **User {target_id}**\n\n"
                f"Name: {user.get('first_name', 'N/A')}\n"
                f"Username: @{user.get('username', 'N/A')}\n"
                f"Credits: {user.get('searches_remaining', 0)}\n"
                f"Searches: {user.get('total_searches', 0)}\n"
                f"Banned: {user.get('is_banned', False)}\n"
                f"Referrals: {user.get('referrals', 0)}"
            )
            await event.respond(text, parse_mode="md")
        else:
            await event.respond("❌ User not found")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/broadcast (.+)', flags=re.DOTALL))
async def broadcast_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        message = event.pattern_match.group(1)
        users = list(db_manager.db.users.find({}, {"user_id": 1}))
        
        sent = 0
        for user in users:
            try:
                await bot_client.send_message(user["user_id"], f"📢 **Announcement**\n\n{message}")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        
        await event.respond(f"✅ Sent to {sent}/{len(users)} users")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

@bot_client.on(events.NewMessage(pattern=r'/reply (\d+) (.+)', flags=re.DOTALL))
async def reply_cmd(event):
    if event.sender_id != config.ADMIN_USER_ID:
        return
    
    try:
        target_id = int(event.pattern_match.group(1))
        message = event.pattern_match.group(2)
        
        await bot_client.send_message(target_id, f"📩 **Admin Reply**\n\n{message}")
        await event.respond(f"✅ Sent to {target_id}")
    except Exception as e:
        await event.respond(f"❌ Error: {e}")

# ================== GROUP MESSAGE HANDLER ==================

@user_client.on(events.NewMessage())
async def handle_group_message(event):
    """Handle all messages from groups"""
    try:
        # Check if this is from one of our search groups
        chat_id = event.chat_id
        
        for group_key, group_data in GROUP_CONFIG.items():
            if group_data.get("entity"):
                group_id = group_data["entity"].id if hasattr(group_data["entity"], 'id') else 0
                if chat_id == group_id:
                    await search_engine.handle_group_message(event)
                    return
    except:
        pass

# ================== WEB SERVER ==================

async def start_web_server():
    app = web.Application()
    app.router.add_get('/health', lambda r: web.Response(text="OK"))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    
    try:
        await site.start()
        logger.info(f"🌐 Web server on port {config.PORT}")
    except Exception as e:
        logger.error(f"Web server error: {e}")

# ================== MAIN ==================

async def main():
    global db_manager, bot_info
    
    try:
        logger.info("🚀 Starting DarkBoxes...")
        
        # Start bot
        await bot_client.start(bot_token=config.BOT_TOKEN)
        bot_info = await bot_client.get_me()
        logger.info(f"✅ Bot: @{bot_info.username}")
        
        # Start user client
        if USE_USER_ACCOUNT:
            await user_client.connect()
            if not await user_client.is_user_authorized():
                logger.error("❌ User client not authorized")
                return
            logger.info("✅ User client ready")
        
        # Connect database
        db_manager = DatabaseManager()
        if not await db_manager.connect():
            return
        
        # Resolve groups
        logger.info("📡 Connecting to groups...")
        for key, group in GROUP_CONFIG.items():
            if group["enabled"]:
                try:
                    group["entity"] = await user_client.get_entity(group["identifier"])
                    logger.info(f"✅ {group['name']}")
                except Exception as e:
                    logger.warning(f"⚠️ {group['name']}: {e}")
        
        # Start web server
        asyncio.create_task(start_web_server())
        
        logger.info("=" * 50)
        logger.info("🎭 DARKBOXES OPERATIONAL")
        logger.info("=" * 50)
        
        await bot_client.run_until_disconnected()
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal: {e}")
        traceback.print_exc()
    finally:
        try:
            await bot_client.disconnect()
            if USE_USER_ACCOUNT:
                await user_client.disconnect()
        except:
            pass

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
