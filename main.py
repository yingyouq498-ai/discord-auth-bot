# main.py
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

# --- 設定（必要ならここを書き換えてね）---
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True  # コマンド受付に必要

# 動作パラメータ（ここだけ変えれば名前や数を変更可能）
ROLE_BASE_NAME = "PrankRole"      # ロールのベース名（5個作成）
ROLE_COUNT = 5
CHANNEL_BASE_NAME = "prank-channel"  # チャンネルのベース名（5個作成）
CHANNEL_COUNT = 5
CHANNEL_MESSAGE = "テストメッセージ！"  # 各チャンネルに送る本文（1件）

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

# --- Bot & Flask ---
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready(), "bot_user": str(bot.user) if bot.user else None}), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    # UptimeRobot 用のシンプルなヘルスチェック
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

# --- nuke コマンド（あなたの要求を一括で実行） ---
@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    """
    フロー:
      1) ロールを ROLE_COUNT 個作成（ベース名は ROLE_BASE_NAME、重複防止のため末尾にインデックスを付与）
      2) 全チャンネルを削除（バックアップチャンネルに構成を保存）
      3) チャンネルを CHANNEL_COUNT 個作成（ベース名は CHANNEL_BASE_NAME + index）
      4) 各チャンネルに CHANNEL_MESSAGE を1件送信
    実行は管理者/サーバー所有者のみ可能。
    """
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    # 必要権限チェック
    me = guild.me or guild.get_member(bot.user.id)
    if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels and me.guild_permissions.create_instant_invite):
        # create_instant_invite は任意のチェック。Manage Roles / Manage Channels が最低必要
        await ctx.send("Bot に必要な権限がありません（Manage Roles / Manage Channels 等）。")
        return

    await ctx.send("⚙️ nuke を開始します：ロール作成 → チャンネル削除 → チャンネル作成 → メッセージ送信")

    # --- バックアップ（簡易） ---
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
        # メッセージ分割送信
        for i in range(0, len(payload_str), 1900):
            await backup_channel.send(f"```json\n{payload_str[i:i+1900]}\n```")
    except Exception as e:
        logger.exception("バックアップ作成に失敗しました: %s", e)
        backup_channel = None

    # --- Step 1: Create roles (fast) ---
    created_roles = []
    existing_roles = len(guild.roles)
    max_roles = 250
    available_slots = max_roles - existing_roles
    to_create = min(ROLE_COUNT, max(0, available_slots))
    if to_create <= 0:
        await ctx.send("ロール作成可能枠がありません（上限に到達）。ロール作成はスキップします。")
    else:
        await ctx.send(f"🔨 ロールを {to_create} 個作成します（ベース名: {ROLE_BASE_NAME}）...")
        # 名前を完全に同じにするよりも、失敗回避のためインデックスを付ける実装にしてます
        for i in range(1, to_create + 1):
            name = ROLE_BASE_NAME  # ユーザーの要望で「全部同じでいい」ならこの行をそのまま使う（重複可）
            # 安全に重複回避したい場合は下の行を使う:
            # name = f"{ROLE_BASE_NAME}-{i}"
            try:
                r = await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="nuke auto-create roles")
                created_roles.append(r)
            except Exception as e:
                logger.exception("ロール作成失敗: %s", e)
            await asyncio.sleep(0.08)  # 小刻みなウェイト

    # --- Step 2: Delete all channels (fast, parallel) ---
    await ctx.send("🧹 全チャンネルを削除しています...")
    channels_to_delete = [c for c in guild.channels]
    # keep the backup channel if it exists so we can read the backup after deletion
    if backup_channel:
        channels_to_delete = [c for c in channels_to_delete if c.id != backup_channel.id]

    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]

    async def delete_group(channels):
        for group in chunk_list(channels, 10):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(0.08)

    # Delete text/voice first, then categories
    await delete_group(non_categories)
    await delete_group(categories)

    # --- Step 3: Create channels ---
    await ctx.send(f"🆕 チャンネルを {CHANNEL_COUNT} 個作成します（ベース名: {CHANNEL_BASE_NAME}）...")
    created_channels = []
    for i in range(1, CHANNEL_COUNT + 1):
        # 同じ名前で良いと言われたのでベース名のみ使うが、チャンネル名重複で失敗する可能性があるため
        # 安全にしたい場合は下行をコメントイン： name = f"{CHANNEL_BASE_NAME}-{i}"
        name = CHANNEL_BASE_NAME
        try:
            nc = await guild.create_text_channel(name)
            created_channels.append(nc)
        except Exception as e:
            logger.exception("チャンネル作成失敗: %s", e)
        await asyncio.sleep(0.08)

    # --- Step 4: Send one message per created channel ---
    await ctx.send("✉️ 各チャンネルへメッセージを送信しています...")
    for c in created_channels:
        try:
            await c.send(CHANNEL_MESSAGE)
        except Exception as e:
            logger.exception("メッセージ送信失敗: %s", e)
        await asyncio.sleep(0.05)

    # 最終通知（できればバックアップチャンネルへ）
    try:
        if backup_channel:
            await backup_channel.send("✅ nuke フローが完了しました。")
    except Exception:
        pass

    await ctx.send("✅ nuke の実行が完了しました。")

# --- エントリポイント ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server starting in background thread...")

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません。")
    bot.run(TOKEN)
