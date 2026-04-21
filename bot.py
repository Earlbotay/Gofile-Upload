import asyncio
import os
import json
import shutil
import time
import subprocess
import requests
import math
import uuid
import html
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DOMAIN = os.getenv("DOMAIN", "temp.earlstore.online")
UPLOAD_URL = f"https://{DOMAIN}/api/upload"
WEB_URL = f"https://{DOMAIN}"
LOCAL_API_URL = "http://127.0.0.1:8081"
CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

# ThreadPoolExecutor dengan 999 workers untuk handle banyak tugas serentak
executor = ThreadPoolExecutor(max_workers=999)

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

# Lock untuk simpan index supaya tidak rosak jika banyak fail serentak
index_lock = asyncio.Lock()

def load_index():
    try:
        if not CACHE_INDEX.exists(): return {}
        with open(CACHE_INDEX, "r") as f: return json.load(f)
    except: return {}

async def save_index_async(index):
    async with index_lock:
        with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

def check_local_api():
    """Semak jika Local API Server sedang berjalan."""
    try:
        resp = requests.get(f"{LOCAL_API_URL}/bot{TELEGRAM_TOKEN}/getMe", timeout=2)
        return resp.status_code == 200
    except:
        return False

IS_LOCAL = check_local_api()
BASE_URL = f"{LOCAL_API_URL}/bot{TELEGRAM_TOKEN}" if IS_LOCAL else f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

print(f"INFO: Menggunakan {'Local API Server' if IS_LOCAL else 'Official Telegram API'}")

def tg_api_call(method, data=None):
    """Fungsi asal tetap ada untuk kegunaan internal."""
    try:
        url = f"{BASE_URL}/{method}"
        # Jika ada data reply_markup dalam format dictionary, tukar ke JSON string
        if data and "reply_markup" in data and isinstance(data["reply_markup"], dict):
            data["reply_markup"] = json.dumps(data["reply_markup"])
            
        resp = requests.post(url, data=data, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

async def tg_api_call_async(method, data=None):
    """Telegram API call yang tidak menghalang (non-blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, tg_api_call, method, data)

def download_file_sync(url, dest):
    """Download fail secara synchronous (untuk dijalankan dalam executor)."""
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            shutil.copyfileobj(r.raw, f)

async def safe_edit_message(chat_id, message_id, text):
    """Cuba edit mesej (HTML), jika gagal, hantar mesej baru."""
    res = await tg_api_call_async("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"})
    if not res or not res.get("ok"):
        return await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    return res

def upload_to_earlstore(file_path: Path, chat_id=None, status_id=None):
    """Memuat naik ke Earl File dengan progress update ke Telegram."""
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return "❌ Ralat: Fail kosong atau tidak wujud di server."

        file_size = file_path.stat().st_size
        chunk_size = 5 * 1024 * 1024  # 5MB
        total_chunks = math.ceil(file_size / chunk_size)
        upload_id = str(uuid.uuid4())
        
        final_url = None

        with open(file_path, "rb") as f:
            for i in range(total_chunks):
                chunk_data = f.read(chunk_size)
                
                payload = {
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                    "upload_id": upload_id
                }
                files = {"file": (file_path.name, chunk_data)}
                
                resp = requests.post(UPLOAD_URL, data=payload, files=files, timeout=120)
                
                if resp.status_code == 200:
                    data = resp.json()
                    if "url" in data:
                        final_url = data["url"]
                    
                    # Update progress setiap 2 chunks atau chunk terakhir (Hanya jika total_chunks > 1)
                    if chat_id and status_id and total_chunks > 1 and (i % 2 == 0 or i == total_chunks - 1):
                        percent = int(((i + 1) / total_chunks) * 100)
                        bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
                        progress_text = (
                            f"🚀 <b>Earl File...</b>\n\n"
                            f"<blockquote><code>{bar}</code> {percent}%\n"
                            f"<b>Bahagian {i+1}/{total_chunks}</b></blockquote>"
                        )
                        asyncio.run_coroutine_threadsafe(safe_edit_message(chat_id, status_id, progress_text), asyncio.get_event_loop())
                        # Tambah delay 1 saat antara edit untuk elakkan Rate Limit Telegram
                        time.sleep(1)
                else:
                    return f"❌ EarlStore Error (Part {i+1}): {resp.text}"

        return final_url or "❌ Error: Gagal mendapatkan URL akhir."
    except Exception as e:
        return f"❌ EarlStore Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    
    # Handle /start command
    if 'text' in message and message['text'].startswith('/start'):
        welcome_text = (
            "<b>👋 Selamat Datang ke Earl File Bot!</b>\n\n"
            "<blockquote>Saya boleh membantu anda memuat naik fail ke <b>Earl File</b> dengan pantas dan selamat.</blockquote>\n\n"
            "<b>Cara Guna:</b>\n"
            "<blockquote>1. Hantar sebarang media ke sini.\n"
            "2. Tunggu bot memproses muat naik.\n"
            "3. Bot akan memberikan pautan hasil.</blockquote>\n\n"
            "<b>Ciri-ciri:</b>\n"
            "<blockquote>✅ Sokongan fail besar.\n"
            "✅ Pemprosesan serentak.\n"
            "✅ Progress bar masa nyata.</blockquote>\n\n"
            "<i>Dibina untuk kelajuan. Selamat mencuba!</i>"
        )
        # Menambah butang merah "LINK WEB" dengan gaya 'danger'
        markup = {
            "inline_keyboard": [
                [{"text": "🌐 LINK WEB", "url": WEB_URL, "style": "danger"}]
            ]
        }
        await tg_api_call_async("sendMessage", {
            "chat_id": chat_id, 
            "text": welcome_text, 
            "parse_mode": "HTML",
            "reply_markup": markup
        })
        return

    attachment = None
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

    file_info = await tg_api_call_async("getFile", {"file_id": file_id})
    if not file_info or not file_info.get('ok'):
        await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": "❌ Gagal mendapatkan info fail."})
        return

    tg_file_path = file_info['result']['file_path']
    ext = os.path.splitext(tg_file_path)[1] or ".bin"
    safe_filename = html.escape(attachment.get('file_name', f"{file_unique_id}{ext}"))
    
    # Folder unik untuk setiap muat naik (TASK ISOLATION)
    task_id = str(uuid.uuid4())[:8]
    task_dir = CACHE_DIR / task_id
    task_dir.mkdir(exist_ok=True)
    
    filename = f"{file_unique_id}{ext}"
    cached_path = task_dir / filename

    index = load_index()
    is_cached = file_unique_id in index and Path(index[file_unique_id]['path']).exists()
    
    if is_cached:
        cached_path = Path(index[file_unique_id]['path'])
        if cached_path.stat().st_size == 0: is_cached = False

    status_msg = f"⏳ Memproses <b>{safe_filename}</b>... {'(⚡ Cache)' if is_cached else ''}"
    status = await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": status_msg, "parse_mode": "HTML"})
    if not status: return
    status_id = status['result']['message_id']

    try:
        loop = asyncio.get_event_loop()
        if not is_cached:
            await safe_edit_message(chat_id, status_id, f"📥 <b>Menyediakan fail:</b>\n<blockquote><code>{safe_filename}</code> ({file_size_str})...</blockquote>")
            
            if IS_LOCAL:
                source_path = Path(tg_file_path)
                if source_path.exists():
                    await loop.run_in_executor(executor, shutil.copy2, source_path, cached_path)
                else:
                    raise Exception(f"Fail tidak dijumpai di disk Local API: {tg_file_path}")
            else:
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_file_path}"
                await loop.run_in_executor(executor, download_file_sync, file_url, cached_path)
            
            if cached_path.stat().st_size == 0: raise Exception("Muat turun berjaya tapi fail bersaiz 0MB.")

            # Simpan dalam index secara selamat (Async Lock)
            index = load_index()
            index[file_unique_id] = {"path": str(cached_path), "name": safe_filename}
            await save_index_async(index)

        await safe_edit_message(chat_id, status_id, f"🚀 <b>Earl File...</b>")
        
        # Gunakan executor khusus (999 workers) untuk muat naik
        print(f"DEBUG: Memulakan muat naik fail {safe_filename}...")
        earl_link = await loop.run_in_executor(executor, upload_to_earlstore, cached_path, chat_id, status_id)
        print(f"DEBUG: Muat naik selesai. Link: {earl_link}")

        if earl_link and "http" in str(earl_link):
            # Finalize progress
            await safe_edit_message(chat_id, status_id, f"✅ <b>Muat naik selesai!</b>\nSila semak mesej di bawah.")
            
            # Hantar HASIL (Link) sebagai MESEJ BARU
            final_caption = (
                f"🔗 <b>Earl File Berjaya Dicipta!</b>\n\n"
                f"<blockquote>📁 <b>Fail:</b> <code>{safe_filename}</code>\n"
                f"📊 <b>Saiz:</b> {file_size_str}\n\n"
                f"🌐 <b>Pautan:</b> {earl_link}</blockquote>"
            )
            res = await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": final_caption, "parse_mode": "HTML"})
            if not res or not res.get("ok"):
                # Fallback jika gagal hantar mesej cantik
                await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": f"✅ Berjaya!\nLink: {earl_link}"})
        else:
            await safe_edit_message(chat_id, status_id, f"❌ <b>Gagal:</b> API tidak memulangkan link sah.\n<blockquote>Respon API: <code>{html.escape(str(earl_link))}</code></blockquote>")

    except Exception as e:
        await safe_edit_message(chat_id, status_id, f"❌ <b>Ralat:</b> {html.escape(str(e))}")
    finally:
        try:
            if task_dir.exists(): shutil.rmtree(task_dir)
        except: pass

async def main():
    if not TELEGRAM_TOKEN:
        print("Ralat: TELEGRAM_TOKEN tidak ditetapkan!")
        return
        
    print(f"🤖 Bot Earl File dimulakan ({'LOCAL' if IS_LOCAL else 'OFFICIAL'})...")
    offset = 0
    while True:
        try:
            updates = await tg_api_call_async("getUpdates", {"offset": offset, "timeout": 30})
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
