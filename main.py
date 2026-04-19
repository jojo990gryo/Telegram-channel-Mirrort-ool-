import asyncio
import json
import logging
import sqlite3
import io
import os
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
from telethon import TelegramClient, events, errors
from telethon.tl.types import (
    PeerChannel, PeerChat, PeerUser,
    MessageMediaDocument, MessageMediaPhoto, 
    DocumentAttributeFilename, MessageMediaWebPage
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("MirrorEnhanced")

DB_PATH = "mappings_rebuild.db"
CACHE_DIR = "media_cache"

class MediaProcessor:
    """Advanced media processing with optimization and metadata preservation"""
    
    @staticmethod
    def get_file_extension(file_path: str) -> str:
        """Get file extension from path"""
        return os.path.splitext(file_path)[1].lower()
    
    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """Calculate SHA-256 hash of file for deduplication"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

class DatabaseManager:
    """Enhanced database management with additional features"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
    
    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.init_tables()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
    
    def init_tables(self):
        cur = self.conn.cursor()
        
        # Main mapping table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mapping (
                source_chat INTEGER,
                source_msg INTEGER,
                target_chat INTEGER,
                target_msg INTEGER,
                file_hash TEXT,
                media_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source_chat, source_msg)
            )
        """)
        
        # File hash tracking for deduplication
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_cache (
                file_hash TEXT PRIMARY KEY,
                target_chat INTEGER,
                target_msg INTEGER,
                media_type TEXT,
                file_size INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Statistics table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                stat_key TEXT PRIMARY KEY,
                stat_value INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.commit()
    
    def save_mapping(self, s_chat: int, s_msg: int, t_chat: int, t_msg: int, 
                     file_hash: str = None, media_type: str = None):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO mapping 
            (source_chat, source_msg, target_chat, target_msg, file_hash, media_type) 
            VALUES (?,?,?,?,?,?)
        """, (s_chat, s_msg, t_chat, t_msg, file_hash, media_type))
        self.conn.commit()
        self._increment_stat("total_messages_mirrored")
    
    def get_mapping(self, s_chat: int, s_msg: int) -> Optional[Tuple]:
        cur = self.conn.cursor()
        cur.execute("SELECT target_chat, target_msg FROM mapping WHERE source_chat=? AND source_msg=?",
                   (s_chat, s_msg))
        return cur.fetchone()
    
    def delete_mapping(self, s_chat: int, s_msg: int):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM mapping WHERE source_chat=? AND source_msg=?", (s_chat, s_msg))
        self.conn.commit()
        self._increment_stat("total_messages_deleted")
    
    def save_file_cache(self, file_hash: str, t_chat: int, t_msg: int, 
                        media_type: str, file_size: int):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO file_cache 
            (file_hash, target_chat, target_msg, media_type, file_size) 
            VALUES (?,?,?,?,?)
        """, (file_hash, t_chat, t_msg, media_type, file_size))
        self.conn.commit()
    
    def get_cached_file(self, file_hash: str) -> Optional[Tuple]:
        cur = self.conn.cursor()
        cur.execute("SELECT target_chat, target_msg FROM file_cache WHERE file_hash=?", (file_hash,))
        return cur.fetchone()
    
    def _increment_stat(self, stat_key: str):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO stats (stat_key, stat_value) 
            VALUES (?, 1) 
            ON CONFLICT(stat_key) DO UPDATE SET 
            stat_value = stat_value + 1,
            updated_at = CURRENT_TIMESTAMP
        """, (stat_key,))
        self.conn.commit()
    
    def get_stats(self) -> Dict[str, int]:
        cur = self.conn.cursor()
        cur.execute("SELECT stat_key, stat_value FROM stats")
        return dict(cur.fetchall())

class EnhancedMirrorBot:
    """Enhanced mirror bot with advanced features"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config = self.load_config(config_path)
        self.client = None
        self.db_manager = None
        self.media_processor = MediaProcessor()
        self.id_map = {}
        self.running = True
        
        # Configuration flags
        self.deduplicate_files = self.config.get("deduplicate_files", True)
        self.max_file_size_mb = self.config.get("max_file_size_mb", 2000)
        self.retry_attempts = self.config.get("retry_attempts", 3)
        
        # Create cache directory
        os.makedirs(CACHE_DIR, exist_ok=True)
    
    def load_config(self, config_path: str) -> Dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    async def initialize(self):
        """Initialize client and database"""
        api_id = self.config["api_id"]
        api_hash = self.config["api_hash"]
        session = self.config.get("session_name", "mirror_session")
        
        self.client = TelegramClient(session, api_id, api_hash)
        self.db_manager = DatabaseManager(DB_PATH)
        self.db_manager.__enter__()
        
        await self.client.start()
        logger.info("🚀 Client connected successfully")
        
        # Resolve all mappings
        await self.resolve_mappings()
        
        # Display statistics
        await self.display_stats()
    
    async def resolve_mappings(self):
        """Resolve all source-target mappings"""
        mappings = self.config["mappings"]
        
        for m in mappings:
            src_id = m["source"]
            tgt_id = m["target"]
            
            src = await self.resolve_entity_safe(src_id)
            tgt = await self.resolve_entity_safe(tgt_id)
            
            self.id_map[src.id] = tgt
            logger.info(f"🔗 Mapping {src_id} ({src.id}) -> {tgt_id} ({tgt.id})")
            
            # Perform initial sync if configured
            if self.config.get("initial_sync", True):
                await self.initial_sync(src, tgt)
    
    async def resolve_entity_safe(self, identifier):
        """Safely resolve entity with retries"""
        for attempt in range(self.retry_attempts):
            try:
                if isinstance(identifier, int) or str(identifier).startswith("-100"):
                    return await self.client.get_entity(PeerChannel(int(identifier)))
                elif str(identifier).isdigit():
                    return await self.client.get_entity(PeerChat(int(identifier)))
                else:
                    return await self.client.get_entity(identifier)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed to resolve '{identifier}': {e}")
                if attempt == self.retry_attempts - 1:
                    raise
                await asyncio.sleep(2)
    
    def get_original_filename(self, message) -> Optional[str]:
        """Extract original filename with better metadata preservation"""
        if not message.media:
            return None
        
        # For documents with filename attribute
        if hasattr(message.media, 'document') and message.media.document:
            for attr in message.media.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    return attr.file_name
        
        # For photos
        if hasattr(message, 'photo') and message.photo:
            if message.date:
                return f"photo_{message.id}_{message.date.strftime('%Y%m%d_%H%M%S')}.jpg"
            return f"photo_{message.id}.jpg"
        
        # For videos
        if hasattr(message, 'video') and message.video:
            if message.date:
                return f"video_{message.id}_{message.date.strftime('%Y%m%d_%H%M%S')}.mp4"
            return f"video_{message.id}.mp4"
        
        # For other media, use message ID
        return f"media_{message.id}.bin"
    
    async def download_media_robust(self, message, file_path: str) -> bool:
        """Robust media download with multiple methods"""
        try:
            # Method 1: Direct download
            logger.info(f"📥 Downloading media from message {message.id}...")
            await message.download_media(file=file_path)
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"✅ Downloaded {os.path.getsize(file_path)} bytes")
                return True
            
            # Method 2: Try with BytesIO
            logger.info(f"⚠️ Direct download failed, trying BytesIO method...")
            buffer = io.BytesIO()
            await message.download_media(file=buffer)
            buffer.seek(0)
            
            with open(file_path, 'wb') as f:
                f.write(buffer.read())
            
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logger.info(f"✅ Downloaded via BytesIO: {os.path.getsize(file_path)} bytes")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            return False
    
    async def process_media_message(self, message, temp_dir: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Process media message with robust downloading"""
        if not message.media:
            return None, None, None
        
        # Get original filename
        filename = self.get_original_filename(message)
        if not filename:
            filename = f"media_{message.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
        
        # Download file with robust method
        file_path = os.path.join(temp_dir, filename)
        download_success = await self.download_media_robust(message, file_path)
        
        if not download_success or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            logger.warning(f"Failed to download media from message {message.id}")
            return None, None, None
        
        # Log file info
        file_size = os.path.getsize(file_path)
        logger.info(f"📁 File: {filename} ({file_size} bytes)")
        
        # Calculate file hash for deduplication
        file_hash = self.media_processor.calculate_file_hash(file_path)
        
        # Check if file already cached
        if self.deduplicate_files:
            cached = self.db_manager.get_cached_file(file_hash)
            if cached:
                logger.info(f"📎 Using cached file for hash {file_hash[:8]}...")
                return None, file_hash, filename
        
        return file_path, file_hash, filename
    
    async def rebuild_message(self, source_msg, target_entity, sleep_between=0.3):
        """Enhanced message rebuilding with robust media handling"""
        temp_dir = None
        file_path = None
        
        for attempt in range(self.retry_attempts):
            try:
                # Get message text/caption
                text = source_msg.text or source_msg.message or ""
                if hasattr(source_msg, 'caption') and source_msg.caption:
                    text = source_msg.caption
                
                temp_dir = tempfile.mkdtemp()
                
                # Determine media type and process
                has_media = source_msg.media is not None
                file_path = None
                file_hash = None
                filename = None
                media_type = None
                
                if has_media:
                    file_path, file_hash, filename = await self.process_media_message(source_msg, temp_dir)
                    
                    # Determine media type for logging
                    if source_msg.photo:
                        media_type = "photo"
                    elif source_msg.video:
                        media_type = "video"
                    elif source_msg.document:
                        media_type = "document"
                    elif source_msg.gif:
                        media_type = "gif"
                    elif source_msg.audio:
                        media_type = "audio"
                    else:
                        media_type = "media"
                
                # Send message
                if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    # Send as file with proper attributes
                    logger.info(f"📤 Sending {media_type or 'file'}: {filename or 'unnamed'}")
                    
                    # Determine if we should force document mode
                    force_document = False
                    supports_streaming = False
                    
                    if media_type == "video":
                        supports_streaming = True
                        force_document = False
                    elif media_type == "photo":
                        force_document = False
                    elif media_type == "document":
                        force_document = True
                    
                    sent = await self.client.send_file(
                        entity=target_entity,
                        file=file_path,
                        caption=text if text else None,
                        force_document=force_document,
                        supports_streaming=supports_streaming,
                        thumb=None  # Let Telegram generate thumbnails
                    )
                else:
                    # No media or download failed, send as text
                    if file_hash:
                        cached = self.db_manager.get_cached_file(file_hash)
                        if cached:
                            logger.info(f"📎 Referencing cached message instead of resending")
                            self.db_manager.save_mapping(
                                source_msg.chat_id, source_msg.id,
                                cached[0], cached[1],
                                file_hash, media_type
                            )
                            await asyncio.sleep(sleep_between)
                            return
                    
                    # Send as text message
                    if text:
                        sent = await self.client.send_message(
                            entity=target_entity,
                            message=text,
                            link_preview=False
                        )
                    else:
                        # If no text and no media, send a placeholder
                        sent = await self.client.send_message(
                            entity=target_entity,
                            message=f"📎 Media content ({media_type or 'file'} from source message {source_msg.id})",
                            link_preview=False
                        )
                
                # Save mappings and cache
                self.db_manager.save_mapping(
                    source_msg.chat_id, source_msg.id,
                    sent.chat_id, sent.id,
                    file_hash, media_type
                )
                
                if file_hash and file_path and os.path.exists(file_path):
                    self.db_manager.save_file_cache(
                        file_hash, sent.chat_id, sent.id,
                        media_type, os.path.getsize(file_path)
                    )
                
                logger.info(f"✅ Reposted {source_msg.chat_id}/{source_msg.id} -> {sent.chat_id}/{sent.id}")
                await asyncio.sleep(sleep_between)
                return  # Success, exit retry loop
                
            except errors.FloodWaitError as e:
                logger.warning(f"Flood wait {e.seconds} seconds")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed for message {source_msg.id}: {e}")
                if attempt == self.retry_attempts - 1:
                    logger.exception(f"Failed to copy message after {self.retry_attempts} attempts")
                else:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            finally:
                # Cleanup temporary files
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        os.rmdir(temp_dir)
                    except:
                        pass
    
    async def initial_sync(self, source_entity, target_entity):
        """Perform initial sync with progress tracking"""
        logger.info(f"📦 Starting initial sync from {source_entity.id} -> {target_entity.id}")
        
        message_count = 0
        async for msg in self.client.iter_messages(source_entity, reverse=True):
            if self.db_manager.get_mapping(msg.chat_id, msg.id):
                continue
            
            await self.rebuild_message(msg, target_entity, self.config.get("sleep_between", 0.3))
            message_count += 1
            
            if message_count % 10 == 0:
                logger.info(f"📊 Synced {message_count} messages so far...")
        
        logger.info(f"✅ Initial sync complete. Synced {message_count} messages.")
    
    async def display_stats(self):
        """Display mirroring statistics"""
        stats = self.db_manager.get_stats()
        if stats:
            logger.info("📊 Mirror Statistics:")
            for key, value in stats.items():
                logger.info(f"   {key}: {value}")
    
    async def run(self):
        """Main bot loop with event handlers"""
        await self.initialize()
        sleep_between = self.config.get("sleep_between", 0.3)
        
        # New messages handler
        @self.client.on(events.NewMessage(incoming=True))
        async def new_msg(event):
            src_chat = event.chat_id
            if src_chat in self.id_map:
                tgt = self.id_map[src_chat]
                await self.rebuild_message(event.message, tgt, sleep_between)
        
        # Edits handler
        @self.client.on(events.MessageEdited())
        async def edit_msg(event):
            src_chat = event.chat_id
            if src_chat in self.id_map:
                mapping = self.db_manager.get_mapping(src_chat, event.id)
                if mapping:
                    tgt_chat, tgt_msg = mapping
                    try:
                        # Get updated text/caption
                        new_text = event.message.text or event.message.message or ""
                        if hasattr(event.message, 'caption') and event.message.caption:
                            new_text = event.message.caption
                        
                        if new_text:
                            await self.client.edit_message(tgt_chat, tgt_msg, new_text)
                            logger.info(f"✏️ Mirrored edit {tgt_chat}/{tgt_msg}")
                    except Exception as e:
                        logger.warning(f"Failed to edit message: {e}")
        
        # Deletions handler
        @self.client.on(events.MessageDeleted())
        async def del_msg(event):
            src_chat = event.chat_id
            if src_chat in self.id_map:
                for mid in event.deleted_ids:
                    mapping = self.db_manager.get_mapping(src_chat, mid)
                    if mapping:
                        tgt_chat, tgt_msg = mapping
                        try:
                            await self.client.delete_messages(tgt_chat, tgt_msg)
                            self.db_manager.delete_mapping(src_chat, mid)
                            logger.info(f"🗑️ Deleted {tgt_chat}/{tgt_msg}")
                        except Exception as e:
                            logger.warning(f"Failed to delete message: {e}")
        
        logger.info("🤖 Enhanced mirror bot is running... (Press Ctrl+C to exit)")
        
        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped manually.")
        finally:
            if self.db_manager:
                self.db_manager.__exit__(None, None, None)

async def main():
    bot = EnhancedMirrorBot("config.json")
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown complete.")