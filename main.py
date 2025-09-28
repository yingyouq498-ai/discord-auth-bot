# main.py
import os
import asyncio
import logging
import json
from datetime import datetime
from typing import List

import discord
from discord.ext import commands
from flask import Flask, jsonify

# ---------------- CONFIG (調整可) ----------------
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

CHANNEL_MESSAGES = [
    "メッセージ1: こんにちは！",
    "メッセージ2: テストです。",
    "メッセージ3: お遊びモード。",
    "メッセージ4: これで終わり。",
    "メッセージ5: またね！"
]

# Parallelism / timing (tune if you hit rate limits)
DELETE_CHUNK_SIZE = 8
DELETE_CHUNK_SLEEP = 0.08

CREATE_CHUNK_SIZE = 6
CREATE_CHUNK_SLEEP = 0.12

# Message sending (round-robin) params
MSG_CHUNK_SIZE = 10
MSG_INTER_CHUNK_SLEEP = 0.01
MSG_INTER_ROUND_SLEEP = 0.02
MSG_MAX_RETRIES = 3

# After full deletion wait (important)
POST_DELETE_WAIT = 3.0
# -------------------------------------------------

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
    except discord.errors.NotFound:
        logger.warning(f"Already deleted: {getattr(channel, 'name', channel)}")
    except discord.errors.Forbidden:
        logger.exception(f"Forbidden to delete channel: {getattr(channel, 'name', channel)}")
    except Exception as e:
        logger.exception(f"Failed to delete channel {getattr(channel, 'name', channel)}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        logger.info(f"Created channel: {name} ({ch.id})")
        return ch
    except discord.errors.Forbidden:
        logger.exception(f"Forbidden to create channel: {name}")
        raise
    except Exception as e:
        logger.exception(f"Failed to create channel {name}: {e}")
        raise

async def safe_send(ch: discord.TextChannel, content: str, max_retries=MSG_MAX_RETRIES):
    retries = 0
    while True:
        try:
            await ch.send(content)
            return
        except discord.errors.NotFound:
            logger.warning(f"send: channel not found {getattr(ch, 'name', ch)}")
            return
        except discord.errors.Forbidden:
            logger.warning(f"send: forbidden {getattr(ch, 'name', ch)}")
            return
        except discord.errors.HTTPException as e:
            # Could be 429 or transient; backoff
            retries += 1
            if retries > max_retries:
                logger.exception(f"send failed after retries ({getattr(ch, 'name', ch)}): {e}")
                return
            backoff = 0.5 * (2 ** (retries - 1))
            logger.warning(f"HTTPException on send to {getattr(ch, 'name', ch)}; retry {retries} after {backoff}s")
            await asyncio.sleep(backoff)
        except Exception as e:
            logger.exception(f"Unexpected send error ({getattr(ch, 'name', ch)}): {e}")
            return

# Round-robin + chunked parallel send
async def send_messages_round_robin(channels: List[discord.TextChannel], messages: List[str]):
    if not channels:
        logger.warning("No channels to send to")
        return
    n_channels = len(channels)
    n_rounds = len(messages)
    for r in range(n_rounds):
        msg = messages[r]
        # chunked parallel across channels
        for i in range(0, n_channels, MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            # send concurrently to this chunk
            await asyncio.gather(*(safe_send(ch, msg) for ch in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

# permission check helper
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

    # quick permission check (before destructive ops)
    if not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません (Manage Channels / Manage Roles / Send Messages)。")
        return

    # Create backup channel first and use it for notifications. Exclude it from deletion.
    try:
        backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("⚙️ nuke 開始（backup channel created）")
    except Exception as e:
        logger.exception("バックアップチャンネル作成失敗: %s", e)
        await ctx.send("バックアップチャンネル作れないため中止します（権限確認してください）。")
        return

    # 1) DELETE: delete all channels except backup_channel, in chunked parallel
    try:
        channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
        await backup_channel.send(f"🧹 削除対象チャンネル: {len(channels_to_delete)} 件。削除を開始します...")
        for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(DELETE_CHUNK_SLEEP)
        await backup_channel.send("🗑️ 削除処理完了。Discord 側反映待ち...")
    except Exception as e:
        logger.exception("削除フェーズ例外: %s", e)
        await backup_channel.send(f"削除フェーズで例外が発生しました: {e}")
        # continue to wait and try create anyway

    # wait for Discord internal state to settle
    await asyncio.sleep(POST_DELETE_WAIT)

    # 2) CREATE roles (fast, sequential small sleep)
    created_roles = []
    await backup_channel.send(f"🔨 ロールを {ROLE_COUNT} 個作成します...")
    for i in range(1, ROLE_COUNT + 1):
        name = f"{ROLE_BASE}-{i}"
        try:
            r = await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="nuke bulk role")
            created_roles.append(r)
        except Exception as e:
            logger.exception("ロール作成失敗: %s", e)
            await backup_channel.send(f"ロール作成失敗: {name}: {e}")
        await asyncio.sleep(0.03)
    await backup_channel.send(f"🔨 ロール作成完了: {len(created_roles)} 個")

    # 3) CREATE channels (chunked parallel creation)
    created_channels: List[discord.TextChannel] = []
    await backup_channel.send(f"🆕 チャンネルを {CHANNEL_COUNT} 個作成します（チャンクサイズ {CREATE_CHUNK_SIZE}）...")
    create_tasks = []
    # prepare creation coroutines grouped by chunks
    names = [f"{CHANNEL_BASE}-{i}" for i in range(1, CHANNEL_COUNT + 1)]
    for i in range(0, len(names), CREATE_CHUNK_SIZE):
        chunk_names = names[i:i+CREATE_CHUNK_SIZE]
        # create coroutines for this chunk
        coros = [safe_create_channel(guild, nm) for nm in chunk_names]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                # log already done inside safe_create_channel, just notify
                await backup_channel.send(f"チャンネル作成で例外: {res}")
            else:
                created_channels.append(res)
        await asyncio.sleep(CREATE_CHUNK_SLEEP)
    await backup_channel.send(f"🆕 チャンネル作成完了: {len(created_channels)} 件")

    # slight wait for Discord to reflect newly created channels
    await asyncio.sleep(0.5)

    # 4) SEND messages using round-robin + chunked parallel
    await backup_channel.send(f"✉️ 各チャンネルへ {len(CHANNEL_MESSAGES)} ラウンドでメッセージ送信（chunk {MSG_CHUNK_SIZE}）...")
    try:
        await send_messages_round_robin(created_channels, CHANNEL_MESSAGES)
    except Exception as e:
        logger.exception("メッセージ送信フェーズ例外: %s", e)
        await backup_channel.send(f"メッセージ送信でエラー: {e}")

    await backup_channel.send("✅ nuke 全工程が完了しました。")

# Entrypoint
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask started")

    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
