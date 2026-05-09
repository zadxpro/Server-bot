import os
import json
import subprocess
import threading
import time
import psutil
import requests
from datetime import datetime
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ============================================================
#  КОНФИГ
# ============================================================
TOKEN       = os.environ.get("MASTER_TOKEN", "8787496445:AAFKrV_Lm_55YriYb8Y6KVG56_HPEbv74ns")
ADMIN_ID    = 7424107874
BOTS_FILE   = "bots.json"
RENDER_URL  = os.environ.get("RENDER_EXTERNAL_URL", "")

# ============================================================
#  ФЛASK — барои Render зинда монад
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
    """Ҳар 30 сония серверро ping мекунад то Render хомӯш накунад"""
    if not RENDER_URL:
        print("[KEEP-ALIVE] RENDER_EXTERNAL_URL танзим нашудааст, skip.")
        return
    while True:
        try:
            r = requests.get(f"{RENDER_URL}/health", timeout=10)
            print(f"[KEEP-ALIVE] ✅ ping → {r.status_code}")
        except Exception as e:
            print(f"[KEEP-ALIVE] ❌ хато: {e}")
        time.sleep(30)  # 30 сония

# ============================================================
#  ИДОРАКУНИИ БОТҲО (JSON)
# ============================================================
def load_bots() -> dict:
    if not os.path.exists(BOTS_FILE):
        return {}
    with open(BOTS_FILE, "r") as f:
        return json.load(f)

def save_bots(bots: dict):
    with open(BOTS_FILE, "w") as f:
        json.dump(bots, f, indent=2)

# Процессҳои зинда
processes: dict[str, subprocess.Popen] = {}

def is_running(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False

# ============================================================
#  EMOJI & HELPERS
# ============================================================
STATUS_ON  = "🟢"
STATUS_OFF = "🔴"
STATUS_ERR = "🟡"

def bot_status_icon(name: str) -> str:
    bots = load_bots()
    info = bots.get(name, {})
    pid  = info.get("pid")
    if pid and is_running(pid):
        return STATUS_ON
    return STATUS_OFF

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")

# ============================================================
#  ТЕКСТҲОИ ЗЕБО
# ============================================================
HEADER = (
    "╔══════════════════════════╗\n"
    "║   🤖  MASTER  BOT  🤖   ║\n"
    "╚══════════════════════════╝\n"
)

def main_menu_text() -> str:
    bots  = load_bots()
    total = len(bots)
    alive = sum(1 for b in bots.values() if b.get("pid") and is_running(b["pid"]))
    return (
        f"{HEADER}\n"
        f"👑 <b>Администратор панел</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Ботҳои умумӣ : <b>{total}</b>\n"
        f"🟢 Фаъол         : <b>{alive}</b>\n"
        f"🔴 Хомӯш         : <b>{total - alive}</b>\n"
        f"🕒 Вақт           : <code>{now_str()}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Амалро интихоб кунед 👇"
    )

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Рӯйхати ботҳо",  callback_data="list"),
            InlineKeyboardButton("➕ Бот илова кун",   callback_data="add_prompt"),
        ],
        [
            InlineKeyboardButton("▶️ Ҳама ботро оғоз", callback_data="start_all"),
            InlineKeyboardButton("⏹ Ҳама ботро бандкун", callback_data="stop_all"),
        ],
        [
            InlineKeyboardButton("🔄 Ҳама ботро рестарт", callback_data="restart_all"),
            InlineKeyboardButton("📊 Вазъияти сервер",    callback_data="server_status"),
        ],
        [
            InlineKeyboardButton("🔃 Навсозии меню",  callback_data="refresh"),
        ],
    ])

# ============================================================
#  GUARD — танҳо ADMIN
# ============================================================
def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = (update.effective_user or update.callback_query.from_user).id
        if uid != ADMIN_ID:
            if update.message:
                await update.message.reply_text("⛔ Шумо дастрасӣ надоред!")
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
    await update.message.reply_html(
        main_menu_text(),
        reply_markup=main_menu_kb()
    )

# ============================================================
#  CALLBACK HANDLER
# ============================================================
@admin_only
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()

    # ── REFRESH / ГЛАВНАЯ ──────────────────────────────────
    if data in ("refresh", "main"):
        await q.edit_message_text(
            main_menu_text(), parse_mode="HTML",
            reply_markup=main_menu_kb()
        )

    # ── РӮЙХАТ ────────────────────────────────────────────
    elif data == "list":
        await show_bot_list(q)

    # ── ВАЗЪИЯТИ СЕРВЕР ───────────────────────────────────
    elif data == "server_status":
        await show_server_status(q)

    # ── ИЛОВА КАРДАНИ БОТ ─────────────────────────────────
    elif data == "add_prompt":
        ctx.user_data["waiting"] = "add_bot"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Бозгашт", callback_data="main")
        ]])
        await q.edit_message_text(
            f"{HEADER}\n"
            "➕ <b>Бот илова кардан</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Формат паёми худро бифиристед:\n\n"
            "<code>ном | масири_файл.py</code>\n\n"
            "Мисол:\n"
            "<code>shopbot | bots/shop_bot.py</code>",
            parse_mode="HTML", reply_markup=kb
        )

    # ── START ALL ─────────────────────────────────────────
    elif data == "start_all":
        bots = load_bots()
        started = 0
        for name, info in bots.items():
            pid = info.get("pid")
            if not (pid and is_running(pid)):
                _start_bot(name, info["path"])
                started += 1
        await q.answer(f"✅ {started} бот оғоз шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    # ── STOP ALL ──────────────────────────────────────────
    elif data == "stop_all":
        bots = load_bots()
        stopped = 0
        for name in list(processes.keys()):
            _stop_bot(name)
            stopped += 1
        await q.answer(f"⏹ {stopped} бот хомӯш шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    # ── RESTART ALL ───────────────────────────────────────
    elif data == "restart_all":
        bots = load_bots()
        for name, info in bots.items():
            _stop_bot(name)
            time.sleep(0.5)
            _start_bot(name, info["path"])
        await q.answer(f"🔄 {len(bots)} бот рестарт шуд!", show_alert=True)
        await q.edit_message_text(main_menu_text(), parse_mode="HTML",
                                   reply_markup=main_menu_kb())

    # ── АМАЛҲОИ БОТ ───────────────────────────────────────
    elif data.startswith("bot_"):
        name = data[4:]
        await show_bot_detail(q, name)

    elif data.startswith("start_"):
        name = data[6:]
        bots = load_bots()
        if name in bots:
            _start_bot(name, bots[name]["path"])
            await q.answer(f"✅ {name} оғоз шуд!", show_alert=True)
        await show_bot_detail(q, name)

    elif data.startswith("stop_"):
        name = data[5:]
        _stop_bot(name)
        await q.answer(f"⏹ {name} хомӯш шуд!", show_alert=True)
        await show_bot_detail(q, name)

    elif data.startswith("restart_"):
        name = data[8:]
        bots = load_bots()
        if name in bots:
            _stop_bot(name)
            time.sleep(0.5)
            _start_bot(name, bots[name]["path"])
            await q.answer(f"🔄 {name} рестарт шуд!", show_alert=True)
        await show_bot_detail(q, name)

    elif data.startswith("delete_"):
        name = data[7:]
        _stop_bot(name)
        bots = load_bots()
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
            InlineKeyboardButton("➕ Бот илова кун", callback_data="add_prompt"),
            InlineKeyboardButton("🔙 Бозгашт",       callback_data="main"),
        ]])
        await q.edit_message_text(
            f"{HEADER}\n📋 <b>Ботҳо мавҷуд нест</b>\n\nАввал бот илова кунед!",
            parse_mode="HTML", reply_markup=kb
        )
        return

    rows = []
    for name in bots:
        icon = bot_status_icon(name)
        rows.append([InlineKeyboardButton(
            f"{icon} {name}", callback_data=f"bot_{name}"
        )])
    rows.append([
        InlineKeyboardButton("➕ Бот илова кун", callback_data="add_prompt"),
        InlineKeyboardButton("🔙 Бозгашт",       callback_data="main"),
    ])

    text = f"{HEADER}\n📋 <b>Рӯйхати ботҳо</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for name, info in bots.items():
        icon = bot_status_icon(name)
        text += f"{icon} <code>{name}</code> — <i>{info['path']}</i>\n"

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
    running = pid and is_running(pid)
    icon    = STATUS_ON if running else STATUS_OFF
    added   = info.get("added", "—")

    try:
        proc = psutil.Process(pid) if running else None
        cpu  = f"{proc.cpu_percent(interval=0.1):.1f}%" if proc else "—"
        mem  = f"{proc.memory_info().rss / 1024 / 1024:.1f} MB" if proc else "—"
    except Exception:
        cpu = mem = "—"

    text = (
        f"{HEADER}\n"
        f"🤖 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 Файл   : <code>{info['path']}</code>\n"
        f"🔵 Вазъ   : {icon} {'Фаъол' if running else 'Хомӯш'}\n"
        f"🆔 PID    : <code>{pid or '—'}</code>\n"
        f"🖥 CPU    : <code>{cpu}</code>\n"
        f"💾 RAM    : <code>{mem}</code>\n"
        f"📅 Илова  : <code>{added}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    if running:
        action_btns = [
            InlineKeyboardButton("⏹ Бандкун",  callback_data=f"stop_{name}"),
            InlineKeyboardButton("🔄 Рестарт",  callback_data=f"restart_{name}"),
        ]
    else:
        action_btns = [
            InlineKeyboardButton("▶️ Оғоз кун", callback_data=f"start_{name}"),
            InlineKeyboardButton("🗑 Ҳазф кун",  callback_data=f"delete_{name}"),
        ]

    kb = InlineKeyboardMarkup([
        action_btns,
        [InlineKeyboardButton("🔙 Рӯйхат", callback_data="list")],
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

    def bar(pct: float, w: int = 10) -> str:
        filled = int(pct / 100 * w)
        return "█" * filled + "░" * (w - filled)

    text = (
        f"{HEADER}\n"
        f"📊 <b>Вазъияти сервер</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖥 CPU  : <code>{bar(cpu_p)} {cpu_p:.1f}%</code>\n"
        f"💾 RAM  : <code>{bar(ram.percent)} {ram.percent:.1f}%</code>\n"
        f"         {ram.used//1024//1024} MB / {ram.total//1024//1024} MB\n"
        f"💿 DISK : <code>{bar(disk.percent)} {disk.percent:.1f}%</code>\n"
        f"         {disk.used//1024//1024//1024} GB / {disk.total//1024//1024//1024} GB\n"
        f"⏱ Uptime: <code>{h}с {m}д {s}сония</code>\n"
        f"🕒 Вақт : <code>{now_str()}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔃 Навсозӣ", callback_data="server_status"),
        InlineKeyboardButton("🔙 Бозгашт", callback_data="main"),
    ]])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

# ============================================================
#  БОТ ИЛОВА КАРДАН (ПАЁМ)
# ============================================================
@admin_only
async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("waiting") != "add_bot":
        return

    text = update.message.text.strip()
    if "|" not in text:
        await update.message.reply_html(
            "❌ Формат нодуруст!\n\n"
            "Лутфан чунин нависед:\n"
            "<code>ном | масири_файл.py</code>"
        )
        return

    parts = [p.strip() for p in text.split("|", 1)]
    name, path = parts[0], parts[1]

    if not name or not path:
        await update.message.reply_text("❌ Ном ё масир холӣ аст!")
        return

    bots = load_bots()
    bots[name] = {
        "path":  path,
        "pid":   None,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    save_bots(bots)
    ctx.user_data.pop("waiting", None)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"▶️ {name} оғоз кун", callback_data=f"start_{name}"),
            InlineKeyboardButton("📋 Рӯйхат",           callback_data="list"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="main")],
    ])
    await update.message.reply_html(
        f"✅ <b>{name}</b> илова шуд!\n\n"
        f"📁 Файл: <code>{path}</code>\n\n"
        "Ҳоло оғоз карда метавонед 👆",
        reply_markup=kb
    )

# ============================================================
#  ИДОРАКУНИИ ПРОЦЕССҲО
# ============================================================
def _start_bot(name: str, path: str):
    try:
        proc = subprocess.Popen(
            ["python3", path],
            stdout=open(f"logs/{name}.log", "a"),
            stderr=subprocess.STDOUT
        )
        processes[name] = proc
        bots = load_bots()
        if name in bots:
            bots[name]["pid"] = proc.pid
            save_bots(bots)
    except Exception as e:
        print(f"[ERROR] {name} оғоз нашуд: {e}")

def _stop_bot(name: str):
    proc = processes.get(name)
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        del processes[name]
    bots = load_bots()
    if name in bots:
        bots[name]["pid"] = None
        save_bots(bots)

# ============================================================
#  АСОСӢ
# ============================================================
import asyncio

async def main():
    # Ботҳои аввал оғоз кардан
    bots = load_bots()
    for name, info in bots.items():
        if os.path.exists(info["path"]):
            print(f"[AUTO-START] {name}")
            _start_bot(name, info["path"])

    # Telegram Application
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu",  cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, message_handler
    ))

    print("🤖 Master Bot оғоз шуд!")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)

    # Flask дар thread ҷудо
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Keep-alive барои Render
    ping_thread = threading.Thread(target=keep_alive, daemon=True)
    ping_thread.start()

    asyncio.run(main())
