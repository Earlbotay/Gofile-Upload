import asyncio
import os
import json
import shutil
import time
import subprocess
import requests
import mimetypes
from pathlib import Path

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

def load_index():
    try:
        with open(CACHE_INDEX, "r") as f: return json.load(f)
    except: return {}

def save_index(index):
    with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

def tg_api_call(method, data=None):
    try:
        url = f"{BASE_URL}/{method}"
        resp = requests.post(url, data=data, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

def upload_to_earlstore(file_path: Path):
    """Memuat naik ke EarlStore menggunakan curl untuk hasil pautan 'pure'."""
    try:
        url = "https://temp.earlstore.online/api/upload"
        cmd = [
            "curl", "-s",
            "-F", f"file=@{file_path.name}",
            url
        ]
        
        # Jalankan curl dari dalam folder fail berada
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(file_path.parent))
        if result.returncode != 0:
            return f"❌ Curl Error: {result.stderr}"
            
        data = json.loads(result.stdout)
        return data.get("url") or f"❌ Error API: {result.stdout}"
    except Exception as e:
        return f"❌ EarlStore Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    attachment = None
    
    # Kenalpasti jenis media
    for mt in ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
            
    if not attachment: return

    file_id = attachment['file_id']
    file_unique_id = attachment['file_unique_id']
    file_size_mb = attachment.get('file_size', 0) / (1024 * 1024)
    file_size_str = f"{file_size_mb:.2f} MB"

    # 1. Dapatkan maklumat fail (laluan asal dari Telegram)
    file_info = tg_api_call("getFile", {"file_id": file_id})
    if not file_info or not file_info.get('ok'):
        tg_api_call("sendMessage", {"chat_id": chat_id, "text": "❌ Gagal mendapatkan info fail."})
        return

    tg_file_path = file_info['result']['file_path']
    ext = os.path.splitext(tg_file_path)[1] or ".bin"
    filename = f"{file_unique_id}{ext}"
    cached_path = CACHE_DIR / filename

    # 2. Semak Cache
    index = load_index()
    is_cached = file_unique_id in index and Path(index[file_unique_id]['path']).exists()
    
    if is_cached:
        cached_path = Path(index[file_unique_id]['path'])
        status_msg = f"⏳ Memproses `{filename}`... (⚡ Cache)"
    else:
        status_msg = f"⏳ Memproses `{filename}`..."

    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": status_msg, "parse_mode": "Markdown"})
    if not status: return
    status_id = status['result']['message_id']

    try:
        # 3. Muat Turun (Jika tiada dalam cache)
        if not is_cached:
            tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"📥 Memuat turun `{filename}` ({file_size_str})...", "parse_mode": "Markdown"})
            
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_file_path}"
            with requests.get(file_url, stream=True) as r:
                with open(cached_path, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)
            
            index[file_unique_id] = {"path": str(cached_path), "name": filename}
            save_index(index)

        # 4. Muat Naik ke EarlStore
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik ke EarlStore...", "parse_mode": "Markdown"})
        
        loop = asyncio.get_event_loop()
        earl_link = await loop.run_in_executor(None, upload_to_earlstore, cached_path)

        # 5. Papar Hasil Akhir
        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Pautan:** {earl_link}"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })

    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})

async def main():
    if not TELEGRAM_TOKEN:
        print("Ralat: TELEGRAM_TOKEN tidak ditetapkan!")
        return
        
    print("🤖 Bot EarlStore dimulakan...")
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    if 'message' in u:
                        asyncio.create_task(process_media(u['message']))
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Loop error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
