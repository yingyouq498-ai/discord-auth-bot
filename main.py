# main.py（修正版 nuke）
import os
import asyncio
import logging
import threading
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

ROLE_BASE_NAME = "PrankRole"
ROLE_COUNT = 5
CHANNEL_BASE_NAME = "prank-channel"
CHANNEL_COUNT = 5
CHANNEL_MESSAGE = "テストメッセージ！"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
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
        await channel.delete(reason="Requested by nuke command")
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

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")

# --- 修正版 nuke ---
@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    me = guild.me or guild.get_member(bot.user.id)
    if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels and me.guild_permissions.send_messages):
        await ctx.send("Bot に必要な権限がありません（Manage Roles / Manage Channels / Send Messages）。")
        return

    await ctx.send("⚙️ nuke を開始します：ロール作成 → チャンネル削除 → チャンネル作成 → メッセージ送信")

    # --- バックアップ ---
    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = None
    try:
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("=== NUKE BACKUP ===")
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
        logger.exception("バックアップ作成に失敗しました: %s", e)
        backup_channel = None

    # --- Step 1: Create roles ---
    created_roles = []
    existing_roles = len(guild.roles)
    max_roles = 250
    available_slots = max_roles - existing_roles
    to_create = min(ROLE_COUNT, max(0, available_slots))
    if to_create > 0:
        await ctx.send(f"🔨 ロールを {to_create} 個作成します...")
        for i in range(1, to_create + 1):
            name = ROLE_BASE_NAME  # 同名で作る場合
            # 安全に重複回避する場合は下を使用
            # name = f"{ROLE_BASE_NAME}-{i}"
            try:
                r = await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="nuke auto-create roles")
                created_roles.append(r)
            except Exception as e:
                logger.exception("ロール作成失敗: %s", e)
            await asyncio.sleep(0.08)

    # --- Step 2: Delete all channels ---
    await ctx.send("🧹 全チャンネルを削除中...")
    channels_to_delete = [c for c in guild.channels if backup_channel is None or c.id != backup_channel.id]
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]

    async def delete_group(channels):
        for group in chunk_list(channels, 10):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(0.08)

    await delete_group(non_categories)
    await delete_group(categories)

    # --- Step 3: Create channels ---
    await ctx.send(f"🆕 チャンネルを {CHANNEL_COUNT} 個作成します...")
    created_channels = []
    for i in range(1, CHANNEL_COUNT + 1):
        # 同名チャンネルでも作れるようにインデックス付与
        name = f"{CHANNEL_BASE_NAME}-{i}"
        try:
            nc = await guild.create_text_channel(name)
            created_channels.append(nc)
        except Exception as e:
            logger.exception("チャンネル作成失敗: %s", e)
        await asyncio.sleep(0.08)

    # --- Step 4: Send message ---
    await ctx.send("✉️ 各チャンネルへメッセージ送信中...")
    for c in created_channels:
        await asyncio.sleep(0.1)  # 作成後に少し待つ
        try:
            await c.send(CHANNEL_MESSAGE)
        except Exception as e:
            logger.exception("メッセージ送信失敗: %s", e)

    if backup_channel:
        await backup_channel.send("✅ nuke フロー完了")

    await ctx.send("✅ nuke の実行が完了しました。")

# --- エントリポイント ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server starting in background thread...")

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません。")
    bot.run(TOKEN)
