import base64
from collections import deque
import datetime
from io import BytesIO
import json
import os
import random
import subprocess
from PIL import Image
from urllib.parse import urlparse
import discord
from discord.ext import commands
from discord import app_commands
import re
import requests
from googletrans import Translator
import praw

TOKEN: str = ''
bot: commands.Bot = commands.Bot(command_prefix='/', intents=discord.Intents.all())
client = discord.Client(intents=discord.Intents.all())
tree = app_commands.CommandTree(client)

URL: str = "http://localhost:11434/api/generate"
LLM: str = 'teallama'
VISION: str = 'llava'

MAX_TOKENS: int = 16384
HISTORY_FILE: str = 'history.json'
PROMPT_LENGTH: int = 2048 - 128

translator: Translator = Translator()

@bot.event
async def on_ready() -> None:
    await bot.change_presence(status=discord.Status.online, activity=discord.Activity(name=LLM, state="Drinking TEA", type=discord.ActivityType.custom))
    print(f'\033[94m{bot.user}\033[0m is ready to talk!')

@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author == bot.user:
        print(f"\033[94m{message.channel} -> {message.author}:\033[0m\n{message.content}")
        return
    print(f"\033[92m{message.channel} -> {message.author}:\033[0m\n{message.content}")


    if await execute(message):
        return


    history = load_history()

# -------------------------------------------------- VISION --------------------------------------------------

    if bot.user.mentioned_in(message) and message.attachments or message.reference:
        print(f"{message.author.display_name} mentioned me in {message.channel}!")

        current_prompt: str = re.sub(f'<@{bot.user.id}', '', message.content).strip()

        current_context: str = f"{message.author.display_name}: {current_prompt}\n"
        add_message(history, current_context)

        image_url = message.attachments[0].url if message.attachments else message.reference.resolved.attachments[0].url
        response = requests.get(image_url)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        img_str = [base64.b64encode(buffered.getvalue()).decode("utf-8")]

        print(img_str)

        await message.channel.typing()
        data = {
            "model": VISION,
            "prompt": current_prompt,
            "images": img_str,
        }
        response = requests.post(URL, json=data, headers={'Content-Type': 'application/json'})

        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            return
        
        response_lines = response.text.strip().split("\n")
        output = "".join(json.loads(line)["response"] for line in response_lines)

        assistant_response: str = f"Teabot: {output}"
        add_message(history, assistant_response)

        await message.reply(output)
        await message.reply(f"Google перевод:\n```fix\n{translator.translate(output, dest='ru').text}```") #sv

        return

# -------------------------------------------------- LLM --------------------------------------------------

    if bot.user.mentioned_in(message):
        print(f"{message.author.display_name} mentioned me in {message.channel}!")

        current_prompt: str = re.sub(f'<@{bot.user.id}', '', message.content).strip()
        current_context: str = f"{message.author.display_name}: {current_prompt}\n"

        if message.reference:
            reference: discord.Message = message.reference.resolved
            # history.append((reference.author.display_name, reference.content.strip()))
            current_context += f"{reference.author.display_name}: {reference.content.strip()}\n"

        prompt: str = f"{get_context(history)}\nCurrent context:\n{current_context}"

        add_message(history, current_context)

        await message.channel.typing()
        data = {
            "model": LLM,
            "prompt": prompt,
            "stream": False
        }
        response = requests.post(URL, json=data)

        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            return
        
        output: str = response.json().get('response')
        assistant_response: str = f"Teabot: {output}"
        add_message(history, assistant_response)

        # print (f"\033[93m{history}\033[0m")
        if len(output) > PROMPT_LENGTH:
            parts = [output[i:i + PROMPT_LENGTH] for i in range(0, len(output), PROMPT_LENGTH)]
            for part in parts:
                await message.reply(part)
            return
        
        await message.reply(output)
        await message.reply(f"Google перевод:\n```fix\n{translator.translate(output, dest='ru').text}```") #sv
        return
    
    add_message(history, f"{message.author.display_name}: {message.content}")


def get_context(history):
    return ' '.join(history)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as file:
            history = deque(json.load(file))
    else:
        history = deque()
    return history

def save_history(history):
    with open(HISTORY_FILE, 'w') as file:
        json.dump(list(history), file)

def clean_history(history):
    while len(' '.join(history)) > MAX_TOKENS:
        history.popleft()

def add_message(history, message):
    history.append(message)
    clean_history(history)
    save_history(history)

# -------------------------------------------------- COMMANDS --------------------------------------------------

async def ping(message: discord.Message):
    """Ping the bot"""
    await message.reply(f'Pong! {round(bot.latency * 1000)}ms')


async def command_list(message: discord.Message):
    """List all available commands"""
    help_message = """```fix\n"""
    for commands, function in COMMANDS.items():
        for command in commands:
            help_message += f"{command} "
        help_message += f"— {function.__doc__}\n"
    help_message += """```"""
    await message.reply(help_message)


async def command_embed_list(message: discord.Message):
    """List all available commands"""
    help_message = discord.Embed(title="Commands", description="List of available commands")
    for commands, function in COMMANDS.items():
        command_line = ""
        for command in commands:
            command_line += f"{command} "
        help_message.add_field(name=command_line, value=function.__doc__, inline=False)
    await message.reply(embed=help_message)


async def purge(message: discord.Message):
    """Purge messages. Syntax: <command> <amount>"""
    content = message.content
    channel = message.channel
    author = message.author

    if channel.permissions_for(author).manage_messages:
        try:
            amount = int(content.split()[1])
            await channel.purge(limit=amount+1)
        except (IndexError, ValueError):
            pass


async def roll(message: discord.Message):
    """Roll dice. Syntax: <command> [iterations] [count] <max>"""
    args = message.content.split()[1:]
    await dice(message, args)


async def translate(message: discord.Message):
    """Translate text. Syntax: <command> <language: ru/en/fr/sv/...>"""
    if message.reference is not None:
        dest = message.content.split()[1]
        await message.reply(translator.translate(message.reference.resolved.content, dest=dest).text)


async def download(message: discord.Message):
    """Download music from YouTube. Syntax: <command> <url>"""
    content = message.content
    channel = message.channel

    url = content.split()[1]

    if not urlparse(url).scheme:
        return
    
    subprocess.run(["yt-dlp", url])

    files = [f for f in os.listdir() if f.endswith(".webm")]
    input_file = files[0]
    os.rename(input_file, "input.webm")

    subprocess.run(["ffmpeg", "-i", "input.webm", "-b:a", "320k", "output.mp3"])

    name = os.path.splitext(input_file)[0] + ".mp3"
    os.rename("output.mp3", name)
    os.remove("input.webm")

    with open(name, "rb") as f:
        await channel.send(file=discord.File(f, filename=name))

    os.remove(name)


async def subreddit(message: discord.Message):
    """Get random reddit post. Syntax: <command> <subreddit>"""
    subreddit = message.content.split()[1]
    await reddit(message, subreddit)


async def art(message: discord.Message):
    """Get art from reddit"""
    await reddit(message, "AnimeArt")


async def meme(message: discord.Message):
    """Get meme from reddit"""
    await reddit(message, "memes")


async def avatar(message: discord.Message):
    """Get avatar"""
    member = message.author
    if message.mentions:
        member = message.mentions[0]
    embed = discord.Embed(title=f"{member.display_name}'s Avatar", color=member.color)
    embed.set_image(url=member.avatar.url)
    await message.reply(embed=embed)


async def disable(message: discord.Message):
    """Disable PC"""
    channel = message.channel
    author = message.author

    if channel.permissions_for(author).manage_messages:
        subprocess.Popen('shutdown -s -t 360', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        await message.delete()
        await message.channel.send(f"Выключение {(datetime.datetime.now() + datetime.timedelta(minutes=6)).strftime('%H:%M')} (через 6 минут).", delete_after=300)


async def cancel(message: discord.Message):
    """Cancel shutdown"""
    channel = message.channel
    author = message.author

    if channel.permissions_for(author).manage_messages:
        subprocess.Popen('shutdown -a', stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        await message.delete()
        await message.channel.send("Отмена выключения.", delete_after=300)

# -------------------------------------------------- HELPERS --------------------------------------------------

async def reddit(message, subreddit):
    reddit = praw.Reddit(client_id="HxYeD-p6A2b4BLCc6PlG7w",
    client_secret="ZcJOWbq5HGYc4TLfNKxPYWGZoXlY1g",
    user_agent="Discord Teabot by /u/Teanquisitor",
    username="Significant_Check591",
    password="vh3P5#LPRFO34bMKVC")
    subreddit = reddit.subreddit(subreddit)
    top = subreddit.top(limit=256)
    submissions = [submission for submission in top]
    meme = random.choice(submissions)
    em = discord.Embed(color=discord.Color.green())
    em.set_footer(text=f"Requested by {message.author.name}")
    em.set_author(name=meme.title, url=meme.url)
    em.set_image(url=meme.url)
    await message.delete()
    await message.channel.send(embed=em)

async def dice(message, args):
    if len(args) == 1:
        amount = int(args[0])  # Количество граней кубика
        embed = discord.Embed(title="Бросок", description=f"{message.author.mention} совершил бросок.", color=discord.Color.blue())
        embed.add_field(name="Результат", value=f'{str(random.randint(1, amount))} из {str(amount)}', inline=False)
        await message.delete()
        await message.channel.send(embed=embed)
    elif len(args) == 2:
        num_dice = int(args[0])  # Количество кубиков
        amount = int(args[1])  # Количество граней кубика
        results = [random.randint(1, amount) for _ in range(num_dice)]
        embed = discord.Embed(title="Бросок", description=f"{message.author.mention} совершил {num_dice} бросков.", color=discord.Color.blue())
        embed.add_field(name=f"Результаты ({amount} граней)", value=f'```fix\n{", ".join(map(str, results))}```', inline=False)
        embed.add_field(name="Общий результат", value=str(sum(results)), inline=False)
        await message.delete()
        await message.channel.send(embed=embed)
    elif len(args) == 3:
        iterations = int(args[0])  # Количество итераций
        num_dice = int(args[1])  # Количество кубиков
        amount = int(args[2])  # Количество граней кубика
        all_results = []  # Список для всех результатов
        for _ in range(iterations):
            results = [random.randint(1, amount) for _ in range(num_dice)]  # Список результатов бросков
            all_results.append(results)  # Добавление результатов текущей итерации в общий список
        embed = discord.Embed(title="Бросок", description=f"{message.author.mention} совершил {iterations} бросков.", color=discord.Color.blue())
        for i, results in enumerate(all_results):
            total = sum(results)  # Общий результат текущей итерации
            embed.add_field(name=f"Результаты {i+1} броска ({num_dice} кубиков, {amount} граней) - {total}", value=f'```fix\n{", ".join(map(str, results))}```', inline=False)
        embed.add_field(name="Общий результат", value=str(sum(sum(results) for results in all_results)), inline=False)
        await message.delete()
        await message.channel.send(embed=embed)

# -------------------------------------------------- COMMAND DICTIONARY --------------------------------------------------

COMMANDS: dict = {
    ('ping',): ping, #
    ('help', 'h', '??'): command_embed_list, #
    ('commands', 'cmds'): command_list, #
    ('delete', 'del', 'purge'): purge, #
    ('roll', 'r'): roll, #
    ('translate', 't'): translate, #
    ('download', 'ytd'): download, #
    ('reddit',): subreddit, #
    ('art', 'a'): art, #
    ('meme', 'm'): meme, #
    ('avatar',): avatar, #
    ('disable', 'd'): disable, #
    ('cancel', 'c'): cancel, #
}

# -------------------------------------------------- COMMAND EXECUTION FUNCTIONS --------------------------------------------------

async def execute(message: discord.Message) -> bool:
    if message.author == bot.user:
        return False
    
    content = message.content.split(' ')[0].lower()

    for key in COMMANDS:
        if any(content == k for k in key):
            await COMMANDS[key](message)
            return True

    return False

bot.run(TOKEN)



# TODO
# Permissions
# Read data from config file
# Sort command sequence
# Add localization
# Clean up code
# Join voice channel

async def is_command(message: discord.Message):
    content = message.content.lower()
    channel = message.channel
    author = message.author

    # Audit Logs Command
    if content.startswith("aud") and channel.permissions_for(author).manage_messages:
        try:
            amount = int(content.split()[1])
            logs = ""
            async for entry in message.guild.audit_logs(limit=amount):
                logs += f"{entry.user} {entry.action.name} {entry.target}\n"
            await message.reply(f'```fix\n{logs}```')
        except (IndexError, ValueError):
            pass
        return True
    
    # Invite Link
    if content in ["invite", "inv"]:
        invite = await channel.create_invite(max_uses=1, unique=True)
        await message.reply(f"Invite link: {invite}")
        return True
    
    # Server Info
    if content in ["serverinfo", "si"]:
        embed = discord.Embed(title="Server Info", color=message.guild.owner.color)
        # embed.set_thumbnail(url=ctx.guild.icon_url)
        embed.add_field(name="Server Name", value=message.guild.name)
        embed.add_field(name="Server ID", value=message.guild.id)
        embed.add_field(name="Member Count", value=message.guild.member_count)
        embed.add_field(name="Owner", value=message.guild.owner)
        await message.reply(embed=embed)
        return True
    
    # User Info
    if content.startswith(("userinfo", "ui")):
        member = message.author
        if message.mentions:
            member = message.mentions[0]
        embed = discord.Embed(title="User Info", color=member.color)
        embed.set_thumbnail(url=member.avatar.url)
        embed.add_field(name="Username", value=member.display_name)
        embed.add_field(name="User ID", value=member.id)
        embed.add_field(name="Join Date", value=member.joined_at.strftime("%b %d, %Y"))
        embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y"))
        await message.reply(embed=embed)
        return True
    
    # Role Info
    if content.startswith(("oleinfo", "i")):
        role = message.guild.default_role
        if message.role_mentions:
            role = message.role_mentions[0]
        embed = discord.Embed(title="Role Info", color=role.color)
        embed.add_field(name="Role Name", value=role.name)
        embed.add_field(name="Members", value=len(role.members))
        embed.add_field(name="Created", value=role.created_at.strftime("%b %d, %Y"))
        embed.set_footer(text=f"Requested by {message.author}")
        await message.delete()
        await message.channel.send(embed=embed)