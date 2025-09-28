import os
import asyncio
import logging
import threading
from typing import List
from datetime import datetime
import json

import discord
from discord.ext import commands
from flask import Flask, jsonify

# --- 設定 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

# --- Bot ---
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)

# --- Flask サーバー ---
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready()}), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- ヘルパー ---
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete(reason="Requested by bot command")
        logger.info(f"Deleted: {channel.name} ({channel.id})")
    except Exception as e:
        logger.exception(f"Failed to delete {channel}: {e}")

def admin_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
        await ctx.send("このコマンドは管理者のみ使用できます。")
        return False
    return commands.check(predicate)

# --- Bot Events ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")

# --- fastsetup コマンド ---
@bot.command(name="fastsetup")
@admin_only()
async def fastsetup(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    def check_author(m):
        return m.author == ctx.author and m.channel == ctx.channel

    # 1️⃣ ロール名
    await ctx.send("🟢 ステップ1 — 作成するロール名を改行区切りで送ってください（最大5個）。")
    try:
        msg_roles = await bot.wait_for("message", check=check_author, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send("タイムアウトしました。やり直してください。")
        return
    role_names = [line.strip() for line in msg_roles.content.splitlines() if line.strip()][:5]

    # 2️⃣ チャンネル名
    await ctx.send("🟢 ステップ2 — 作成するチャンネル名を改行区切りで送ってください（最大5個）。")
    try:
        msg_chs = await bot.wait_for("message", check=check_author, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send("タイムアウトしました。やり直してください。")
        return
    chan_names = [line.strip() for line in msg_chs.content.splitlines() if line.strip()][:5]

    # 3️⃣ メッセージ
    await ctx.send("🟢 ステップ3 — 各チャンネルに送るメッセージを1件送ってください。")
    try:
        msg_body = await bot.wait_for("message", check=check_author, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send("タイムアウトしました。やり直してください。")
        return
    message_text = msg_body.content.strip()
    if not message_text:
        await ctx.send("空のメッセージは送れません。中止します。")
        return

    # --- Backup ---
    backup_name = f"fastsetup-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = None
    try:
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("=== FASTSETUP BACKUP ===")
        roles_data = [{"name": r.name, "id": r.id, "position": r.position} for r in guild.roles]
        channels_data = [{"name": c.name, "type": str(c.type), "id": c.id} for c in guild.channels]
        payload = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "roles": roles_data,
            "channels": channels_data,
            "initiator": str(ctx.author),
        }
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        for i in range(0, len(payload_str), 1900):
            await backup_channel.send(f"```json\n{payload_str[i:i+1900]}\n```")
    except Exception as e:
        logger.exception("バックアップ作成失敗: %s", e)

    await ctx.send(f"⚙️ バックアップ完了（{backup_channel.name if backup_channel else '失敗'}）。処理開始...")

    # --- Step A: Create roles ---
    created_roles = []
    existing_roles = len(guild.roles)
    max_roles = 250
    available_slots = max_roles - existing_roles
    to_create = role_names[:max(0, available_slots)]
    for rn in to_create:
        try:
            r = await guild.create_role(name=rn, permissions=discord.Permissions.none(), reason="fastsetup create")
            created_roles.append(r)
        except Exception as e:
            logger.exception("ロール作成失敗: %s", e)
        await asyncio.sleep(0.08)

    # --- Step B: Delete all channels ---
    await ctx.send("🧹 全チャンネルを削除します...")
    channels_to_delete = [c for c in guild.channels]
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]
    async def delete_group(channels):
        for group in chunk_list(channels, 10):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(0.08)
    await delete_group(non_categories)
    await delete_group(categories)

    # --- Step C: Create channels ---
    await ctx.send(f"🆕 {len(chan_names)} 個のテキストチャンネルを作成します...")
    created_channels = []
    for cname in chan_names:
        try:
            nc = await guild.create_text_channel(cname)
            created_channels.append(nc)
        except Exception as e:
            logger.exception("チャンネル作成失敗: %s", e)
        await asyncio.sleep(0.08)

    # --- Step D: Send message ---
    await ctx.send("✉️ 各チャンネルへメッセージ送信中...")
    for c in created_channels:
        try:
            await c.send(message_text)
        except Exception as e:
            logger.exception("メッセージ送信失敗: %s", e)
        await asyncio.sleep(0.05)

    await ctx.send("✅ fastsetup 完了しました。")
# --- fastsetup 終了 ---

# --- エントリポイント ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server starting in background thread...")

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません。")
    bot.run(TOKEN)
