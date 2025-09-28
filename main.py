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
TOKEN = os.environ.get("DISCORD_TOKEN")  # Render の環境変数名
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True  # Bot作成時にIntentを有効に

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

# --- Botセットアップ ---
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)

# --- Flask サーバー（UptimeRobot 用） ---
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    """UptimeRobot が叩くヘルスチェック用。Bot の基本状態を返す。"""
    ready = bot.is_ready()
    bot_user = None
    guild_count = 0
    try:
        if bot.user:
            bot_user = str(bot.user)
        guild_count = len(bot.guilds)
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "bot_ready": ready,
        "bot_user": bot_user,
        "guild_count": guild_count
    }), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    # デバッグモードやloggerの逸脱を避けるため、use_reloader=False
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- ヘルパー ---
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete(reason="Requested by nuke command")
        logger.info(f"Deleted: {channel} ({channel.id})")
    except Exception as e:
        logger.exception(f"Failed to delete {channel}: {e}")

# --- 権限チェックデコレータ ---
def admin_only():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        # サーバー所有者も許可
        if ctx.author == ctx.guild.owner:
            return True
        await ctx.send("このコマンドは管理者のみ使用できます。")
        return False
    return commands.check(predicate)

# --- Bot イベント ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logger.info("------")

# --- nuke コマンド（元の機能を保持） ---
@bot.command(name="nuke")
@admin_only()
async def nuke(ctx, *args):
    """
    使い方例：
    !nuke --dry               -> 削除予定のチャンネル一覧を表示（削除しない）
    !nuke --exclude general   -> 'general' という名前のチャンネルは削除しない
    !nuke                     -> 実行（確認が必要）
    """
    guild = ctx.guild
    if guild is None:
        await ctx.send("サーバー内で実行してください。")
        return

    # parse args
    dry_run = "--dry" in args
    # exclude 指定はスペース区切りで名前を並べる（例: --exclude general logs）
    exclude_names = [a for a in args if a != "--dry" and not a.startswith("--")]
    exclude_names = [n.lower() for n in exclude_names]

    # check bot permissions
    me = guild.me or guild.get_member(bot.user.id)
    if not me.guild_permissions.manage_channels and not me.guild_permissions.administrator:
        await ctx.send("Botにチャンネル削除権限（Manage Channels または Administrator）がありません。")
        return

    # Build list of channels to delete
    channels_to_delete: List[discord.abc.GuildChannel] = []
    for ch in guild.channels:
        if ch.name.lower() in exclude_names:
            continue
        channels_to_delete.append(ch)

    if dry_run:
        if not channels_to_delete:
            await ctx.send("削除対象のチャンネルはありません（除外設定のため）。")
            return
        lines = [f"- {c.name} ({c.type})" for c in channels_to_delete]
        # メッセージ長制限に配慮
        joined = "\n".join(lines)
        if len(joined) > 1900:
            # 長すぎる場合は先頭2000文字分のみ送る
            joined = joined[:1900] + "\n...(省略)"
        await ctx.send(f"🧾 **Dry run** — 削除予定のチャンネル一覧:\n{joined}")
        return

    # Confirmation step
    confirm_code = os.urandom(3).hex()  # 6文字確認コード
    await ctx.send(
        f"⚠️ 本当に全チャンネルを削除します。確認のため次のコードをこのチャンネルにコピーして送ってください：\n`{confirm_code}`\n"
        "（この操作は取り消せません）\n"
        "除外したいチャンネルがある場合は、`!nuke --dry`で確認してから実行してください。"
    )

    def check(m: discord.Message):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        reply: discord.Message = await bot.wait_for("message", check=check, timeout=60.0)
    except asyncio.TimeoutError:
        await ctx.send("タイムアウトしました。もう一度やり直してください。")
        return

    if reply.content.strip() != confirm_code:
        await ctx.send("確認コードが一致しません。中止します。")
        return

    # Backup: create a channel to post the backup log (temporary)
    backup_name = "nuke-backup-log"
    backup_channel = None
    try:
        backup_channel = await guild.create_text_channel(backup_name)
        await backup_channel.send("バックアップ: 以下は削除対象のチャンネル一覧です。")
        for c in channels_to_delete:
            try:
                await backup_channel.send(f"- {c.name} ({c.type}) id:{c.id}")
            except Exception:
                pass
    except Exception as e:
        logger.exception("バックアップチャンネル作成失敗: %s", e)
        backup_channel = None

    # Proceed with deletion
    await ctx.send(f"✅ 確認完了。{len(channels_to_delete)} チャンネルを順次削除します。処理中...")

    # Delete categories after non-categories to avoid dangling references
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]

    for ch in non_categories + categories:
        # ensure we don't try to delete the backup channel we just created
        if backup_channel and ch.id == backup_channel.id:
            logger.info("Skipping backup channel from deletion.")
            continue
        try:
            await safe_delete_channel(ch)
            # short sleep to reduce chance of hitting rate limits
            await asyncio.sleep(0.5)
        except Exception:
            await asyncio.sleep(1)

    # Recreate a small channel to notify completion, if possible
    try:
        new_ch = await guild.create_text_channel("nuked-by-bot")
        await new_ch.send("🎉 サーバーがリセットされました（nuke 実行者: {}）".format(ctx.author.mention))
    except Exception as e:
        logger.exception("完了通知チャンネルの作成に失敗: %s", e)

    await ctx.send("✅ 削除処理が完了しました。")

# --- エントリポイント ---
if __name__ == "__main__":
    # Flask を別スレッドで起動
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server starting in background thread...")

    # 実行
    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。環境変数を確認してください。")
        raise SystemExit("DISCORD_TOKEN is required")

    bot.run(TOKEN)
