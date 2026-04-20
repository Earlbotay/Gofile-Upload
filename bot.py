import asyncio
import os
import requests
import json
import shutil
import time
import re
from pathlib import Path

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/tg-api-data")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

def wait_for_local_api():
    if not TELEGRAM_TOKEN: return False
    print(f"Menunggu Local API...")
    for i in range(5):
        try:
            resp = requests.get(f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}/getMe", timeout=5)
            if resp.status_code == 200:
                return True
        except: pass
        time.sleep(1)
    return False

# Status API
USE_LOCAL_API = False
API_URL = BASE_URL

def tg_api_call(method, data=None, files=None):
    try:
        url = f"{API_URL}/{method}"
        resp = requests.post(url, data=data, files=files, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"TG API Error: {e}")
        return None

def sanitize_filename(name: str):
    # Tukar ruang ke underscore, biarkan underscore sedia ada
    clean = name.replace(" ", "_")
    # Buang simbol pelik tapi kekalkan titik dan underscore
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    # Elakkan underscore bertindih
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

def upload_to_gofile(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        server_resp = requests.get("https://api.gofile.io/servers", timeout=15)
        server = server_resp.json()["data"]["servers"][0]["name"]
        url = f"https://{server}.gofile.io/contents/uploadfile"
        with file_path.open("rb") as f:
            resp = requests.post(url, files={"file": (file_path.name, f)}, headers=headers, timeout=600)
        return resp.json()["data"]["downloadPage"]
    except Exception as e: return f"Gofile Error: {str(e)}"

def upload_to_tempsh(file_path: Path):
    try:
        # Hantar fail secara standard
        with file_path.open("rb") as f:
            resp = requests.post("https://temp.sh/upload", files={'file': (file_path.name, f)}, timeout=600)
            return resp.text.strip()
    except Exception as e: return f"Temp.sh Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    
    attachment = None
    media_types = ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']
    for mt in media_types:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    
    if not attachment: return

    raw_filename = attachment.get('file_name') or f"file_{attachment['file_unique_id']}"
    # PEMBERSIHAN NAMA FAIL (PASTIKAN ADA UNDERSCORE)
    filename = sanitize_filename(raw_filename)
    
    file_id = attachment['file_id']
    file_size_tg = attachment.get('file_size', 0)
    file_size_str = f"{file_size_tg / (1024*1024):.2f} MB"
    
    status_msg = tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⏳ Memproses `{filename}`...", "parse_mode": "Markdown"})
    if not status_msg: return
    status_id = status_msg['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        
        # Get File Info
        file_info = tg_api_call("getFile", {"file_id": file_id})
        if not file_info or not file_info.get('ok'): raise Exception("Gagal dapatkan fail dari Telegram")
        
        server_path = file_info['result']['file_path']
        
        # Download
        if USE_LOCAL_API:
            host_path = Path(server_path) if server_path.startswith('/') else Path(TELEGRAM_DATA_DIR) / f"bot{TELEGRAM_TOKEN}" / server_path.lstrip('/')
            if host_path.exists(): shutil.copy2(host_path, cached_path)
            else:
                r = requests.get(f"{LOCAL_API_SERVER}/file/bot{TELEGRAM_TOKEN}/{server_path.lstrip('/')}", stream=True)
                with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)
        else:
            r = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{server_path}", stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0:
            raise Exception("Muat turun gagal (0 bait)")

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}` ke 2 Cloud...", "parse_mode": "Markdown"})

        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        )
        
        gofile_url = results[0]
        temp_raw = results[1]
        
        # --- OMEGA FORCE URL RECONSTRUCTION ---
        # Jika link dari server Temp.sh tiada underscore, kita bedah dan masukkan balik
        final_temp_url = temp_raw
        if "temp.sh" in temp_raw and "/" in temp_raw:
            try:
                # Cari ID (gaQsp) dalam https://temp.sh/gaQsp/File.zip
                parts = temp_raw.replace("https://", "").replace("http://", "").split('/')
                # parts[0] = temp.sh, parts[1] = ID, parts[2] = nama_fail_salah
                if len(parts) >= 2:
                    temp_id = parts[1]
                    final_temp_url = f"https://temp.sh/{temp_id}/{filename}"
                    print(f"DEBUG: Link dibetulkan -> {final_temp_url}")
            except: pass
        # --------------------------------------

        tg_api_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": status_id,
            "text": (
                f"✅ **Selesai (Versi V10 - Omega Force)!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {gofile_url}\n"
                f"⏱ **Temp.sh:** {final_temp_url}"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        if 'cached_path' in locals() and cached_path.exists():
            os.remove(cached_path)

async def main():
    global USE_LOCAL_API, API_URL
    USE_LOCAL_API = wait_for_local_api()
    API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL
    print(f"Bot V10 dimulakan pada {time.ctime()}")
    
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for update in updates['result']:
                    offset = update['update_id'] + 1
                    if 'message' in update:
                        msg = update['message']
                        if msg.get('text') == '/start':
                            tg_api_call("sendMessage", {"chat_id": msg['chat']['id'], "text": f"👋 **Multi-Cloud Bot V10 (Omega Force)**\n\nVersi: `V10 (Strict Underscore)`\nKemas kini: `{time.ctime()}`" , "parse_mode": "Markdown"})
                        else:
                            asyncio.create_task(process_media(msg))
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
