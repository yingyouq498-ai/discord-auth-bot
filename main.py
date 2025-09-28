# main.py
import os
import asyncio
import logging
import threading
import json
from datetime import datetime
from typing import List

import discord
from discord.ext import commands
from flask import Flask, jsonify

# ------------------ 設定（ここだけ編集して使ってね） ------------------
TOKEN = os.environ.get("DISCORD_TOKEN")  # 環境変数で設定
COMMAND_PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True  # コマンド受付のために有効に（Developer PortalでONに）

# 動作パラメータ
ROLE_BASE = "ozeumember"
ROLE_COUNT = 5

CHANNEL_BASE = "prank-channel"
CHANNEL_COUNT = 20

# 各チャンネルに送るメッセージ（ここに 5 件を書いておく）
CHANNEL_MESSAGES = [
    "メッセージ1: こんにちは！",
    "メッセージ2: テストです。",
    "メッセージ3: お遊びモード。",
    "メッセージ4: これで終わり。",
    "メッセージ5: またね！"
]
# -------------------------------------------------------------------

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")

# Bot & Flask
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=INTENTS)
app = Flask(__name__)

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

# Helpers
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete(reason="Requested by nuke command")
        logger.info(f"Deleted channel: {channel.name} ({channel.id})")
    except Exception as e:
        logger.exception(f"Failed to delete {channel}: {e}")

def admin_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
        await ctx.send("このコマンドは管理者またはサーバー所有者のみ実行できます。")
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")

# メインコマンド（!nuke）
@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    me = guild.me or guild.get_member(bot.user.id)
    # 必要最低権限チェック
    if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels and me.guild_permissions.send_messages):
        await ctx.send("Bot に必要な権限がありません（Manage Roles / Manage Channels / Send Messages）。")
        return

    await ctx.send("⚙️ nuke 開始：ロール作成 → チャンネル削除 → チャンネル作成 → 各チャンネルへメッセージ送信")

    # 1) バックアップチャンネルを作成して現在の構成を保存（残す）
    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = None
    try:
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("=== NUKE BACKUP ===")
        data = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "roles": [{"name": r.name, "id": r.id, "position": r.position} for r in guild.roles],
            "channels": [{"name": c.name, "type": str(c.type), "id": c.id} for c in guild.channels],
            "initiator": str(ctx.author)
        }
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        for i in range(0, len(payload), 1900):
            await backup_channel.send(f"```json\n{payload[i:i+1900]}\n```")
    except Exception as e:
        logger.exception("バックアップ作成失敗: %s", e)
        backup_channel = None

    # 2) ロールを高速に作成（5個） -- 並列で投げるが小ウェイトを置く
    created_roles = []
    await ctx.send(f"🔨 ロールを {ROLE_COUNT} 個作成します（ベース: {ROLE_BASE}）...")
    role_tasks = []
    for i in range(1, ROLE_COUNT + 1):
        name = f"{ROLE_BASE}-{i}"  # ozeumember-1 ... -5
        coro = guild.create_role(name=name, permissions=discord.Permissions.none(), reason="nuke bulk role create")
        role_tasks.append(coro)
    # 少数なので一括 gather してから短いsleep
    try:
        created = await asyncio.gather(*role_tasks, return_exceptions=True)
        for res in created:
            if isinstance(res, Exception):
                logger.exception("role create error: %s", res)
            else:
                created_roles.append(res)
        await asyncio.sleep(0.1)
    except Exception as e:
        logger.exception("ロール作成で例外: %s", e)

    # 3) 全チャンネル削除（バックアップチャンネルは残す）
    await ctx.send("🧹 全チャンネルを削除します（バックアップチャンネルは残します）...")
    channels_to_delete = [c for c in guild.channels if (backup_channel is None or c.id != backup_channel.id)]
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]

    # 削除は並列でチャンキング（例: 10 個ずつ並列）
    for group in chunk_list(non_categories, 10):
        await asyncio.gather(*(safe_delete_channel(c) for c in group))
        await asyncio.sleep(0.08)
    # カテゴリは後で消す
    for group in chunk_list(categories, 10):
        await asyncio.gather(*(safe_delete_channel(c) for c in group))
        await asyncio.sleep(0.08)

    # 重要: 削除完了を待ってから次へ（ここで確実に全削除が終わる）
    await asyncio.sleep(0.3)

    # 4) チャンネルを高速に作成（20個） -- チャンネル名はユニークにする
    await ctx.send(f"🆕 テキストチャンネルを {CHANNEL_COUNT} 個作成します（ベース: {CHANNEL_BASE}）...")
    created_channels: List[discord.TextChannel] = []
    create_tasks = []
    for i in range(1, CHANNEL_COUNT + 1):
        name = f"{CHANNEL_BASE}-{i}"  # prank-channel-1 ... -20
        create_tasks.append(guild.create_text_channel(name))

    # chunked gather（10ずつ）で叩く
    for group in chunk_list(create_tasks, 10):
        results = await asyncio.gather(*group, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.exception("チャンネル作成失敗: %s", res)
            else:
                created_channels.append(res)
        await asyncio.sleep(0.08)

    # 少し待って Discord 側に反映させる
    await asyncio.sleep(0.2)

    # 5) 各チャンネルへメッセージを高速に送信（各チャンネルに CHANNEL_MESSAGES の順で 5 件）
    await ctx.send("✉️ 各チャンネルへメッセージを送信します...")
    # 各チャンネルごとに逐次送信（各チャンネル内は順番を守る）
    for ch in created_channels:
        for msg in CHANNEL_MESSAGES:
            try:
                await ch.send(msg)
            except Exception as e:
                logger.exception("メッセージ送信失敗 (%s): %s", ch.name if hasattr(ch, "name") else str(ch), e)
            # チャンネル内の連続送信は短いウェイト
            await asyncio.sleep(0.05)
        # チャンネル間にも短いウェイト
        await asyncio.sleep(0.03)

    # 6) 完了通知
    try:
        if backup_channel:
            await backup_channel.send("✅ nuke フローが完了しました。")
    except Exception:
        pass

    await ctx.send("✅ nuke 実行が完了しました（完成）。")

# エントリポイント
if __name__ == "__main__":
    # Flask をバックグラウンドで起動（UptimeRobot 用）
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask starting...")

    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
