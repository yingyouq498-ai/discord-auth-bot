# main.py
import os
import asyncio
import logging
import threading
from typing import List

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

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
        await channel.delete(reason="Requested by nuke command")
        logger.info(f"Deleted: {channel.name} ({channel.id})")
    except Exception as e:
        logger.exception(f"Failed to delete {channel}: {e}")

# --- コマンド ---
def admin_only():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator or ctx.author == ctx.guild.owner:
            return True
        await ctx.send("このコマンドは管理者のみ使用できます。")
        return False
    return commands.check(predicate)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")

@bot.command(name="nuke")
@admin_only()
async def nuke(ctx):
    """即削除、高速版"""
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    me = guild.me or guild.get_member(bot.user.id)
    if not me.guild_permissions.manage_channels and not me.guild_permissions.administrator:
        await ctx.send("Botにチャンネル削除権限がありません。")
        return

    channels_to_delete: List[discord.abc.GuildChannel] = [c for c in guild.channels]

    if not channels_to_delete:
        await ctx.send("削除対象のチャンネルはありません。")
        return

    await ctx.send(f"⚡ 全チャンネルを即削除します！ ({len(channels_to_delete)} チャンネル)")

    # --- 並列削除 ---
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]

    async def delete_group(channels: list):
        # 10個ずつ並列削除
        for group in chunk_list(channels, 10):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(0.1)  # レート制限回避

    await delete_group(non_categories)
    await delete_group(categories)

    # 削除完了後に通知用チャンネルを作成
    try:
        new_ch = await guild.create_text_channel("nuked-by-bot")
        await new_ch.send(f"🎉 サーバーがリセットされました（実行者: {ctx.author.mention}）")
    except Exception as e:
        logger.exception("完了通知チャンネルの作成に失敗: %s", e)

# --- エントリポイント ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server starting in background thread...")

    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN が設定されていません。")
    bot.run(TOKEN)
