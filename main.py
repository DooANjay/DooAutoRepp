import asyncio
import os
import random
import re
import aiosqlite
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (
    InputReportReasonSpam, InputReportReasonChildAbuse, 
    InputReportReasonViolence, InputReportReasonPornography, 
    InputReportReasonCopyright
)
from telethon.tl.custom import Button

load_dotenv()

# ============ CONFIG ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "ISI_TOKEN")
API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "ISI_HASH")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = "bot.db"
SESSION_RE = re.compile(r"^[A-Za-z0-9_\-=]{50,}$")

# ============ DATABASE ============
class Database:
    def __init__(self, path): self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY, role TEXT DEFAULT 'user');
            CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
                session_string TEXT, status TEXT DEFAULT 'active', owner_id INTEGER);
            """)
            await db.commit()

    async def add_user(self, uid, role="user"):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO users(user_id,role) VALUES(?,?)", (uid, role))
            await db.commit()

    async def get_role(self, uid):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT role FROM users WHERE user_id=?", (uid,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def add_session(self, name, sstr, owner):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO sessions(name,session_string,owner_id) VALUES(?,?,?)",
                (name, sstr, owner))
            await db.commit()
            return cur.lastrowid

    async def get_active_sessions(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id,name,session_string FROM sessions WHERE status='active'") as cur:
                return await cur.fetchall()

# ============ AUTH ============
async def is_admin(db, uid): return await db.get_role(uid) in ("owner", "admin")
async def is_owner(db, uid): return await db.get_role(uid) == "owner"

# ============ SESSION ============
async def add_session(db, owner_id, name, sstr):
    if not SESSION_RE.match(sstr):
        return "❌ Format session string nggak valid."
    try:
        c = TelegramClient(StringSession(sstr), API_ID, API_HASH)
        await c.connect()
        if not await c.is_user_authorized():
            await c.disconnect()
            return "❌ Session mati / nggak authorized."
        await c.disconnect()
    except Exception as ex:
        return f"❌ Gagal validasi: {ex}"
    sid = await db.add_session(name, sstr, owner_id)
    return f"✅ Session '{name}' ditambahin (ID: {sid})."

# ============ ENGINE REPORT ============
async def execute_report_massal(db, user_id, data, status_msg):
    target_link = data.get("target")
    msg_link = data.get("msg_link")
    reason = data.get("reason")
    limit = data.get("limit", 1)
    
    sessions = await db.get_active_sessions()
    if not sessions:
        return await status_msg.edit("❌ **Gagal:** Belum ada session aktif di database.")
    
    await status_msg.edit(f"🔥 **EKSEKUSI DIMULAI**\n\n🎯 Target: `{target_link}`\n🔗 Pesan: `{msg_link}`\n⚡ Alasan: `{data.get('reason_name')}`\n🔄 Limit: {limit}x per akun\n👤 Total Akun: {len(sessions)}\n\n⏳ *Sedang memproses report, mohon tunggu...*")
    
    total_ok = 0
    total_fail = 0
    log_details = []

    for sid, name, sstr in sessions:
        client = None
        try:
            client = TelegramClient(StringSession(sstr), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                log_details.append(f"❌ `{name}`: Session mati")
                total_fail += limit
                continue

            # 1. Join Grup
            try:
                if "t.me/+" in target_link or "joinchat" in target_link:
                    from telethon.tl.functions.messages import ImportChatInviteRequest
                    invite_hash = target_link.split("/")[-1].replace("+", "")
                    await client(ImportChatInviteRequest(invite_hash))
                else:
                    clean = target_link.replace("https://", "").replace("t.me/", "")
                    from telethon.tl.functions.channels import JoinChannelRequest
                    entity_group = await client.get_entity(clean)
                    await client(JoinChannelRequest(entity_group))
                await asyncio.sleep(2)
            except Exception:
                pass # Anggap udah join

            # 2. Ambil ID Pesan
            msg_id = None
            try:
                # Format link pesan: t.me/username/123
                if "/" in msg_link and not "+" in msg_link:
                    msg_id = int(msg_link.split("/")[-1])
                
                if "t.me/+" in target_link or "joinchat" in target_link:
                    from telethon.tl.functions.messages import CheckChatInviteRequest
                    invite_hash = target_link.split("/")[-1].replace("+", "")
                    invite_info = await client(CheckChatInviteRequest(invite_hash))
                    if hasattr(invite_info, 'chat'):
                        entity = invite_info.chat
                    else:
                        entity = None
                else:
                    clean = target_link.replace("https://", "").replace("t.me/", "")
                    entity = await client.get_entity(clean)

                # Kalau gak ada ID pesan, ambil pesan terakhir
                if not msg_id and entity:
                    async for msg in client.iter_messages(entity, limit=1):
                        msg_id = msg.id
                        break
            except Exception as e:
                log_details.append(f"❌ `{name}`: Gagal dapet pesan ({str(e)[:30]})")
                total_fail += limit
                continue

            # 3. Tembak Report
            if entity and msg_id:
                ok_count = 0
                for i in range(limit):
                    try:
                        # ================= SIMULASI (HAPUS BARIS INI KALAU MAU NEMBAK BENERAN) =================
                        await asyncio.sleep(1.5) 
                        # =========================================================================================
                        
                        # KODE ASLI TEMBAK:
                        # await client.report_message(entity, [msg_id], reason=reason)
                        
                        ok_count += 1
                        total_ok += 1
                    except Exception as e:
                        total_fail += 1
                        log_details.append(f"⚠️ `{name}` Gagal 1x: {str(e)[:30]}")
                    
                    await asyncio.sleep(random.uniform(2, 5)) # Delay antar report
                
                log_details.append(f"✅ `{name}`: {ok_count}/{limit} Sukses")
        except Exception as e:
            log_details.append(f"❌ `{name}`: {str(e)[:50]}")
            total_fail += limit
        finally:
            if client:
                try: await client.disconnect()
                except: pass

    # Rekap Akhir
    rekap_text = (
        f"🏁 **PROSES REPORT SELESAI** 🏁\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Target: {target_link}\n"
        f"⚡ Alasan: {data.get('reason_name')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **STATISTIK:**\n"
        f"✅ Sukses: **{total_ok}** report\n"
        f"❌ Gagal: **{total_fail}** report\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 **LOG (Maks 10):**\n" + "\n".join(log_details[:10])
    )
    await status_msg.edit(rekap_text)

# ============ MAIN ============
async def main():
    db = Database(DB_PATH)
    await db.init()
    if OWNER_ID:
        await db.add_user(OWNER_ID, "owner")

    bot = TelegramClient("bot", API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    print("🤖 Bot Epic UI Nyala!")

    # State Management (Nyimpen data sementara user)
    user_states = {}

    # ---- /start ----
    @bot.on(events.NewMessage(pattern=r"^/start"))
    async def h_start(e):
        role = await db.get_role(e.sender_id) or "Guest"
        buttons = [
            [Button.inline("🚀 Mulai Report Massal", data=b"rep_start")],
            [Button.inline("➕ Tambah Session", data=b"menu_addsession"), Button.inline("📊 Status", data=b"menu_summary")]
        ]
        text = (
            f"👑 **WELCOME TO AUTO REPORT PANEL** 👑\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **User:** `{e.sender_id}`\n"
            f"💎 **Role:** `{role.upper()}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Silakan pilih menu di bawah ini untuk memulai operasi:"
        )
        await e.reply(text, buttons=buttons)

    # ---- HANDLER TOMBOL ----
    @bot.on(events.CallbackQuery)
    async def h_tombol(e):
        uid = e.sender_id
        data = e.data.decode('utf-8')

        # Cek Admin
        if not await is_admin(db, uid) and data != b"menu_summary":
            return await e.answer("❌ Anda bukan Admin/Owner!", alert=True)

        # 1. Menu Awal Report
        if data == "rep_start":
            user_states[uid] = {}
            text = "🌐 **LANGKAH 1: PILIH TIPE GRUP**\n\nSilakan pilih target grup yang ingin di-report:"
            btns = [
                [Button.inline("🌍 Public Group (@username)", data=b"rep_type_public")],
                [Button.inline("🔒 Private Group (t.me/+link)", data=b"rep_type_private")],
                [Button.inline("🔙 Kembali", data=b"rep_back")]
            ]
            await e.edit(text, buttons=btns)

        # 2. Pilih Public
        elif data == "rep_type_public":
            user_states[uid]["type"] = "public"
            await e.edit("🌍 **MODE PUBLIC**\n\nSilakan **KETIK** link grup public (contoh: `@username` atau `t.me/username`) di chat ini:", buttons=Button.inline("❌ Batal", data=b"rep_start"))
        
        # 3. Pilih Private
        elif data == "rep_type_private":
            user_states[uid]["type"] = "private"
            await e.edit("🔒 **MODE PRIVATE**\n\nSilakan **KETIK/PASTE** link undangan grup (contoh: `https://t.me/+xxxxxx`) di chat ini:", buttons=Button.inline("❌ Batal", data=b"rep_start"))

        # 4. Pilih Alasan
        elif data.startswith("reason_"):
            reason_code = data.split("_")[1]
            reason_map = {
                "spam": ("Spam", InputReportReasonSpam()),
                "child": ("Child Abuse", InputReportReasonChildAbuse()),
                "violence": ("Violence", InputReportReasonViolence()),
                "porn": ("Pornography", InputReportReasonPornography()),
                "copyright": ("Copyright", InputReportReasonCopyright())
            }
            nama, obj = reason_map[reason_code]
            user_states[uid]["reason"] = obj
            user_states[uid]["reason_name"] = nama
            
            text = f"🚨 **LANGKAH 3: JUMLAH TEMBAKAN**\n\nAlasan: `{nama}`\n\nMau berapa kali report per akun session?"
            btns = [
                [Button.inline("1x", data=b"limit_1"), Button.inline("3x", data=b"limit_3"), Button.inline("5x", data=b"limit_5")],
                [Button.inline("10x", data=b"limit_10"), Button.inline("20x", data=b"limit_20")],
                [Button.inline("🔙 Kembali", data=b"rep_start")]
            ]
            await e.edit(text, buttons=btns)

        # 5. Pilih Limit & Eksekusi
        elif data.startswith("limit_"):
            limit = int(data.split("_")[1])
            user_states[uid]["limit"] = limit
            
            # Tampilkan Ringkasan
            info = user_states[uid]
            sessions = await db.get_active_sessions()
            
            text = (
                f"📝 **KONFIRMASI OPERASI** 📝\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Target: `{info.get('target')}`\n"
                f"🔗 Pesan: `{info.get('msg_link', 'Pesan Terakhir')}`\n"
                f"🚨 Alasan: `{info.get('reason_name')}`\n"
                f"⚡ Limit: **{limit}x** per akun\n"
                f"👤 Akun Tersedia: **{len(sessions)}**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Total Tembakan: **{limit * len(sessions)}x**\n\n"
                f"Apakah Anda yakin ingin memulai?"
            )
            btns = [
                [Button.inline("🚀 EKSEKUSI SEKARANG", data=b"rep_execute")],
                [Button.inline("❌ Batal", data=b"rep_start")]
            ]
            await e.edit(text, buttons=btns)

        # 6. Eksekusi
        elif data == "rep_execute":
            if uid not in user_states or "limit" not in user_states[uid]:
                return await e.answer("❌ Sesi expired, ulangi dari awal.", alert=True)
            
            info = user_states[uid]
            status_msg = await e.edit("⏳ Menghubungi server Telegram...", buttons=None)
            
            # Jalankan di background agar bot tidak freeze
            asyncio.create_task(execute_report_massal(db, uid, info, status_msg))

        # 7. Tombol Kembali
        elif data == "rep_back":
            role = await db.get_role(uid) or "Guest"
            buttons = [
                [Button.inline("🚀 Mulai Report Massal", data=b"rep_start")],
                [Button.inline("➕ Tambah Session", data=b"menu_addsession"), Button.inline("📊 Status", data=b"menu_summary")]
            ]
            await e.edit(f"👑 **WELCOME TO AUTO REPORT PANEL** 👑\nRole: `{role.upper()}`", buttons=buttons)

        # 8. Menu Lain
        elif data == "menu_summary":
            sessions = await db.get_active_sessions()
            await e.answer(f"Total Session Aktif: {len(sessions)}", alert=True)
            
        elif data == "menu_addsession":
            await e.answer("Ketik manual di chat: /addsession <nama> <session_string>", alert=True)

    # ---- TEXT HANDLER (Nangkep Input Link) ----
    @bot.on(events.NewMessage)
    async def h_text(e):
        uid = e.sender_id
        if not e.text or e.text.startswith("/"): return
        
        if uid in user_states:
            state = user_states[uid]
            
            # Nangkep Input Link Grup
            if "type" in state and "target" not in state:
                state["target"] = e.text.strip()
                text = "🔗 **LANGKAH 2: LINK PESAN**\n\nSilakan **KETIK/PASTE** link pesan spesifik yang mau di-report (contoh: `t.me/username/123`).\n\n*Atau ketik `SKIP` untuk melaporkan pesan terakhir di grup.*"
                await e.reply(text)
                state["waiting_msg_link"] = True
                
            # Nangkep Input Link Pesan
            elif state.get("waiting_msg_link"):
                if e.text.upper() == "SKIP":
                    state["msg_link"] = None
                else:
                    state["msg_link"] = e.text.strip()
                
                state["waiting_msg_link"] = False
                
                text = "🚨 **LANGKAH 3: PILIH ALASAN REPORT**\n\nPilih alasan yang sesuai dengan pelanggaran grup tersebut:"
                btns = [
                    [Button.inline("🚫 Spam", data=b"reason_spam"), Button.inline("⚠️ Kekerasan", data=b"reason_violence")],
                    [Button.inline("🔞 Pornografi", data=b"reason_porn"), Button.inline("👶 Child Abuse", data=b"reason_child")],
                    [Button.inline("©️ Copyright", data=b"reason_copyright")],
                    [Button.inline("🔙 Kembali", data=b"rep_start")]
                ]
                await e.reply(text, buttons=btns)

    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
