# Docker Usage Guide

## Building the Image

```bash
docker build -t steam-news .
```

## Usage with Steam API Key (Recommended)

The script now supports using the Steam Web API, which works with private profiles.

### Get a Steam API Key
1. Visit https://steamcommunity.com/dev/apikey
2. Register for a key (use any domain name, e.g., `localhost`)
3. Copy your API key

### First-time Setup

```bash
# Using Steam ID (64-bit numerical ID)
docker run -v $(pwd)/data:/data \
  -e STEAM_API_KEY=YOUR_API_KEY_HERE \
  steam-news python SteamNews.py --first-run --add-profile-games YOUR_STEAM_ID --api-key $STEAM_API_KEY

# OR using vanity URL (username)
docker run -v $(pwd)/data:/data \
  -e STEAM_API_KEY=YOUR_API_KEY_HERE \
  steam-news python SteamNews.py --first-run --add-profile-games sharkusmanchez --api-key $STEAM_API_KEY
```

### Fetch News and Generate RSS

```bash
docker run -v $(pwd)/data:/data \
  steam-news python SteamNews.py --fetch --publish /data/steam_news.xml
```

### Interactive Game Selection

```bash
docker run -it -v $(pwd)/data:/data \
  steam-news python SteamNews.py --edit-games-like "game"
```

## Usage without API Key (Public Profiles Only)

If your Steam profile's game details are public, you can use the legacy XML method:

```bash
docker run -v $(pwd)/data:/data \
  steam-news python SteamNews.py --first-run --add-profile-games YOUR_STEAM_ID
```

## Docker Compose Example

Create a `docker-compose.yml`:

```yaml
version: '3.8'

services:
  steam-news:
    build: .
    volumes:
      - ./data:/data
    environment:
      - STEAM_API_KEY=${STEAM_API_KEY}
    command: python SteamNews.py --fetch --publish /data/steam_news.xml
```

Then create a `.env` file:
```
STEAM_API_KEY=your_api_key_here
```

Run with:
```bash
docker-compose run steam-news
```

## Automated Updates with Cron

You can schedule regular updates using cron or a scheduler:

```bash
# Add to crontab (runs every 6 hours)
0 */6 * * * docker run -v /path/to/data:/data steam-news python SteamNews.py --fetch --publish /data/steam_news.xml
```

## Environment Variables

- `STEAM_API_KEY`: Your Steam Web API key (optional but recommended)
- `DATABASE_PATH`: Path to SQLite database (default: `/data/steam_news.db`)

## Volumes

- `/data`: Persistent storage for database and generated RSS feed

## Finding Your Steam ID

### Method 1: From Profile URL
If your profile URL is `https://steamcommunity.com/id/username/`, use `username` as the vanity URL.

### Method 2: Using SteamID Finder
Visit https://steamid.io/ and enter your profile URL to get your 64-bit Steam ID.

### Method 3: From Steam Client
1. Click your name in Steam
2. Click "Account Details"
3. Your Steam ID is shown at the top
