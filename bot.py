from dotenv import load_dotenv
load_dotenv()
import socket
import struct
import asyncio
import json
from aiohttp import web
import discord
from discord.ext import commands, tasks
from discord import app_commands
import os

RCON_HOST      = os.environ.get("RCON_HOST", "")
RCON_PORT      = int(os.environ.get("RCON_PORT", "25575"))
RCON_PASSWORD  = os.environ.get("RCON_PASSWORD", "")
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", "0"))
CHAT_CHANNEL_ID= int(os.environ.get("CHAT_CHANNEL_ID", "0"))
WEBHOOK_PORT   = int(os.environ.get("WEBHOOK_PORT", "40060"))
POLL_INTERVAL  = int(os.environ.get("POLL_INTERVAL", "30"))


class RconClient:
    def __init__(self):
        self._sock = None
        self._req_id = 1

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10)
        self._sock.connect((RCON_HOST, RCON_PORT))
        resp_id, _, _ = self._send_packet(3, RCON_PASSWORD)
        if resp_id == -1:
            raise ConnectionError("RCON authentication failed")

    def _send_packet(self, pkt_type, payload):
        req_id = self._req_id
        self._req_id += 1
        encoded = payload.encode("utf-8")
        size = 4 + 4 + len(encoded) + 2
        packet = struct.pack("<iii", size, req_id, pkt_type) + encoded + b"\x00\x00"
        self._sock.sendall(packet)
        return self._read_response()

    def _read_response(self):
        raw_size = self._recv_exact(4)
        size = struct.unpack("<i", raw_size)[0]
        body = self._recv_exact(size)
        resp_id = struct.unpack("<i", body[0:4])[0]
        resp_type = struct.unpack("<i", body[4:8])[0]
        payload = body[8:-2].decode("utf-8", errors="replace")
        return resp_id, resp_type, payload

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            buf += chunk
        return buf

    def command(self, cmd):
        _, _, response = self._send_packet(2, cmd)
        return response

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


def rcon_command(cmd: str) -> str:
    client = RconClient()
    client.connect()
    try:
        return client.command(cmd)
    finally:
        client.disconnect()


def parse_players(response: str) -> dict:
    players = {}
    for line in response.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            name_part = parts[0]
            if ")" in name_part:
                name_part = name_part.split(")", 1)[1].strip()
            platform_id = parts[1].strip()
            if name_part and platform_id:
                players[platform_id] = name_part
    return players


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

known_players: dict = {}
first_run: bool = True
server_online: bool = False


@tasks.loop(seconds=POLL_INTERVAL)
async def player_monitor():
    global known_players, first_run, server_online

    log_channel = bot.get_channel(LOG_CHANNEL_ID)

    try:
        raw = await asyncio.to_thread(rcon_command, "listplayers")
        current = parse_players(raw)

        if not server_online:
            server_online = True

        if first_run:
            known_players = current
            first_run = False
            print(f"[INIT] {len(current)} player(s) online")
            return

        for pid, name in current.items():
            if pid not in known_players:
                print(f"[JOIN] {name}")
                if log_channel:
                    embed = discord.Embed(
                        title="🟢 Player Joined",
                        description=f"**{name}** connected to the server.",
                        color=0x2ECC71,
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.add_field(name="Platform ID", value=f"`{pid}`", inline=True)
                    embed.set_footer(text="Conan Exiles • RCON")
                    await log_channel.send(embed=embed)

        for pid, name in known_players.items():
            if pid not in current:
                print(f"[LEAVE] {name}")
                if log_channel:
                    embed = discord.Embed(
                        title="🔴 Player Left",
                        description=f"**{name}** disconnected from the server.",
                        color=0xE74C3C,
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.add_field(name="Platform ID", value=f"`{pid}`", inline=True)
                    embed.set_footer(text="Conan Exiles • RCON")
                    await log_channel.send(embed=embed)

        known_players = current

    except (ConnectionError, OSError, TimeoutError) as e:
        if server_online:
            server_online = False
            print(f"[ERROR] Server unreachable: {e}")
            if log_channel:
                embed = discord.Embed(
                    title="⚠️ Server Unreachable",
                    description="Lost connection to the Conan Exiles server.",
                    color=0xE67E22,
                    timestamp=discord.utils.utcnow(),
                )
                embed.set_footer(text="Conan Exiles • RCON")
                await log_channel.send(embed=embed)


async def handle_webhook(request: web.Request) -> web.Response:
    params = dict(request.rel_url.query)

    try:
        body = await request.text()
        if body:
            try:
                params.update(json.loads(body))
            except json.JSONDecodeError:
                for part in body.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        params[k] = v
    except Exception:
        pass

    event_id    = params.get("eventId", "")
    char_name   = params.get("charName", "Unknown")
    platform_id = params.get("steamId", "")
    message     = params.get("message", "")
    channel     = params.get("channel", "Global")

    print(f"[WEBHOOK] event={event_id} char={char_name} msg={message}")

    chat_channel = bot.get_channel(CHAT_CHANNEL_ID)
    log_channel  = bot.get_channel(LOG_CHANNEL_ID)

    if message and event_id not in ("PLAYER_CONNECTED", "PLAYER_DISCONNECTED", "PlayerConnected", "PlayerDisconnected"):
        if chat_channel:
            embed = discord.Embed(
                description=message,
                color=0x3498DB,
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=f"[{channel}] {char_name}")
            embed.set_footer(text="Conan Exiles")
            asyncio.create_task(chat_channel.send(embed=embed))

    elif event_id in ("PLAYER_CONNECTED", "PlayerConnected"):
        if log_channel:
            embed = discord.Embed(
                title="🟢 Player Joined",
                description=f"**{char_name}** connected to the server.",
                color=0x2ECC71,
                timestamp=discord.utils.utcnow(),
            )
            if platform_id:
                embed.add_field(name="Platform ID", value=f"`{platform_id}`", inline=True)
            embed.set_footer(text="Conan Exiles • Tot Sudo")
            asyncio.create_task(log_channel.send(embed=embed))

    elif event_id in ("PLAYER_DISCONNECTED", "PlayerDisconnected"):
        if log_channel:
            embed = discord.Embed(
                title="🔴 Player Left",
                description=f"**{char_name}** disconnected from the server.",
                color=0xE74C3C,
                timestamp=discord.utils.utcnow(),
            )
            if platform_id:
                embed.add_field(name="Platform ID", value=f"`{platform_id}`", inline=True)
            embed.set_footer(text="Conan Exiles • Tot Sudo")
            asyncio.create_task(log_channel.send(embed=embed))

    else:
        print(f"[WEBHOOK] Unhandled event: {event_id} | params: {params}")

    return web.Response(text="OK", status=200)


async def start_webhook_server():
    app = web.Application()
    app.router.add_get("/log", handle_webhook)
    app.router.add_post("/log", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    print(f"[WEBHOOK] Listening on port {WEBHOOK_PORT}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id == CHAT_CHANNEL_ID:
        text = f"[Discord] {message.author.display_name}: {message.content}"
        try:
            await asyncio.to_thread(rcon_command, f"broadcast {text}")
            print(f"[CHAT->CONAN] {text}")
        except (ConnectionError, OSError, TimeoutError) as e:
            print(f"[ERROR] Broadcast failed: {e}")
    await bot.process_commands(message)


@bot.tree.command(name="players", description="Show currently online players")
async def slash_players(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        raw = await asyncio.to_thread(rcon_command, "listplayers")
        players = parse_players(raw)
        if not players:
            embed = discord.Embed(title="👥 Online Players", description="No players online.", color=0x95A5A6, timestamp=discord.utils.utcnow())
        else:
            lines = [f"`{i+1}.` {name}" for i, (pid, name) in enumerate(players.items())]
            embed = discord.Embed(title=f"👥 Online Players ({len(players)})", description="\n".join(lines), color=0x3498DB, timestamp=discord.utils.utcnow())
        embed.set_footer(text="Conan Exiles • RCON")
        await interaction.followup.send(embed=embed)
    except (ConnectionError, OSError, TimeoutError) as e:
        await interaction.followup.send(f"❌ Could not reach server: `{e}`", ephemeral=True)


@bot.tree.command(name="status", description="Show server online/offline status")
async def slash_status(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        raw = await asyncio.to_thread(rcon_command, "listplayers")
        players = parse_players(raw)
        embed = discord.Embed(title="✅ Server Online", description=f"**{len(players)}** player(s) connected.", color=0x2ECC71, timestamp=discord.utils.utcnow())
        embed.add_field(name="Host", value=f"`{RCON_HOST}`", inline=True)
        embed.set_footer(text="Conan Exiles • RCON")
        await interaction.followup.send(embed=embed)
    except (ConnectionError, OSError, TimeoutError):
        embed = discord.Embed(title="❌ Server Offline", description="Could not connect to the server.", color=0xE74C3C, timestamp=discord.utils.utcnow())
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="broadcast", description="Send a broadcast message to all players in-game")
@app_commands.describe(message="The message to broadcast")
@app_commands.default_permissions(administrator=True)
async def slash_broadcast(interaction: discord.Interaction, message: str):
    await interaction.response.defer(ephemeral=True)
    try:
        await asyncio.to_thread(rcon_command, f"broadcast {message}")
        await interaction.followup.send(f"✅ Broadcast sent: **{message}**", ephemeral=True)
        print(f"[BROADCAST] {interaction.user}: {message}")
    except (ConnectionError, OSError, TimeoutError) as e:
        await interaction.followup.send(f"❌ Failed: `{e}`", ephemeral=True)


@bot.event
async def on_ready():
    print("=" * 55)
    print(f" Conan Exiles Discord Bot")
    print(f" Logged in as  : {bot.user} ({bot.user.id})")
    print(f" RCON          : {RCON_HOST}:{RCON_PORT}")
    print(f" Log channel   : {LOG_CHANNEL_ID}")
    print(f" Chat channel  : {CHAT_CHANNEL_ID}")
    print(f" Webhook port  : {WEBHOOK_PORT}")
    print("=" * 55)
    await bot.tree.sync()
    print("[BOT] Slash commands synced")
    await start_webhook_server()
    player_monitor.start()
    print(f"[BOT] Player monitor started (every {POLL_INTERVAL}s)")


bot.run(BOT_TOKEN)
