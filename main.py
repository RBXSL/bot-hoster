# ------------------ IMPORTS ------------------
import os
import sys
import threading
import datetime
import json
from flask import Flask
import discord
from discord.ext import commands, tasks

# ------------------ CONFIG ------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN environment variable not set")
    sys.exit(1)

DATA_FILE = "activity_logs.json"
INACTIVITY_THRESHOLD = 60  # seconds

# ------------------ FLASK KEEP-ALIVE ------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ------------------ DISCORD BOT ------------------
intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ LOAD/INIT LOGS ------------------
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            raw_logs = json.load(f)
            activity_logs = {}
            for user_id, data in raw_logs.items():
                activity_logs[int(user_id)] = {
                    "total_seconds": data.get("total_seconds", 0),
                    "daily_seconds": data.get("daily_seconds", 0),
                    "weekly_seconds": data.get("weekly_seconds", 0),
                    "monthly_seconds": data.get("monthly_seconds", 0),
                    "last_activity": datetime.datetime.fromisoformat(data["last_activity"]) if data.get("last_activity") else None,
                    "online": data.get("online", False),
                    "last_message": datetime.datetime.fromisoformat(data["last_message"]) if data.get("last_message") else None
                }
    except Exception:
        print("⚠️ Corrupt activity_logs.json, resetting...")
        activity_logs = {}
else:
    activity_logs = {}

def save_logs():
    serializable_logs = {}
    for user_id, data in activity_logs.items():
        serializable_logs[str(user_id)] = {
            "total_seconds": data["total_seconds"],
            "daily_seconds": data.get("daily_seconds", 0),
            "weekly_seconds": data.get("weekly_seconds", 0),
            "monthly_seconds": data.get("monthly_seconds", 0),
            "last_activity": data["last_activity"].isoformat() if data["last_activity"] else None,
            "online": data["online"],
            "last_message": data["last_message"].isoformat() if data.get("last_message") else None
        }
    with open(DATA_FILE, "w") as f:
        json.dump(serializable_logs, f, indent=4)

# ------------------ HELPERS ------------------
def format_time(seconds: int):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def update_user_time(user_id: int):
    now = datetime.datetime.now(datetime.timezone.utc)
    user = activity_logs.get(user_id)
    if not user or not user["online"] or not user["last_message"]:
        return
    elapsed = (now - user["last_message"]).total_seconds()
    if elapsed <= INACTIVITY_THRESHOLD:
        user["total_seconds"] += int(elapsed)
        user["daily_seconds"] += int(elapsed)
        user["weekly_seconds"] += int(elapsed)
        user["monthly_seconds"] += int(elapsed)
        user["last_activity"] = now

def check_inactivity():
    now = datetime.datetime.now(datetime.timezone.utc)
    for user in activity_logs.values():
        if user["online"] and user["last_message"]:
            if (now - user["last_message"]).total_seconds() > INACTIVITY_THRESHOLD:
                user["online"] = False

# ------------------ EVENTS ------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not update_all_users.is_running():
        update_all_users.start()
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"⚠️ Slash sync failed: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    user_id = message.author.id
    now = datetime.datetime.now(datetime.timezone.utc)
    if user_id not in activity_logs:
        activity_logs[user_id] = {
            "total_seconds": 0,
            "daily_seconds": 0,
            "weekly_seconds": 0,
            "monthly_seconds": 0,
            "last_activity": None,
            "online": True,
            "last_message": now
        }
    else:
        activity_logs[user_id]["online"] = True
        activity_logs[user_id]["last_message"] = now
    save_logs()

# ------------------ BACKGROUND TASK ------------------
@tasks.loop(seconds=10)
async def update_all_users():
    check_inactivity()
    for user_id, user in activity_logs.items():
        if user["online"]:
            update_user_time(user_id)
    save_logs()

# ------------------ SLASH COMMAND ------------------
@bot.tree.command(name="timetrack", description="Check a user's tracked online/offline time")
async def timetrack(interaction: discord.Interaction, member: discord.Member):
    user_id = member.id
    if user_id not in activity_logs:
        await interaction.response.send_message("❌ No activity recorded for this user.", ephemeral=True)
        return

    user = activity_logs[user_id]
    update_user_time(user_id)

    online_time = user["total_seconds"]
    daily_time = user["daily_seconds"]
    weekly_time = user["weekly_seconds"]
    monthly_time = user["monthly_seconds"]

    now = datetime.datetime.now(datetime.timezone.utc)
    offline_seconds = 0
    if not user["online"] and user.get("last_message"):
        offline_seconds = int((now - user["last_message"]).total_seconds())

    msg = f"⏳ **{member.display_name}**\n"
    msg += f"🟢 Online time: {format_time(online_time)}\n"
    msg += f"⚫ Offline for: {format_time(offline_seconds)}\n"
    msg += f"📆 Daily: {format_time(daily_time)}, Weekly: {format_time(weekly_time)}, Monthly: {format_time(monthly_time)}"

    await interaction.response.send_message(msg)

# ------------------ RUN BOT ------------------
bot.run(TOKEN)
