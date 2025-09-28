# main.py
import os
import asyncio
import logging
from typing import List

import discord
from discord.ext import commands
from aiohttp import web

# --- 設定 ---
TOKEN = os.environ.get("DISCORD_TOKEN")  # Renderでは環境変数に設定
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True  # コマンド確認用に必要（ボット作成時Intentを有効にすること）

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nuker")

# --- Botセットアップ ---
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)

# --- ヘルパー ---
def chunk_list(lst, n):
    """n 個ずつの塊に分割（必要なら）"""
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete(reason="Requested by nuke command")
        logger.info(f"Deleted: {channel} ({channel.id})")
    except Exception as e:
        logger.exception(f"Failed to delete {channel}: {e}")

# --- コマンド ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logger.info("------")

def admin_only():
    """管理者権限チェックのデコレータ"""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        # サーバー所有者も許可
        if ctx.author == ctx.guild.owner:
            return True
        await ctx.send("このコマンドは管理者のみ使用できます。")
        return False
    return commands.check(predicate)

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
    exclude_names = [a.split("=",1)[1] if "=" in a else a for a in args if a != "--dry" and not a.startswith("--")]
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
        # do not remove system channels like rules or boost? We'll still include them if allowed.
        channels_to_delete.append(ch)

    if dry_run:
        if not channels_to_delete:
            await ctx.send("削除対象のチャンネルはありません（除外設定のため）。")
            return
        lines = [f"- {c.name} ({c.type})" for c in channels_to_delete]
        chunked = "\n".join(lines[:2000])  # Discordメッセージ制限に配慮
        await ctx.send(f"🧾 **Dry run** — 削除予定のチャンネル一覧:\n{chunked}")
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

    # Backup: create a channel to post the backup log (we'll try to create temporary channel)
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

    # Delete categories first (categories are typically type=CategoryChannel)
    categories = [c for c in channels_to_delete if isinstance(c, discord.CategoryChannel)]
    non_categories = [c for c in channels_to_delete if not isinstance(c, discord.CategoryChannel)]
    # Delete channels (text/voice) first so category deletion will remove references cleanly
    # We'll delete non-categories, then categories
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

# --- シンプルなHTTPサーバー（UptimeRobot用 ping レスポンス） ---
async def handle(request):
    return web.Response(text="ok")

def start_web_server():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    port = int(os.environ.get("PORT", "8080"))
    runner = web.AppRunner(app)
    loop = asyncio.get_event_loop()

    async def _run():
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Web server started on port {port}")

    loop.create_task(_run())

# --- エントリポイント ---
if __name__ == "__main__":
    start_web_server()
    bot.run(TOKEN)
