import os
import threading
import discord
from discord.ext import commands
from webserver import run  # Flask サーバーをインポート

TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Flask を別スレッドで起動
threading.Thread(target=run).start()

bot.run(TOKEN)
