# ------------------ IMPORTS ------------------
import os
import threading
from flask import Flask
import discord
from discord.ext import commands, tasks
import datetime
import json
import sys

# ------------------ CONFIG ------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN environment variable not set")
    sys.exit(1)

DATA_FILE = "activity_logs.json"
TIMEZONES = {
    "UTC": datetime.timezone.utc,
    "EST": datetime.timezone(datetime.timedelta(hours=-5)),
    "PST": datetime.timezone(datetime.timedelta(hours=-8)),
    "CET": datetime.timezone(datetime.timedelta(hours=1)),
}
INACTIVITY_THRESHOLD = 60  # 1 minute inactivity timeout
DAY_SECONDS = 24 * 3600
WEEK_SECONDS = 7 * DAY_SECONDS
MONTH_SECONDS = 30 * DAY_SECONDS

GUILD_ID = 123456789012345678  # replace with your server ID
MUTE_ROLE_ID = 1410423854563721287
LOG_CHANNEL_ID = 1403422664521023648

# ------------------ FLASK PORT BINDING ------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask).start()

# ------------------ DISCORD BOT ------------------
intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ TIME TRACKING ------------------
activity_logs = {}
last_messages = {}

# Load existing logs
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            raw_logs = json.load(f)
            activity_logs = {
                int(user_id): {
                    "total_seconds": data.get("total_seconds", 0),
                    "offline_seconds": data.get("offline_seconds", 0),
                    "daily_seconds": data.get("daily_seconds", 0),
                    "weekly_seconds": data.get("weekly_seconds", 0),
                    "monthly_seconds": data.get("monthly_seconds", 0),
                    "last_activity": datetime.datetime.fromisoformat(data["last_activity"]) if data.get("last_activity") else None,
                    "online": data.get("online", False),
                    "first_seen": datetime.datetime.fromisoformat(data.get("first_seen")) if data.get("first_seen") else datetime.datetime.now(datetime.timezone.utc),
                    "daily_start": datetime.datetime.fromisoformat(data.get("daily_start")) if data.get("daily_start") else datetime.datetime.now(datetime.timezone.utc),
                    "weekly_start": datetime.datetime.fromisoformat(data.get("weekly_start")) if data.get("weekly_start") else datetime.datetime.now(datetime.timezone.utc),
                    "monthly_start": datetime.datetime.fromisoformat(data.get("monthly_start")) if data.get("monthly_start") else datetime.datetime.now(datetime.timezone.utc),
                    "offline_start": datetime.datetime.fromisoformat(data.get("offline_start")) if data.get("offline_start") else None
                }
                for user_id, data in raw_logs.items()
            }
    except Exception:
        print("⚠️ Corrupt activity_logs.json, resetting...")
        activity_logs = {}
else:
    activity_logs = {}

def save_logs():
    serializable_logs = {
        str(user_id): {
            "total_seconds": data["total_seconds"],
            "offline_seconds": data["offline_seconds"],
            "daily_seconds": data["daily_seconds"],
            "weekly_seconds": data["weekly_seconds"],
            "monthly_seconds": data["monthly_seconds"],
            "last_activity": data["last_activity"].isoformat() if data["last_activity"] else None,
            "online": data["online"],
            "first_seen": data["first_seen"].isoformat(),
            "daily_start": data["daily_start"].isoformat(),
            "weekly_start": data["weekly_start"].isoformat(),
            "monthly_start": data["monthly_start"].isoformat(),
            "offline_start": data["offline_start"].isoformat() if data["offline_start"] else None
        }
        for user_id, data in activity_logs.items()
    }
    with open(DATA_FILE, "w") as f:
        json.dump(serializable_logs, f, indent=4)

def format_time(seconds: int):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"

def convert_timezone(dt: datetime.datetime, tz_name: str):
    tz = TIMEZONES.get(tz_name.upper(), datetime.timezone.utc)
    return dt.astimezone(tz)

def update_user_time(user_id: int, delta: int):
    user_data = activity_logs.get(user_id)
    if not user_data:
        return
    user_data["total_seconds"] += delta
    user_data["daily_seconds"] += delta
    user_data["weekly_seconds"] += delta
    user_data["monthly_seconds"] += delta

def check_inactivity():
    now = datetime.datetime.now(datetime.timezone.utc)
    for user_id, data in activity_logs.items():
        if data["online"] and data["last_activity"]:
            elapsed = (now - data["last_activity"]).total_seconds()
            if elapsed > INACTIVITY_THRESHOLD:
                data["online"] = False
                data["offline_start"] = now
                data["last_activity"] = None

def reset_periods():
    now = datetime.datetime.now(datetime.timezone.utc)
    for user_id, data in activity_logs.items():
        # Daily reset
        if (now - data["daily_start"]).total_seconds() > DAY_SECONDS:
            data["daily_seconds"] = 0
            data["daily_start"] = now
        # Weekly reset
        if (now - data["weekly_start"]).total_seconds() > WEEK_SECONDS:
            data["weekly_seconds"] = 0
            data["weekly_start"] = now
        # Monthly reset
        if (now - data["monthly_start"]).total_seconds() > MONTH_SECONDS:
            data["monthly_seconds"] = 0
            data["monthly_start"] = now

# ------------------ TIME EVENTS ------------------
@bot.event
async def on_ready():
    now = datetime.datetime.now(datetime.timezone.utc)
    for guild in bot.guilds:
        for member in guild.members:
            if member.id not in activity_logs:
                activity_logs[member.id] = {
                    "total_seconds": 0,
                    "offline_seconds": 0,
                    "daily_seconds": 0,
                    "weekly_seconds": 0,
                    "monthly_seconds": 0,
                    "last_activity": now if member.status != discord.Status.offline else None,
                    "online": member.status != discord.Status.offline,
                    "first_seen": now,
                    "daily_start": now,
                    "weekly_start": now,
                    "monthly_start": now,
                    "offline_start": None
                }
    if not update_all_users.is_running():
        update_all_users.start()
    if not check_mutes.is_running():
        check_mutes.start()
    try:
        await bot.tree.sync()
        print("✅ Slash commands synced.")
    except Exception as e:
        print(f"⚠️ Slash sync failed: {e}")
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    user_id = message.author.id
    if user_id not in activity_logs:
        activity_logs[user_id] = {
            "total_seconds": 0,
            "offline_seconds": 0,
            "daily_seconds": 0,
            "weekly_seconds": 0,
            "monthly_seconds": 0,
            "last_activity": now,
            "online": True,
            "first_seen": now,
            "daily_start": now,
            "weekly_start": now,
            "monthly_start": now,
            "offline_start": None
        }
    else:
        activity_logs[user_id]["last_activity"] = now
        activity_logs[user_id]["online"] = True
        activity_logs[user_id]["offline_start"] = None  # Reset offline timer
    last_messages[user_id] = {"content": message.content, "timestamp": now}
    save_logs()

# ------------------ TIME LOOP ------------------
@tasks.loop(seconds=10)
async def update_all_users():
    now = datetime.datetime.now(datetime.timezone.utc)
    reset_periods()
    for user_id, data in activity_logs.items():
        if data["online"] and data.get("last_activity"):
            elapsed = (now - data["last_activity"]).total_seconds()
            if elapsed > 0:
                delta = int(min(elapsed, 10))
                update_user_time(user_id, delta)
            data["offline_start"] = None
        else:
            if "offline_start" in data and data["offline_start"]:
                delta_off = (now - data["offline_start"]).total_seconds()
                data["offline_seconds"] += int(delta_off)
                data["offline_start"] = now
    check_inactivity()
    save_logs()

# ------------------ SEND TIME ------------------
async def send_time(interaction, username: discord.Member, user_data, show_last_message=False, timezone="UTC"):
    status = "🟢 Online" if user_data["online"] else "⚫ Offline"
    offline_time = 0
    if not user_data["online"] and "offline_start" in user_data and user_data["offline_start"]:
        offline_time = int((datetime.datetime.now(datetime.timezone.utc) - user_data["offline_start"]).total_seconds())

    msg = f"⏳ **{username.display_name}**\n"
    msg += f"🟢 Online time: `{format_time(user_data['total_seconds'])}`\n"
    msg += f"⚫ Offline for: `{format_time(user_data['offline_seconds'] + offline_time)}`\n\n"
    msg += "📆 **Periods**\n"
    msg += f"Daily: `{format_time(user_data['daily_seconds'])}`\n"
    msg += f"Weekly: `{format_time(user_data['weekly_seconds'])}`\n"
    msg += f"Monthly: `{format_time(user_data['monthly_seconds'])}`"

    if show_last_message and username.id in last_messages:
        last_msg = last_messages[username.id]
        ts = convert_timezone(last_msg["timestamp"], timezone)
        msg += f"\n💬 Last message ({timezone}): [{ts.strftime('%Y-%m-%d %H:%M:%S')}] {last_msg['content']}"

    await interaction.response.send_message(msg)

# ------------------ TIME SLASH COMMANDS ------------------
@bot.tree.command(name="timetrack", description="Show current online/offline time")
async def timetrack(interaction: discord.Interaction, username: discord.Member, show_last_message: bool = False, timezone: str = "UTC"):
    user_data = activity_logs.get(username.id)
    if not user_data:
        await interaction.response.send_message("❌ User not found in logs.", ephemeral=True)
        return
    await send_time(interaction, username, user_data, show_last_message, timezone)

@bot.tree.command(name="weekly", description="Show weekly online time")
async def weekly(interaction: discord.Interaction, username: discord.Member):
    user_data = activity_logs.get(username.id)
    if not user_data:
        await interaction.response.send_message("❌ User not found in logs.", ephemeral=True)
        return
    await send_time(interaction, username, user_data)

@bot.tree.command(name="monthly", description="Show monthly online time")
async def monthly(interaction: discord.Interaction, username: discord.Member):
    user_data = activity_logs.get(username.id)
    if not user_data:
        await interaction.response.send_message("❌ User not found in logs.", ephemeral=True)
        return
    await send_time(interaction, username, user_data)

@bot.tree.command(name="fulltime", description="Show total online and offline time")
async def fulltime(interaction: discord.Interaction, username: discord.Member):
    user_data = activity_logs.get(username.id)
    if not user_data:
        await interaction.response.send_message("❌ User not found in logs.", ephemeral=True)
        return
    await send_time(interaction, username, user_data)

# ------------------ RMUTE SYSTEM ------------------
active_mutes = {}  # {user_id: {"end_time": datetime, "reason": str, "proof": str}}

def parse_duration(duration: str):
    if not duration:
        return 60
    try:
        unit = duration[-1]
        val = int(duration[:-1])
        if unit == "s":
            return val
        elif unit == "m":
            return val * 60
        elif unit == "h":
            return val * 3600
        elif unit == "d":
            return val * 86400
    except:
        return 60
    return 60

async def apply_mute(member: discord.Member, duration_seconds: int, reason: str, proof: str = None):
    role = member.guild.get_role(MUTE_ROLE_ID)
    if role and role not in member.roles:
        await member.add_roles(role)

    end_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=duration_seconds)
    active_mutes[member.id] = {"end_time": end_time, "reason": reason, "proof": proof}

    try:
        await member.send(f"You have been muted in {member.guild.name} until {end_time} UTC.\nReason: {reason}\nProof: {proof if proof else 'None'}")
    except:
        pass

    log_channel = member.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="🔇 User Muted", color=discord.Color.red())
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=duration_seconds)), inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if proof:
            embed.add_field(name="Proof", value=proof, inline=False)
        await log_channel.send(embed=embed)

async def remove_mute(user_id: int):
    data = active_mutes.pop(user_id, None)
    if not data:
        return
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    member = guild.get_member(user_id)
    if not member:
        return
    role = guild.get_role(MUTE_ROLE_ID)
    if role in member.roles:
        await member.remove_roles(role)
    try:
        await member.send(f"You have been unmuted in {guild.name}.")
    except:
        pass
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="✅ User Unmuted", color=discord.Color.green())
        embed.add_field(name="User", value=member.mention)
        await log_channel.send(embed=embed)

# ------------------ RMUTE LOOP ------------------
@tasks.loop(seconds=10)
async def check_mutes():
    now = datetime.datetime.utcnow()
    to_remove = [uid for uid, data in active_mutes.items() if now >= data["end_time"]]
    for uid in to_remove:
        await remove_mute(uid)

# ------------------ RMUTE COMMANDS ------------------
def has_mute_perm(ctx):
    return ctx.author.guild_permissions.mute_members

@bot.command(name="qmute")
@commands.check(has_mute_perm)
async def qmute(ctx, duration: str = None, *, reason: str = "No reason provided"):
    if not ctx.message.reference:
        await ctx.send("❌ You must reply to a message to mute a user.", delete_after=5)
        return
    replied_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    member = replied_msg.author
    dur_seconds = parse_duration(duration)
    proof = f"[Message link](https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{ctx.message.reference.message_id})"
    await apply_mute(member, dur_seconds, reason, proof)
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send(f"✅ {member.mention} has been muted.", delete_after=5)

@bot.tree.command(name="rmute", description="Mute a user by replying to a message")
async def rmute(interaction: discord.Interaction, duration: str = None, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.mute_members:
        await interaction.response.send_message("❌ You do not have permission to mute members.", ephemeral=True)
        return
    if not interaction.data.get("resolved", {}).get("messages"):
        await interaction.response.send_message("❌ You must reply to a message.", ephemeral=True)
        return
    refs = interaction.data["resolved"]["messages"]
    message_id = list(refs.keys())[0]
    channel_id = int(refs[message_id]["channel_id"])
    channel = bot.get_channel(channel_id)
    message = await channel.fetch_message(int(message_id))
    member = message.author
    dur_seconds = parse_duration(duration)
    proof = f"[Message link](https://discord.com/channels/{interaction.guild.id}/{channel.id}/{message.id})"
    await apply_mute(member, dur_seconds, reason, proof)
    await interaction.response.send_message(f"✅ {member.mention} has been muted.", ephemeral=True)

# ------------------ RUN BOT ------------------
bot.run(TOKEN)
