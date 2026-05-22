# Conan Exiles Discord Bot

Discord bot for Conan Exiles servers using RCON and Tot Sudo/Chat webhooks.

## Features

- Join/leave logging via RCON polling
- Two-way chat bridge (Discord <-> Conan via Tot Chat webhook + RCON broadcast)
- `/players` — list online players
- `/status` — server online/offline
- `/broadcast` — send message to all players in-game (admin only)

## Setup

### 1. Configure RCON on your Conan server

Add to `Game.ini`:
```
[RconPlugin]
RconEnabled=1
RconPassword=your_password
RconPort=25575
```

### 2. Create a Discord bot

1. Go to https://discord.com/developers/applications
2. New Application → Bot → Reset Token → copy token
3. Enable **Message Content Intent** and **Server Members Intent**
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Send Messages`, `Embed Links`
5. Invite bot to your server

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values.

In Pelican, set each variable in the server's Variables section:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Discord bot token |
| `RCON_HOST` | Conan server IP |
| `RCON_PORT` | RCON port (default 25575) |
| `RCON_PASSWORD` | RCON password |
| `LOG_CHANNEL_ID` | Channel ID for join/leave logs |
| `CHAT_CHANNEL_ID` | Channel ID for two-way chat bridge |
| `WEBHOOK_PORT` | Port for Tot Sudo/Chat webhook (default 40060) |
| `POLL_INTERVAL` | Seconds between player polls (default 30) |

### 4. Tot Sudo webhook

In-game: Shift+U → Webhook → Enable → set URL to:
```
http://YOUR_SERVER_IP:WEBHOOK_PORT/log
```

### 5. Pelican setup

- **Main file**: `bot.py`
- **Node packages**: leave empty
- **Additional packages**: `discord.py aiohttp` (or use requirements.txt)
- **Startup**: `python bot.py`

## Discord channels

| Channel | Purpose |
|---|---|
| `#conan-log` | Join/leave, server status alerts |
| `#conan-chat` | Two-way chat — messages here are broadcast in-game |
