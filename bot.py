import os
import json
import subprocess
import threading
import time
import asyncio
import psutil
import requests
import shutil
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ============================================================
#  КОНФИГ
# ============================================================
TOKEN      = os.environ.get("MASTER_TOKEN", "8787496445:AAFKrV_Lm_55YriYb8Y6KVG56_HPEbv74ns")
ADMIN_ID   = 7424107874
BOTS_FILE  = "bots.json"
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
BOTS_DIR   = "bots"
_app_ref   = None

os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)

# ============================================================
#  FLASK
# ============================================================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Master Bot is running!", 200

@flask_app.route("/health")
def health():
    return {"status": "ok", "bots": len(load_bots())}, 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

def keep_alive():
    if not RENDER_URL:
        return
    while True:
        try:
            requests.get(f"{RENDER_URL}/health", timeout=10)
        except Exception:
            pass
        time.sleep(30)

# ============================================================
#  ИДОРАКУНИИ БОТҲО
# ============================================================
def load_bots() -> dict:
    if not os.path.exists(BOTS_FILE):
        return {}
    with open(BOTS_FILE, "r") as f:
        return json.load(f)

def save_bots(bots: dict):
    with open(BOTS_FILE, "w") as f:
        json.dump(bots, f, indent=2)

processes: dict = {}

def is_running(pid) -> bool:
    try:
        return bool(pid) and psutil.pid_exists(int(pid)) and \
               psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False

def _start_bot(name: str, cmd: str):
    try:
        log  = open(f"logs/{name}.log", "a")
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=log, stderr=subprocess.STDOUT,
            cwd=os.path.join(BOTS_DIR, name)
        )
        processes[name] = proc
        bots = load_bots()
        if name in bots:
            bots[name]["pid"] = proc.pid
            save_bots(bots)
        return proc.pid
    except Exception as e:
        print(f"[ERROR] {name}: {e}")
        return None

def _stop_bot(name: str):
    proc = processes.get(name)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        processes.pop(name, None)
    bots = load_bots()
    if name in bots:
        bots[name]["pid"] = None
        save_bots(bots)

# ============================================================
#  HELPERS
# ============================================================
HEADER = (
    "╔══════════════════════════╗\n"
    "║   🤖  MASTER  BOT  🤖   ║\n"
    "╚══════════════════════════╝\n"
)

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def bot_icon(name):
    pid = load_bots().get(name, {}).get("pid")
    return "🟢" if is_running(pid) else "🔴"

def main_menu_text():
    bots  = load_bots()
    total = len(bots)
    alive = sum(1 for b in bots.values() if is_running(b.get("pid")))
    return (
        f"{HEADER}\n"
        f"👑 <b>Администратор панел</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Ботҳои умумӣ : <b>{total}</b>\n"
        f"🟢 Фаъол         : <b>{alive}</b>\n"
        f"🔴 Хомӯш         : <b>{total - alive}</b>\n"
        f"🕒 Вақт           : <code>{now_str()}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 Файлҳоро фирист → тугмаи <b>Тамом</b> зан!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Амалро интихоб кунед 👇"
    )

def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Рӯйхати ботҳо",  callback_data="list"),
            InlineKeyboardButton("📊 Вазъияти сервер", callback_data="server_status"),
        ],
        [
            InlineKeyboardButton("▶️ Ҳама оғоз",       callback_data="start_all"),
            InlineKeyboardButton("⏹ Ҳама бандкун",     callback_data="stop_all"),
        ],
        [
            InlineKeyboardButton("🔄 Ҳама рестарт",    callback_data="restart_all"),
            InlineKeyboardButton("🔃 Навсозӣ",         callback_data="refresh"),
        ],
    ])

# ============================================================
#  ВАҚТ ТАҲЛИЛ
# ============================================================
def parse_duration(text: str) -> int:
    text = text.strip().lower()
    if text == "0":
        return 0
    import re
    total   = 0
    mapping = [
        (r"(\d+)\s*y\b",  365 * 24 * 3600),
        (r"(\d+)\s*mo\b", 30  * 24 * 3600),
        (r"(\d+)\s*d\b",  24  * 3600),
        (r"(\d+)\s*ch\b", 3600),
        (r"(\d+)\s*mi\b", 60),
    ]
    for pattern, mult in mapping:
        for m in re.finditer(pattern, text):
            total += int(m.group(1)) * mult
    return total

def seconds_to_human(s: int) -> str:
    if s == 0:
        return "♾ Бе маҳдудият"
    parts = []
    for unit, label in [(365*24*3600,"сол"),(30*24*3600,"моҳ"),
                        (24*3600,"рӯз"),(3600,"соат"),(60,"дақиқа")]:
        if s >= unit:
            parts.append(f"{s//unit} {label}")
            s %= unit
    return " ".join(parts)

# ============================================================
#  AUTO STOP
# ============================================================
async def auto_stop_bot(app, bot_name: str, seconds: int, chat_id: int):
    await asyncio.sleep(seconds)
    bots = load_bots()
    if bot_name in bots and is_running(bots[bot_name].get("pid")):
        _stop_bot(bot_name)
        human = seconds_to_human(seconds)
        try:
            await app.bot.send_message(
                chat_id=chat_id, parse_mode="HTML",
                text=(
                    f"⏰ <b>Вақт тамом шуд!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 Бот: <b>{bot_name}</b>\n"
                    f"🕒 Вақти кор: <code>{human}</code>\n"
                    f"🔴 Бот <b>худкор хомӯш шуд!</b>"
                )
            )
        except Exception:
            pass

# ============================================================
#  GUARD
# ============================================================
def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("⛔ Дастрасӣ нест!")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Танҳо Admin!", show_alert=True)
            return
        return await func(update, ctx)
    return wrapper

# ============================================================
#  /start
# ============================================================
@admin_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_html(main_menu_text(), reply_markup=main_menu_kb())

# ============================================================
#  ФАЙЛҲО ҚАБУЛ КАРДАН (ҲАР НАВЪ)
# ============================================================
@admin_only
async def file_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    # Сессияи upload оғоз кун
    if "upload_session" not in ctx.user_data:
        ctx.user_data["upload_session"] = {
            "files": [],
            "bot_name": None
        }

    session   = ctx.user_data["upload_session"]
    file_name = doc.file_name
    file_id   = doc.file_id

    # Ба рӯйхат илова кун
    session["files"].append({"name": file_name, "file_id": file_id})
    count = len(session["files"])

    # Рӯйхати файлҳои фиристодашуда
    file_list = "\n".join(
        f"  {'✅'} <code>{f['name']}</code>"
        for f in session["files"]
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Тамом — оғоз кун!", callback_data="upload_done")],
        [InlineKeyboardButton("🗑 Ҳама файлро пок кун", callback_data="upload_clear")],
    ])

    await update.message.reply_html(
        f"{HEADER}\n"
        f"📦 <b>{count} файл қабул шуд:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{file_list}\n\n"
        f"📎 Боз файл фирист ё тугмаи <b>Тамом</b> зан 👇",
        reply_markup=kb
    )

# ============================================================
#  CALLBACK HANDLER
# ============================================================
@admin_only
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    if data in ("refresh", "main"):
        ctx.user_data.clear()
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    elif data == "list":
        await show_bot_list(q)

    elif data == "server_status":
        await show_server_status(q)

    elif data == "start_all":
        bots    = load_bots()
        started = 0
        for name, info in bots.items():
            if not is_running(info.get("pid")):
                _start_bot(name, info["cmd"])
                started += 1
        await q.answer(f"✅ {started} бот оғоз шуд!", show_alert=True)
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    elif data == "stop_all":
        stopped = len(processes)
        for name in list(processes.keys()):
            _stop_bot(name)
        await q.answer(f"⏹ {stopped} бот хомӯш шуд!", show_alert=True)
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    elif data == "restart_all":
        bots = load_bots()
        for name, info in bots.items():
            _stop_bot(name)
            time.sleep(0.3)
            _start_bot(name, info["cmd"])
        await q.answer(f"🔄 {len(bots)} бот рестарт шуд!", show_alert=True)
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    # ── UPLOAD ТАМОМ ──────────────────────────────────────
    elif data == "upload_done":
        session = ctx.user_data.get("upload_session", {})
        files   = session.get("files", [])
        if not files:
            await q.answer("❌ Аввал файл фирист!", show_alert=True)
            return

        file_list = "\n".join(f"  📄 <code>{f['name']}</code>" for f in files)
        ctx.user_data["step"] = "ask_name"

        await q.edit_message_text(
            f"{HEADER}\n"
            f"📦 <b>Файлҳои қабулшуда:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{file_list}\n\n"
            f"✏️ <b>Номи ботро нависед</b>\n"
            f"(барои папка ва лог)\n\n"
            f"Мисол: <code>mybot</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Бозгашт", callback_data="upload_clear")
            ]])
        )

    elif data == "upload_clear":
        ctx.user_data.clear()
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    elif data.startswith("bot_"):
        await show_bot_detail(q, data[4:])

    elif data.startswith("start_"):
        name = data[6:]
        bots = load_bots()
        if name in bots:
            _start_bot(name, bots[name]["cmd"])
        await show_bot_detail(q, name)

    elif data.startswith("stop_"):
        _stop_bot(data[5:])
        await show_bot_detail(q, data[5:])

    elif data.startswith("restart_"):
        name = data[8:]
        bots = load_bots()
        if name in bots:
            _stop_bot(name)
            time.sleep(0.3)
            _start_bot(name, bots[name]["cmd"])
        await show_bot_detail(q, name)

    elif data.startswith("delete_"):
        name = data[7:]
        _stop_bot(name)
        bots = load_bots()
        path = os.path.join(BOTS_DIR, name)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
        bots.pop(name, None)
        save_bots(bots)
        await q.answer(f"🗑 {name} ҳазф шуд!", show_alert=True)
        await show_bot_list(q)

# ============================================================
#  ПАЁМИ МАТНӢ — қадамҳо
# ============================================================
@admin_only
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step    = ctx.user_data.get("step")
    text    = update.message.text.strip()
    session = ctx.user_data.get("upload_session", {})

    # ── ҚАДАМИ 1: Номи бот ────────────────────────────────
    if step == "ask_name":
        bot_name = text.replace(" ", "_")
        ctx.user_data["upload_session"]["bot_name"] = bot_name
        ctx.user_data["step"] = "ask_cmd"

        file_list = "\n".join(
            f"  📄 <code>{f['name']}</code>"
            for f in session["files"]
        )

        await update.message.reply_html(
            f"{HEADER}\n"
            f"✅ Ном: <b>{bot_name}</b>\n\n"
            f"📦 Файлҳо:\n{file_list}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"▶️ <b>Start командро нависед:</b>\n\n"
            f"Мисол:\n"
            f"<code>python bot.py</code>\n"
            f"<code>python3 main.py</code>\n"
            f"<code>node index.js</code>\n"
            f"<code>bash start.sh</code>"
        )
        return

    # ── ҚАДАМИ 2: Start command ───────────────────────────
    if step == "ask_cmd":
        ctx.user_data["upload_session"]["cmd"] = text
        ctx.user_data["step"] = "ask_time"

        await update.message.reply_html(
            f"{HEADER}\n"
            f"✅ Команда: <code>{text}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ <b>Чанд вақт бот кор кунад?</b>\n\n"
            f"<code>1y</code>   — 1 сол\n"
            f"<code>1mo</code>  — 1 моҳ\n"
            f"<code>1d</code>   — 1 рӯз\n"
            f"<code>1ch</code>  — 1 соат\n"
            f"<code>30mi</code> — 30 дақиқа\n"
            f"<code>0</code>    — бе маҳдудият ♾\n\n"
            f"Мисол: <code>2d 6ch</code>"
        )
        return

    # ── ҚАДАМИ 3: Вақт → оғоз ────────────────────────────
    if step == "ask_time":
        seconds  = parse_duration(text)
        session  = ctx.user_data.get("upload_session", {})
        bot_name = session.get("bot_name")
        cmd      = session.get("cmd")
        files    = session.get("files", [])
        chat_id  = update.message.chat_id

        if not bot_name or not cmd or not files:
            await update.message.reply_text("❌ Хатогӣ! /start ба кун")
            ctx.user_data.clear()
            return

        ctx.user_data.clear()
        human = seconds_to_human(seconds)

        # ── АНИМАЦИЯ ──────────────────────────────────────
        msg = await update.message.reply_html(
            f"{HEADER}\n"
            f"📥 <b>Файлҳо дарёфт шуд...</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Ном    : <code>{bot_name}</code>\n"
            f"▶️ Команда: <code>{cmd}</code>\n"
            f"⏰ Вақт   : <code>{human}</code>\n\n"
            f"⏳ Лутфан интизор шавед..."
        )

        # Папка созед
        bot_dir = os.path.join(BOTS_DIR, bot_name)
        os.makedirs(bot_dir, exist_ok=True)

        await asyncio.sleep(1)
        await msg.edit_text(
            f"{HEADER}\n"
            f"💾 <b>Файлҳо сервер захира мешаванд...</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Ном    : <code>{bot_name}</code>",
            parse_mode="HTML"
        )

        # Ҳама файлҳоро download кун
        saved = []
        for f in files:
            try:
                tg_file   = await update.get_bot().get_file(f["file_id"])
                save_path = os.path.join(bot_dir, f["name"])
                await tg_file.download_to_drive(save_path)
                saved.append(f["name"])
            except Exception as e:
                print(f"[DL ERROR] {f['name']}: {e}")

        await asyncio.sleep(1)
        await msg.edit_text(
            f"{HEADER}\n"
            f"📂 <b>Файлҳои захирашуда:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(f"  ✅ <code>{s}</code>" for s in saved) +
            f"\n\n⚙️ <b>Бот оғоз мешавад...</b>",
            parse_mode="HTML"
        )
        await asyncio.sleep(1)

        # Агар бот пештар буд
        bots = load_bots()
        if bot_name in bots:
            _stop_bot(bot_name)
            await asyncio.sleep(0.5)

        bots[bot_name] = {
            "path":  bot_dir,
            "cmd":   cmd,
            "pid":   None,
            "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "timer": seconds,
        }
        save_bots(bots)
        pid = _start_bot(bot_name, cmd)

        await asyncio.sleep(2)
        await msg.edit_text(
            f"{HEADER}\n"
            f"🔍 <b>Вазъият тафтиш мешавад...</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 Ном: <code>{bot_name}</code>",
            parse_mode="HTML"
        )
        await asyncio.sleep(2)

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Рӯйхат", callback_data="list"),
            InlineKeyboardButton("🏠 Меню",   callback_data="main"),
        ]])

        file_list_str = "\n".join(f"  📄 <code>{s}</code>" for s in saved)

        if pid and is_running(pid):
            timer_line = f"⏰ Таймер : <code>{human}</code>" if seconds > 0 else "♾ Таймер : <b>Бе маҳдудият</b>"
            await msg.edit_text(
                f"╔══════════════════════════╗\n"
                f"║  ✅  БОТ ФАОЛ ШУД!  ✅  ║\n"
                f"╚══════════════════════════╝\n\n"
                f"🤖 Ном     : <b>{bot_name}</b>\n"
                f"▶️ Команда : <code>{cmd}</code>\n"
                f"🆔 PID     : <code>{pid}</code>\n"
                f"🟢 Вазъ    : <b>Фаъол</b>\n"
                f"{timer_line}\n"
                f"🕒 Вақт    : <code>{now_str()}</code>\n\n"
                f"📦 Файлҳо:\n{file_list_str}",
                parse_mode="HTML", reply_markup=kb
            )
            if seconds > 0 and _app_ref:
                asyncio.create_task(
                    auto_stop_bot(_app_ref, bot_name, seconds, chat_id)
                )
        else:
            await msg.edit_text(
                f"╔══════════════════════════╗\n"
                f"║  ⚠️  ХАТОГӢ ЮЗ ДОД  ⚠️  ║\n"
                f"╚══════════════════════════╝\n\n"
                f"🤖 Ном  : <b>{bot_name}</b>\n"
                f"▶️ Команда: <code>{cmd}</code>\n"
                f"🔴 Вазъ : <b>Оғоз нашуд</b>\n"
                f"📋 Лог  : <code>logs/{bot_name}.log</code>",
                parse_mode="HTML", reply_markup=kb
            )
        return

    # ── Дигар ─────────────────────────────────────────────
    await update.message.reply_html(
        "📎 Файлҳоро фирист ва тугмаи <b>Тамом</b> зан!\n\nЁ /start ба кун.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Меню", callback_data="main")
        ]])
    )

# ============================================================
#  РӮЙХАТИ БОТҲО
# ============================================================
async def show_bot_list(q):
    bots = load_bots()
    if not bots:
        await q.edit_message_text(
            f"{HEADER}\n📋 <b>Ботҳо мавҷуд нест</b>\n\n"
            "📎 Файлҳоро фирист!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Бозгашт", callback_data="main")
            ]])
        )
        return

    rows = []
    for name in bots:
        rows.append([InlineKeyboardButton(
            f"{bot_icon(name)} {name}", callback_data=f"bot_{name}"
        )])
    rows.append([InlineKeyboardButton("🔙 Бозгашт", callback_data="main")])

    text = f"{HEADER}\n📋 <b>Рӯйхати ботҳо</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for name in bots:
        text += f"{bot_icon(name)} <b>{name}</b>\n"

    await q.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows)
    )

# ============================================================
#  ТАФСИЛОТИ БОТ
# ============================================================
async def show_bot_detail(q, name: str):
    bots = load_bots()
    info = bots.get(name)
    if not info:
        await q.answer("❌ Бот ёфт нашуд!", show_alert=True)
        return

    pid     = info.get("pid")
    running = is_running(pid)

    try:
        proc = psutil.Process(int(pid)) if running else None
        cpu  = f"{proc.cpu_percent(interval=0.1):.1f}%" if proc else "—"
        mem  = f"{proc.memory_info().rss/1024/1024:.1f} MB" if proc else "—"
    except Exception:
        cpu = mem = "—"

    icon = "🟢" if running else "🔴"
    text = (
        f"{HEADER}"
        f"🤖 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▶️ Команда : <code>{info.get('cmd','—')}</code>\n"
        f"🔵 Вазъ    : {icon} {'Фаъол' if running else 'Хомӯш'}\n"
        f"🆔 PID     : <code>{pid or '—'}</code>\n"
        f"🖥 CPU     : <code>{cpu}</code>\n"
        f"💾 RAM     : <code>{mem}</code>\n"
        f"📅 Илова   : <code>{info.get('added','—')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    btns = (
        [
            InlineKeyboardButton("⏹ Бандкун", callback_data=f"stop_{name}"),
            InlineKeyboardButton("🔄 Рестарт", callback_data=f"restart_{name}"),
        ] if running else [
            InlineKeyboardButton("▶️ Оғоз кун", callback_data=f"start_{name}"),
            InlineKeyboardButton("🗑 Ҳазф кун",  callback_data=f"delete_{name}"),
        ]
    )
    await q.edit_message_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            btns,
            [InlineKeyboardButton("🔙 Рӯйхат", callback_data="list")]
        ])
    )

# ============================================================
#  ВАЗЪИЯТИ СЕРВЕР
# ============================================================
async def show_server_status(q):
    cpu_p  = psutil.cpu_percent(interval=1)
    ram    = psutil.virtual_memory()
    disk   = psutil.disk_usage("/")
    uptime = time.time() - psutil.boot_time()
    h, r   = divmod(int(uptime), 3600)
    m, s   = divmod(r, 60)

    def bar(p, w=10):
        f = int(p/100*w)
        return "█"*f + "░"*(w-f)

    await q.edit_message_text(
        f"{HEADER}"
        f"📊 <b>Вазъияти сервер</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 CPU  : <code>{bar(cpu_p)} {cpu_p:.1f}%</code>\n"
        f"💾 RAM  : <code>{bar(ram.percent)} {ram.percent:.1f}%</code>\n"
        f"         {ram.used//1024//1024} MB / {ram.total//1024//1024} MB\n"
        f"💿 DISK : <code>{bar(disk.percent)} {disk.percent:.1f}%</code>\n"
        f"⏱ Uptime: <code>{h}с {m}д {s}сон</code>\n"
        f"🕒 Вақт : <code>{now_str()}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔃 Навсозӣ", callback_data="server_status"),
            InlineKeyboardButton("🔙 Бозгашт", callback_data="main"),
        ]])
    )

# ============================================================
#  АСОСӢ
# ============================================================
async def main():
    global _app_ref

    threading.Thread(target=run_flask,   daemon=True).start()
    threading.Thread(target=keep_alive,  daemon=True).start()

    for name, info in load_bots().items():
        bot_dir = os.path.join(BOTS_DIR, name)
        if os.path.exists(bot_dir):
            print(f"[AUTO-START] {name}")
            _start_bot(name, info.get("cmd", ""))

    app = Application.builder().token(TOKEN).build()
    _app_ref = app

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, file_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Master Bot оғоз шуд!")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
