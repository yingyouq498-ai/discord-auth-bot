# main.py（高速化・Render対応版 nuke）
import os
import asyncio
import logging
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

    # 権限チェック
    if not (me.guild_permissions.manage_roles and me.guild_permissions.manage_channels and me.guild_permissions.send_messages):
        await ctx.send("Bot に必要な権限がありません（Manage Roles / Manage Channels / Send Messages）")
        return

    # 1. 全チャンネル削除
    channels_to_delete = [c for c in guild.channels]
    for c in channels_to_delete:
        try:
            await c.delete()
        except Exception as e:
            logger.exception(f"チャンネル削除失敗: {e}")
        await asyncio.sleep(0.05)

    # 削除反映待ち
    await asyncio.sleep(3)

    # 2. バックアップチャンネル作成（通知用）
    try:
        backup_channel = await guild.create_text_channel("nuke-backup")
        await backup_channel.send("⚙️ nuke 開始...")
    except Exception as e:
        logger.exception(f"バックアップチャンネル作成失敗: {e}")
        return  # 通知できない場合は停止

    # 3. ロール作成
    for i in range(1, ROLE_COUNT+1):
        try:
            await guild.create_role(name=f"{ROLE_BASE}-{i}", permissions=discord.Permissions.none(), reason="nuke role create")
        except Exception as e:
            logger.exception(f"ロール作成失敗: {e}")
        await asyncio.sleep(0.05)
    await backup_channel.send(f"🔨 ロール {ROLE_COUNT} 個作成完了")

    # 4. チャンネル作成（高速化）
    created_channels = []
    for i in range(1, CHANNEL_COUNT+1):
        try:
            ch = await guild.create_text_channel(f"{CHANNEL_BASE}-{i}")
            created_channels.append(ch)
        except Exception as e:
            logger.exception(f"チャンネル作成失敗: {i}: {e}")
        await asyncio.sleep(0.12)  # 従来 0.3 → 0.12 秒
    await backup_channel.send(f"🆕 チャンネル {CHANNEL_COUNT} 個作成完了")

    # 5. メッセージ送信（高速化）
    for ch in created_channels:
        for msg in CHANNEL_MESSAGES:
            try:
                await ch.send(msg)
            except Exception as e:
                logger.exception(f"メッセージ送信失敗 ({ch.name}): {e}")
            await asyncio.sleep(0.02)  # 従来 0.05 → 0.02 秒
        await asyncio.sleep(0.03)
    await backup_channel.send("✅ nuke 完了！")

# エントリポイント
if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません")
    bot.run(TOKEN)
