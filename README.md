# Telegram Mirror Bot - Ultimate Channel Mirroring Tool

A powerful, production-ready Telegram bot that mirrors messages, media, and files from source channels/groups to target channels/groups with original filenames, media optimization, deduplication, and real-time sync.

## 🌟 Features

### Core Features
- **Real-time Mirroring** - Automatically mirrors new messages, edits, and deletions
- **Initial Sync** - Sync all historical messages on first run
- **Media Support** - Supports images, videos, documents, GIFs, and audio files
- **Original Filename Preservation** - Keeps original filenames for all files
- **Cross-Platform** - Works on Windows, Linux, and macOS

### Advanced Features
- **Video Streaming Support** - Videos are sent with streaming enabled
- **Smart Media Handling** - Automatic detection of media types
- **Deduplication** - Prevents duplicate media storage using SHA-256 hashing
- **Database Tracking** - SQLite database for message mapping and statistics
- **Edit/Delete Sync** - Mirrors message edits and deletions in real-time
- **Flood Control** - Automatic handling of Telegram rate limits
- **Retry Logic** - Exponential backoff for failed operations
- **Private Channel Support** - Can mirror private channels (with proper access)

### Media Optimization (Optional)
- **Image Compression** - Automatic image optimization (requires Pillow)
- **MIME Detection** - Accurate file type detection (requires python-magic)
- **Thumbnail Generation** - Automatic thumbnails for videos

## 📋 Prerequisites

- Python 3.8 or higher
- Telegram API credentials (api_id and api_hash)
- Access to source channel (must be member)
- Permission to post in target channel

## 🚀 Quick Installation

```bash
git clone https://github.com/jojo990gryo/Telegram-channel-Mirrort-ool-.git
cd Telegram-channel-Mirrort-ool-

nano config.json or notepad config.json

python3 main.py
