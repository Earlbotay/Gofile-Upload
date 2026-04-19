import asyncio
import os
import tempfile
import requests
import json
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters, CommandHandler

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Local Bot API Server defaults
LOCAL_API_URL = "http://localhost:8081"
CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

# Ensure cache directory exists
CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f:
        json.dump({}, f)

def load_index():
    with open(CACHE_INDEX, "r") as f:
        return json.load(f)

def save_index(index):
    with open(CACHE_INDEX, "w") as f:
        json.dump(index, f, indent=4)

# API Endpoints for Clouds
CATBOX_API = "https://catbox.moe/user/api.php"
TEMPSH_API = "https://temp.sh/upload"

def upload_to_gofile(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        server_resp = requests.get("https://api.gofile.io/servers", timeout=10)
        server = server_resp.json()["data"]["servers"][0]["name"]
        url = f"https://{server}.gofile.io/contents/uploadfile"
        with file_path.open("rb") as f:
            resp = requests.post(url, files={"file": (file_path.name, f)}, headers=headers, timeout=120)
        data = resp.json()
        return data["data"]["downloadPage"] if data.get("status") == "ok" else "Gofile Failed"
    except Exception as e:
        return f"Gofile Error: {str(e)}"

def upload_to_catbox(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        with file_path.open("rb") as f:
            resp = requests.post(CATBOX_API, data={"req": "upload"}, files={"fileToUpload": (file_path.name, f)}, headers=headers, timeout=120)
        return resp.text.strip() if resp.status_code == 200 else "Catbox Failed"
    except Exception as e:
        return f"Catbox Error: {str(e)}"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post(TEMPSH_API, files={"file": (file_path.name, f)}, timeout=120)
        return resp.text.strip() if resp.status_code == 200 else "Temp.sh Failed"
    except Exception as e:
        return f"Temp.sh Error: {str(e)}"

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    index = load_index()
    if not index:
        await update.message.reply_text("📭 Cache kosong.")
        return
    text = "📂 **Fail dalam Cache:**\n\n"
    for name, info in index.items():
        text += f"- `{name}` ({info['size']})\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_any_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message: return

    attachment = (message.document or message.video or message.audio or 
                  (message.photo[-1] if message.photo else None) or 
                  message.voice or message.video_note or message.animation)

    if not attachment: return

    filename = getattr(attachment, 'file_name', None) or f"file_{attachment.file_unique_id}"
    
    status_msg = await message.reply_text(f"⏳ Memproses fail besar: `{filename}`...")
    
    try:
        # Step 1: Download to local cache
        file_obj = await attachment.get_file()
        local_path = CACHE_DIR / filename
        await file_obj.download_to_drive(str(local_path))

        # Update Index
        index = load_index()
        file_size = f"{os.path.getsize(local_path) / (1024*1024):.2f} MB"
        index[filename] = {"size": file_size, "id": attachment.file_id}
        save_index(index)

        await status_msg.edit_text(f"🚀 Memuat naik `{filename}` ({file_size}) ke Cloud...")
        await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

        # Step 2: Upload in parallel
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, local_path),
            loop.run_in_executor(None, upload_to_catbox, local_path),
            loop.run_in_executor(None, upload_to_tempsh, local_path)
        ]
        results = await asyncio.gather(*tasks)
        
        response_text = (
            f"✅ **Berjaya Disimpan & Diupload!**\n\n"
            f"📁 **Fail:** `{filename}`\n"
            f"📊 **Saiz:** `{file_size}`\n\n"
            f"🌐 **Gofile:** {results[0]}\n"
            f"🐱 **Catbox:** {results[1]}\n"
            f"⏱ **Temp.sh:** {results[2]}\n\n"
            f"💡 *Gunakan /list untuk lihat cache.*"
        )
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Ralat: {str(e)}\n\n*Pastikan Local API Server berjalan untuk fail > 20MB.*", parse_mode='Markdown')

def main():
    if not TELEGRAM_TOKEN:
        print("Ralat: TELEGRAM_TOKEN tiada.")
        return

    # Connect to Local Bot API Server
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).base_url(f"{LOCAL_API_URL}/bot").local_mode(True).build()
    
    app.add_handler(CommandHandler("list", list_files))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, handle_any_media))
    
    print(f"Bot dimulakan dengan Local API di {LOCAL_API_URL}")
    app.run_polling()

if __name__ == "__main__":
    main()
