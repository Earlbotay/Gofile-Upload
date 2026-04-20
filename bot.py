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
CACHE_DIR.mkdir(exist_ok=True)

def tg_api_call(method, data=None, files=None):
    try:
        resp = requests.post(f"{BASE_URL}/{method}", data=data, files=files, timeout=60)
        return resp.json()
    except: return None

def sanitize_filename(name: str):
    clean = name.replace(" ", "_")
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

def upload_to_gofile(file_path: Path):
    try:
        s = requests.get("https://api.gofile.io/servers").json()["data"]["servers"][0]["name"]
        with file_path.open("rb") as f:
            r = requests.post(f"https://{s}.gofile.io/contents/uploadfile", files={"file": (file_path.name, f)})
        return r.json()["data"]["downloadPage"]
    except: return "Gofile Error"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            r = requests.post("https://temp.sh/upload", files={'file': (file_path.name, f)})
            return r.text.strip()
    except: return "Temp.sh Error"

async def process_media(message):
    chat_id = message['chat']['id']
    att = None
    for mt in ['document', 'video', 'audio', 'photo']:
        if mt in message:
            att = message[mt]
            if mt == 'photo': att = att[-1]
            break
    if not att: return

    # NAMA FAIL DENGAN UNDERSCORE
    original_fn = att.get('file_name') or f"file_{att['file_unique_id']}"
    filename = sanitize_filename(original_fn)
    
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⏳ Memproses `{filename}`..."})
    if not status: return
    status_id = status['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        file_info = tg_api_call("getFile", {"file_id": att['file_id']})
        r = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info['result']['file_path']}", stream=True)
        with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}`..."})

        loop = asyncio.get_event_loop()
        res = await asyncio.gather(
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        )
        
        g_url = res[0]
        t_raw = res[1]
        
        # --- V12 BRUTE FORCE RECONSTRUCTION ---
        t_url = t_raw
        if "temp.sh/" in t_raw:
            # Cari ID (gaQsp) secara agresif
            find_id = re.findall(r"temp\.sh/([^/]+)", t_raw)
            if find_id:
                t_id = find_id[0]
                # BINA LINK BARU DARI KOSONG
                t_url = f"https://temp.sh/{t_id}/{filename}"
        # ---------------------------------------

        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai (Versi V12 - Brute Force)!**\n\n"
                f"📁 **Fail:** `{filename}`\n\n"
                f"🌐 **Gofile:** {g_url}\n"
                f"⏱ **Temp.sh:** {t_url}"
            ),
            "parse_mode": "Markdown", "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        if 'cached_path' in locals() and cached_path.exists(): os.remove(cached_path)

async def main():
    print(f"Bot V12 Online")
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    if 'message' in u:
                        m = u['message']
                        if m.get('text') == '/start':
                            tg_api_call("sendMessage", {"chat_id": m['chat']['id'], "text": f"👋 **Multi-Cloud Bot V12 (Brute Force)**\nUjian Masa: `{time.strftime('%H:%M:%S')}`"})
                        else: asyncio.create_task(process_media(m))
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
