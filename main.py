# main.py（削除後待機で確実版 nuke）
import os
import asyncio
import logging
from datetime import datetime
import discord
from discord.ext import commands
from flask import Flask, jsonify

# ------------------ 設定 ------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True

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
# ---------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready()}), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def admin_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
        await ctx.send("管理者のみ実行可能です。")
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")

# --- nuke コマンド ---
@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    guild = ctx.guild
    me = guild.me or guild.get_member(bot.user.id)

    if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels and me.guild_permissions.send_messages):
        await ctx.send("Bot に必要な権限がありません（Manage Roles / Manage Channels / Send Messages）")
        return

    await ctx.send("⚙️ nuke 開始...")

    # 1. ロール作成
    await ctx.send(f"🔨 ロールを {ROLE_COUNT} 個作成...")
    for i in range(1, ROLE_COUNT + 1):
        name = f"{ROLE_BASE}-{i}"
        try:
            await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="nuke role create")
        except Exception as e:
            logger.exception(f"ロール作成失敗: {e}")
        await asyncio.sleep(0.05)

    # 2. 全チャンネル削除
    await ctx.send("🧹 全チャンネルを削除...")
    channels_to_delete = [c for c in guild.channels]
    for c in channels_to_delete:
        try:
            await c.delete()
        except Exception as e:
            logger.exception(f"チャンネル削除失敗: {e}")
        await asyncio.sleep(0.05)

    # 削除完了後に長めに待機
    await asyncio.sleep(3)

    # 3. チャンネル作成
    await ctx.send(f"🆕 チャンネルを {CHANNEL_COUNT} 個作成...")
    created_channels = []
    for i in range(1, CHANNEL_COUNT + 1):
        name = f"{CHANNEL_BASE}-{i}"
        try:
            ch = await guild.create_text_channel(name)
            created_channels.append(ch)
        except Exception as e:
            logger.exception(f"チャンネル作成失敗: {name}: {e}")
        await asyncio.sleep(0.3)

    # 4. メッセージ送信
    await ctx.send("✉️ 各チャンネルにメッセージ送信...")
    for ch in created_channels:
        for msg in CHANNEL_MESSAGES:
            try:
                await ch.send(msg)
            except Exception as e:
                logger.exception(f"メッセージ送信失敗 ({ch.name}): {e}")
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.03)

    await ctx.send("✅ nuke 完了！")

# エントリポイント
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません")
    bot.run(TOKEN)
