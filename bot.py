import os
import json
import subprocess
import threading
import time
import asyncio
import psutil
import requests
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

os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)

# ============================================================
#  FLASK — барои Render зинда монад
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
        return pid and psutil.pid_exists(int(pid)) and \
               psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False

def _start_bot(name: str, path: str):
    try:
        log = open(f"logs/{name}.log", "a")
        proc = subprocess.Popen(["python3", path], stdout=log, stderr=subprocess.STDOUT)
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
    bots = load_bots()
    pid = bots.get(name, {}).get("pid")
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
        f"📎 Файли .py фирист — бот ба таври худкор илова мешавад!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Амалро интихоб кунед 👇"
    )

def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Рӯйхати ботҳо",    callback_data="list"),
            InlineKeyboardButton("📊 Вазъияти сервер",   callback_data="server_status"),
        ],
        [
            InlineKeyboardButton("▶️ Ҳама оғоз",         callback_data="start_all"),
            InlineKeyboardButton("⏹ Ҳама бандкун",       callback_data="stop_all"),
        ],
        [
            InlineKeyboardButton("🔄 Ҳама рестарт",      callback_data="restart_all"),
            InlineKeyboardButton("🔃 Навсозӣ",           callback_data="refresh"),
        ],
    ])

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
    await update.message.reply_html(main_menu_text(), reply_markup=main_menu_kb())

# ============================================================
#  ФАЙЛ ҚАБУЛ КАРДАН — АСОСИИ НАВИ КОД
# ============================================================
@admin_only
async def file_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    # Танҳо .py файл
    if not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ Танҳо файлҳои .py қабул мешавад!")
        return

    bot_name = doc.file_name.replace(".py", "")

    # ── Анимацияи загрузка ──────────────────────────────
    frames = ["⏳", "🔄", "📥", "💾", "⚙️"]
    steps = [
        "📥 Файл дарёфт шуд...",
        "💾 Файл сервер захира мешавад...",
        "⚙️ Бот оғоз мешавад...",
        "🔍 Вазъият тафтиш мешавад...",
    ]

    msg = await update.message.reply_html(
        f"<b>{frames[0]} Файл қабул шуд!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Ном: <code>{doc.file_name}</code>\n\n"
        f"{steps[0]}"
    )

    await asyncio.sleep(1)
    await msg.edit_text(
        f"<b>🔄 Коркард мешавад...</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Ном: <code>{doc.file_name}</code>\n\n"
        f"{steps[1]}",
        parse_mode="HTML"
    )

    # ── Файлро сервер сохт ──────────────────────────────
    try:
        file = await ctx.bot.get_file(doc.file_id)
        save_path = os.path.join(BOTS_DIR, doc.file_name)
        await file.download_to_drive(save_path)
    except Exception as e:
        await msg.edit_text(f"❌ Файл сохта нашуд:\n<code>{e}</code>", parse_mode="HTML")
        return

    await asyncio.sleep(1)
    await msg.edit_text(
        f"<b>⚙️ Бот оғоз мешавад...</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Ном: <code>{doc.file_name}</code>\n\n"
        f"{steps[2]}",
        parse_mode="HTML"
    )

    # ── Агар бот пештар буд, рестарт ──────────────────
    bots = load_bots()
    if bot_name in bots:
        _stop_bot(bot_name)
        await asyncio.sleep(1)

    # ── Бот оғоз кардан ────────────────────────────────
    bots[bot_name] = {
        "path":  save_path,
        "pid":   None,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_bots(bots)
    pid = _start_bot(bot_name, save_path)

    await asyncio.sleep(2)
    await msg.edit_text(
        f"<b>🔍 Вазъият тафтиш мешавад...</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Ном: <code>{doc.file_name}</code>",
        parse_mode="HTML"
    )

    await asyncio.sleep(2)

    # ── Натиҷа ─────────────────────────────────────────
    if pid and is_running(pid):
        status_text = (
            f"╔══════════════════════════╗\n"
            f"║  ✅  БОТ ФАОЛ ШУД!  ✅  ║\n"
            f"╚══════════════════════════╝\n\n"
            f"🤖 Ном   : <b>{bot_name}</b>\n"
            f"📁 Файл  : <code>{save_path}</code>\n"
            f"🆔 PID   : <code>{pid}</code>\n"
            f"🟢 Вазъ  : <b>Фаъол</b>\n"
            f"🕒 Вақт  : <code>{now_str()}</code>\n"
        )
    else:
        status_text = (
            f"╔══════════════════════════╗\n"
            f"║  ⚠️  ХАТОГӢ ЮЗ ДОД  ⚠️  ║\n"
            f"╚══════════════════════════╝\n\n"
            f"🤖 Ном   : <b>{bot_name}</b>\n"
            f"📁 Файл  : <code>{save_path}</code>\n"
            f"🔴 Вазъ  : <b>Оғоз нашуд</b>\n"
            f"📋 Логро тафтиш кун: <code>logs/{bot_name}.log</code>\n"
        )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Рӯйхат",   callback_data="list"),
            InlineKeyboardButton("🏠 Меню",      callback_data="main"),
        ]
    ])
    await msg.edit_text(status_text, parse_mode="HTML", reply_markup=kb)

# ============================================================
#  CALLBACK HANDLER
# ============================================================
@admin_only
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    if data in ("refresh", "main"):
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    elif data == "list":
        await show_bot_list(q)

    elif data == "server_status":
        await show_server_status(q)

    elif data == "start_all":
        bots = load_bots()
        started = 0
        for name, info in bots.items():
            if not is_running(info.get("pid")):
                _start_bot(name, info["path"])
                started += 1
        await q.answer(f"✅ {started} бот оғоз шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    elif data == "stop_all":
        stopped = len(processes)
        for name in list(processes.keys()):
            _stop_bot(name)
        await q.answer(f"⏹ {stopped} бот хомӯш шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    elif data == "restart_all":
        bots = load_bots()
        for name, info in bots.items():
            _stop_bot(name)
            time.sleep(0.3)
            _start_bot(name, info["path"])
        await q.answer(f"🔄 {len(bots)} бот рестарт шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    elif data.startswith("bot_"):
        await show_bot_detail(q, data[4:])

    elif data.startswith("start_"):
        name = data[6:]
        bots = load_bots()
        if name in bots:
            _start_bot(name, bots[name]["path"])
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
            _start_bot(name, bots[name]["path"])
        await show_bot_detail(q, name)

    elif data.startswith("delete_"):
        name = data[7:]
        _stop_bot(name)
        bots = load_bots()
        # Файлро ҳам ҳазф кун
        path = bots.get(name, {}).get("path", "")
        if path and os.path.exists(path):
            os.remove(path)
        bots.pop(name, None)
        save_bots(bots)
        await q.answer(f"🗑 {name} ҳазф шуд!", show_alert=True)
        await show_bot_list(q)

# ============================================================
#  РӮЙХАТИ БОТҲО
# ============================================================
async def show_bot_list(q):
    bots = load_bots()
    if not bots:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Бозгашт", callback_data="main")
        ]])
        await q.edit_message_text(
            f"{HEADER}\n📋 <b>Ботҳо мавҷуд нест</b>\n\n"
            "📎 Файли .py -ро ба чат фирист!",
            parse_mode="HTML", reply_markup=kb
        )
        return

    rows = []
    for name in bots:
        rows.append([InlineKeyboardButton(
            f"{bot_icon(name)} {name}", callback_data=f"bot_{name}"
        )])
    rows.append([InlineKeyboardButton("🔙 Бозгашт", callback_data="main")])

    text = f"{HEADER}\n📋 <b>Рӯйхати ботҳо</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for name, info in bots.items():
        text += f"{bot_icon(name)} <b>{name}</b>\n"

    await q.edit_message_text(text, parse_mode="HTML",
                               reply_markup=InlineKeyboardMarkup(rows))

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
    icon    = "🟢" if running else "🔴"

    try:
        proc = psutil.Process(int(pid)) if running else None
        cpu  = f"{proc.cpu_percent(interval=0.1):.1f}%" if proc else "—"
        mem  = f"{proc.memory_info().rss / 1024 / 1024:.1f} MB" if proc else "—"
    except Exception:
        cpu = mem = "—"

    text = (
        f"{HEADER}"
        f"🤖 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 Файл  : <code>{info['path']}</code>\n"
        f"🔵 Вазъ  : {icon} {'Фаъол' if running else 'Хомӯш'}\n"
        f"🆔 PID   : <code>{pid or '—'}</code>\n"
        f"🖥 CPU   : <code>{cpu}</code>\n"
        f"💾 RAM   : <code>{mem}</code>\n"
        f"📅 Илова : <code>{info.get('added', '—')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if running:
        btns = [
            InlineKeyboardButton("⏹ Бандкун",  callback_data=f"stop_{name}"),
            InlineKeyboardButton("🔄 Рестарт",  callback_data=f"restart_{name}"),
        ]
    else:
        btns = [
            InlineKeyboardButton("▶️ Оғоз кун", callback_data=f"start_{name}"),
            InlineKeyboardButton("🗑 Ҳазф кун",  callback_data=f"delete_{name}"),
        ]

    kb = InlineKeyboardMarkup([btns,
        [InlineKeyboardButton("🔙 Рӯйхат", callback_data="list")]
    ])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

# ============================================================
#  ВАЗЪИЯТИ СЕРВЕР
# ============================================================
async def show_server_status(q):
    cpu_p  = psutil.cpu_percent(interval=1)
    ram    = psutil.virtual_memory()
    disk   = psutil.disk_usage("/")
    uptime = time.time() - psutil.boot_time()
    h, rem = divmod(int(uptime), 3600)
    m, s   = divmod(rem, 60)

    def bar(p, w=10):
        f = int(p / 100 * w)
        return "█" * f + "░" * (w - f)

    text = (
        f"{HEADER}"
        f"📊 <b>Вазъияти сервер</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 CPU  : <code>{bar(cpu_p)} {cpu_p:.1f}%</code>\n"
        f"💾 RAM  : <code>{bar(ram.percent)} {ram.percent:.1f}%</code>\n"
        f"         {ram.used//1024//1024} MB / {ram.total//1024//1024} MB\n"
        f"💿 DISK : <code>{bar(disk.percent)} {disk.percent:.1f}%</code>\n"
        f"⏱ Uptime: <code>{h}с {m}д {s}сон</code>\n"
        f"🕒 Вақт : <code>{now_str()}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔃 Навсозӣ", callback_data="server_status"),
        InlineKeyboardButton("🔙 Бозгашт", callback_data="main"),
    ]])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

# ============================================================
#  ПАЁМИ МАТНӢ
# ============================================================
@admin_only
async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📎 Барои илова кардани бот — файли <code>.py</code> -ро фирист!\n\n"
        "Ё /start ба кун.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Меню", callback_data="main")
        ]])
    )

# ============================================================
#  АСОСӢ
# ============================================================
async def main():
    # Flask
    threading.Thread(target=run_flask, daemon=True).start()
    # Keep-alive
    threading.Thread(target=keep_alive, daemon=True).start()

    # Ботҳои аввалро оғоз кун
    for name, info in load_bots().items():
        if os.path.exists(info["path"]):
            print(f"[AUTO-START] {name}")
            _start_bot(name, info["path"])

    app = Application.builder().token(TOKEN).build()
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
