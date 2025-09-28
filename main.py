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

# Behavioral params
ROLE_BASE = "ozeumember"
ROLE_COUNT = 5
CHANNEL_BASE = "prank-channel"
CHANNEL_COUNT = 20

REPEAT_MESSAGE = "@everyone テスト通知です！"
REPEAT_COUNT = 250  # 各チャンネルに送信する回数

# Parallelism / timing
DELETE_CHUNK_SIZE = 8
DELETE_CHUNK_SLEEP = 0.08
CREATE_CHUNK_SIZE = 6
CREATE_CHUNK_SLEEP = 0.12
MSG_CHUNK_SIZE = 10
MSG_INTER_CHUNK_SLEEP = 0.01
MSG_INTER_ROUND_SLEEP = 0.02
POST_DELETE_WAIT = 3.0
# ---------------------------------------

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready(), "bot_user": str(bot.user) if bot.user else None}), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# helpers
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete()
        logger.info(f"Deleted: {getattr(channel, 'name', repr(channel))} ({channel.id})")
    except Exception as e:
        logger.warning(f"Delete failed {getattr(channel, 'name', channel)}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        logger.info(f"Created channel: {name} ({ch.id})")
        await asyncio.sleep(0.2)  # 権限反映待ち
        return ch
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

async def safe_send(ch: discord.TextChannel, content: str, max_retries=3):
    if not ch or not content:
        return
    retries = 0
    while True:
        try:
            await ch.send(str(content)[:2000])
            return
        except discord.errors.Forbidden:
            logger.warning(f"Forbidden: cannot send to {ch.name}")
            return
        except discord.errors.HTTPException as e:
            retries += 1
            if retries > max_retries:
                logger.warning(f"HTTPException send failed {ch.name}: {e}")
                return
            await asyncio.sleep(0.5 * (2 ** (retries - 1)))
        except Exception as e:
            logger.exception(f"Unexpected send error {ch.name}: {e}")
            return

async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    if not channels or not msg:
        return
    for _ in range(repeat):
        for i in range(0, len(channels), MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            await asyncio.gather(*(safe_send(ch, msg) for ch in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages

def admin_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
        await ctx.send("管理者またはサーバー所有者のみ実行可能です。")
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")

@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return
    if not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません。")
        return

    # backup channel
    try:
        backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("⚙️ nuke 開始（backup channel created）")
    except Exception as e:
        await ctx.send(f"バックアップチャンネル作成失敗: {e}")
        return

    # DELETE
    channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
    await backup_channel.send(f"🧹 削除対象: {len(channels_to_delete)} 件")
    for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
        await asyncio.gather(*(safe_delete_channel(c) for c in group))
        await asyncio.sleep(DELETE_CHUNK_SLEEP)
    await asyncio.sleep(POST_DELETE_WAIT)

    # CREATE roles
    created_roles = []
    await backup_channel.send(f"🔨 ロール {ROLE_COUNT} 個作成")
    for i in range(1, ROLE_COUNT + 1):
        try:
            r = await guild.create_role(name=f"{ROLE_BASE}-{i}", permissions=discord.Permissions.none())
            created_roles.append(r)
        except Exception as e:
            await backup_channel.send(f"ロール作成失敗 {i}: {e}")
        await asyncio.sleep(0.03)
    await backup_channel.send(f"🔨 ロール作成完了 {len(created_roles)} 個")

    # CREATE channels
    created_channels: List[discord.TextChannel] = []
    await backup_channel.send(f"🆕 チャンネル {CHANNEL_COUNT} 個作成")
    names = [f"{CHANNEL_BASE}-{i}" for i in range(1, CHANNEL_COUNT + 1)]
    for i in range(0, len(names), CREATE_CHUNK_SIZE):
        chunk_names = names[i:i+CREATE_CHUNK_SIZE]
        results = await asyncio.gather(*(safe_create_channel(guild, nm) for nm in chunk_names))
        created_channels.extend([ch for ch in results if ch is not None])
        await asyncio.sleep(CREATE_CHUNK_SLEEP)
    await backup_channel.send(f"🆕 チャンネル作成完了 {len(created_channels)} 件")

    # SEND repeated messages
    await backup_channel.send(f"✉️ 各チャンネルに同じメッセージを {REPEAT_COUNT} 回送信開始")
    await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)
    await backup_channel.send("✅ nuke 全工程完了")

# Entrypoint
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask started")

    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
