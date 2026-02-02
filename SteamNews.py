#!/usr/bin/env python3

# Inspired by the likes of
# https://bendodson.com/weblog/2016/05/17/fetching-rss-feeds-for-steam-game-updates/
# http://www.getoffmalawn.com/blog/rss-feeds-for-steam-games

__version__ = "1.0.1"

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
from urllib.error import HTTPError
import xml.dom.minidom  # Maybe replace this one...

from database import NewsDatabase
from NewsPublisher import publish

logger = logging.getLogger(__name__)

# Hardcoded list of AppIDs that return news related to Steam as a whole (not games)
# Mileage may vary. Use app_id_discovery.py to maybe find more of these...
STEAM_APPIDS = {753: 'Steam',
        221410: 'Steam for Linux',
        223300: 'Steam Hardware',
        250820: 'SteamVR',
        353370: 'Steam Controller',
        353380: 'Steam Link',
        358720: 'SteamVR Developer Hardware',
        596420: 'Steam Audio',
        #593110 is the source for the megaphone icon in the client, not in appid list...
        593110: 'Steam News',
        613220: 'Steam 360 Video Player'}


def seed_database(idOrVanity, db: NewsDatabase, api_key=None, recently_played=False, recently_played_count=None, replace=False):
    """Seed database with games from a Steam profile.
    
    Args:
        idOrVanity: Steam ID (64-bit) or vanity URL name
        db: NewsDatabase instance
        api_key: Steam Web API key (optional, will check env var STEAM_NEWS_API_KEY)
        recently_played: If True, enable only recently played games; otherwise enable all games
        recently_played_count: Number of recently played games to enable (used with recently_played)
        replace: If True, disable all existing games before adding new ones
    """
    if api_key is None:
        api_key = os.environ.get('STEAM_NEWS_API_KEY')
    
    # Convert vanity URL to Steam ID if needed
    try:
        steamid = int(idOrVanity)
    except ValueError:
        # It's a vanity URL, need to resolve it
        if not api_key:
            logger.error('Steam API key required to resolve vanity URLs. Set STEAM_NEWS_API_KEY environment variable.')
            sys.exit(1)
        steamid = resolveVanityURL(idOrVanity, api_key)
        if not steamid:
            logger.error('Could not resolve vanity URL: %s', idOrVanity)
            sys.exit(1)
    
    # Always fetch ALL owned games with timestamps
    if api_key:
        newsids, timestamps = getAllGamesWithTimestamps(steamid, api_key)
    else:
        # Fall back to XML method (requires public profile)
        # Note: XML method doesn't have timestamp data
        if recently_played:
            logger.warning('Recently played mode requires API key for timestamp data. Falling back to all games from XML.')
        url = 'https://steamcommunity.com/profiles/{}/games?xml=1'.format(steamid)
        newsids = getAppIDsFromURL(url)
        timestamps = {}
    
    #Also add the hardcoded ones...
    newsids.update(STEAM_APPIDS)
    
    if replace:
        # Disable all existing games before adding new ones
        existing_ids = list(db.get_all_game_ids())
        if existing_ids:
            logger.info('Replace mode: disabling %d existing games before adding new ones.', len(existing_ids))
            db.disable_fetching_ids(existing_ids)
    
    # Add/update all games with timestamps
    db.add_games(newsids, timestamps)
    
    # If recently_played mode, enable only recently played games
    if recently_played and timestamps:
        # Get recently played game IDs
        played_games = [(appid, ts) for appid, ts in timestamps.items() if ts > 0]
        played_games.sort(key=lambda x: x[1], reverse=True)
        
        if recently_played_count:
            played_games = played_games[:recently_played_count]
        
        recently_played_ids = [appid for appid, _ in played_games]
        
        # Disable all games first, then enable only recently played
        all_game_ids = list(newsids.keys())
        db.disable_fetching_ids(all_game_ids)
        db.enable_fetching_ids(recently_played_ids)
        
        logger.info('Enabled %d recently played games for news fetching.', len(recently_played_ids))
    elif not recently_played:
        # Enable all games
        db.enable_fetching_ids(list(newsids.keys()))


def resolveVanityURL(vanity_url, api_key):
    """Resolve a Steam vanity URL to a Steam ID using the API."""
    url = 'https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={}&vanityurl={}'.format(
        api_key, vanity_url)
    try:
        response = urlopen(url)
        data = json.loads(response.read().decode('utf-8'))
        if data['response']['success'] == 1:
            logger.info('Resolved vanity URL "%s" to Steam ID %s', vanity_url, data['response']['steamid'])
            return int(data['response']['steamid'])
        else:
            return None
    except Exception as e:
        logger.error('Error resolving vanity URL: %s', e)
        return None


def getAllGamesWithTimestamps(steamid, api_key):
    """Get all owned games with their last played timestamps using Steam Web API.
    
    Args:
        steamid: 64-bit Steam ID
        api_key: Steam Web API key
    
    Returns:
        tuple: (games dict {appid: name}, timestamps dict {appid: last_played_unix_time})
    """
    url = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={}&steamid={}&include_appinfo=1&include_played_free_games=1&format=json'.format(
        api_key, steamid)
    logger.info('Fetching all games with timestamps from Steam API for Steam ID %s...', steamid)
    
    try:
        response = urlopen(url)
        data = json.loads(response.read().decode('utf-8'))
        
        if 'response' not in data or 'games' not in data['response']:
            logger.error('No games found. The profile may be private or the Steam ID may be invalid.')
            return {}, {}
        
        games = {}
        timestamps = {}
        for game in data['response']['games']:
            appid = game['appid']
            name = game.get('name', 'Unknown Game')
            last_played = game.get('rtime_last_played', 0)
            games[appid] = name
            timestamps[appid] = last_played
        
        played_count = sum(1 for ts in timestamps.values() if ts > 0)
        logger.info('Found %d total games (%d with play history).', len(games), played_count)
        return games, timestamps
    except HTTPError as e:
        logger.error('HTTP Error fetching games: %s %s', e.code, e.reason)
        return {}, {}
    except Exception as e:
        logger.error('Error fetching games from API: %s', e)
        return {}, {}


def getAppIDsFromURL(url):
    """Given a steam profile url, produce a dict of
    appids to names of games owned (appids are strings)
    i.e. parses unofficial XML API of a Steam user's game list.
    Note that the profile in question needs to be public for this to work!"""
    logger.info('Parsing XML from %s...', url)
    try:
        xmlstr = urlopen(url).read().decode('utf-8')
        
        # Check if we got redirected to a login page
        if 'login' in xmlstr.lower() or '<html' in xmlstr.lower():
            logger.error('Profile is private or requires login. Please make your game details public or use --api-key.')
            return {}
        
        dom = xml.dom.minidom.parseString(xmlstr)
        gameEls = dom.getElementsByTagName('game')

        games = {}
        for ge in gameEls:
            appid = int(ge.getElementsByTagName('appID')[0].firstChild.data)
            name = ge.getElementsByTagName('name')[0].firstChild.data
            games[appid] = name

        logger.info('Found %d games.', len(games))
        return games
    except xml.parsers.expat.ExpatError as e:
        logger.error('XML parsing error: %s. Profile may be private or invalid.', e)
        logger.error('Please make your game details public or use --api-key option with STEAM_NEWS_API_KEY environment variable.')
        return {}
    except Exception as e:
        logger.error('Error fetching games from profile: %s', e)
        return {}

# Date/time manipulation

def getExpiresDTFromResponse(response):
    exp = response.getheader('Expires')
    if exp is None:
        return datetime.now(timezone.utc)
    else:
        return parseExpiresAsDT(exp)


def parseExpiresAsDT(exp):
    # e.g. 'Sun, 15 Apr 2018 17:20:14 GMT'
    t = datetime.strptime(exp, '%a, %d %b %Y %H:%M:%S %Z')
    # The %Z parsing doesn't work right since it seems to expect a +##:## code on top of the GMT
    # So we're going to assume it's always GMT/UTC
    return t.replace(tzinfo=timezone.utc)

# Why are there so many variables named ned?
# I shorthanded "news element dict" to distinguish it as a single item
# vs. 'news' which is typically used for the entire JSON payload Steam gives us

def getNewsForAppID(appid):
    """Get news for the given appid as a dict"""
    url = 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/?format=json&maxlength=0&count=10&appid={}'.format(appid)
    try:
        response = urlopen(url)
        # Get value of 'expires' header as a datetime obj
        exdt = getExpiresDTFromResponse(response)
        # Parse the JSON
        news = json.loads(response.read().decode('utf-8'))
        # Add the expire time to the group as a plain unix time
        news['expires'] = int(exdt.timestamp())
        # Decorate each news item and the group with its "true" appid
        for ned in news['appnews']['newsitems']:
            ned['realappid'] = appid

        return news
    except HTTPError as e:
        return {'error': '{} {}'.format(e.code, e.reason)}


def isNewsOld(ned, retention_days=14):
    """Is this news item older than retention_days?"""
    newsdt = datetime.fromtimestamp(ned['date'], timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    return newsdt < cutoff


def saveRecentNews(news: dict, db: NewsDatabase, retention_days=14):
    """Given a single news dict from getNewsForAppID,
    save all "recent" news items to the DB"""
    db.update_expire_time(news['appnews']['appid'], news['expires'])

    current_entries = 0
    for ned in news['appnews']['newsitems']:
        if not isNewsOld(ned, retention_days):
            db.insert_news_item(ned)
            current_entries += 1
    return current_entries


def getAllRecentNews(newsids: dict, db: NewsDatabase, max_workers=10):
    """Given a dict of appids to names, store all "recent" items, respecting the cache.
    
    Args:
        newsids: dict of {appid: game_name}
        db: NewsDatabase instance
        max_workers: Maximum number of concurrent requests (default: 10)
    """
    total_current = 0
    cachehits = 0
    newhits = 0
    fails = 0
    
    # Thread-safe counter and database access lock
    counter_lock = threading.Lock()
    db_lock = threading.Lock()
    
    def fetch_news_only(aid, name):
        """Fetch news for a single app ID (network request only)."""
        try:
            news = getNewsForAppID(aid)
            return (aid, name, news, None)
        except Exception as e:
            return (aid, name, None, str(e))
    
    # First, check cache and separate cached vs. to-fetch
    to_fetch = []
    for aid, name in newsids.items():
        if db.is_news_cached(aid):
            logger.info('Cache for %d: %s still valid!', aid, name)
            cachehits += 1
        else:
            to_fetch.append((aid, name))
    
    if to_fetch:
        logger.info('Fetching news for %d games concurrently (max %d workers)...', 
                   len(to_fetch), max_workers)
        
        # Use ThreadPoolExecutor for concurrent fetching (network I/O only)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all fetch tasks
            future_to_game = {
                executor.submit(fetch_news_only, aid, name): (aid, name)
                for aid, name in to_fetch
            }
            
            # Process results as they complete
            for future in as_completed(future_to_game):
                aid, name = future_to_game[future]
                try:
                    aid, name, news, error = future.result()
                    
                    if error:
                        with counter_lock:
                            fails += 1
                        logger.error('%d: %s exception: %s', aid, name, error)
                    elif news and 'appnews' in news:
                        # Save to database using the main thread's connection (with lock)
                        with db_lock:
                            cur_entries = saveRecentNews(news, db, retention_days=db.retention_days)
                        
                        with counter_lock:
                            newhits += 1
                            total_current += cur_entries
                        
                        if cur_entries:
                            logger.info('Fetched %d: %s OK; %d current items', aid, name, cur_entries)
                        else:
                            logger.info('Fetched %d: %s OK; nothing current', aid, name)
                    else:
                        with counter_lock:
                            fails += 1
                        logger.error('%d: %s fetch error: %s', aid, name, news.get('error', 'Unknown error'))
                        
                except Exception as e:
                    with counter_lock:
                        fails += 1
                    logger.error('Unexpected error processing %d: %s - %s', aid, name, str(e))

    logger.info('Run complete. %d cached, %d fetched, %d failed; %d current news items',
            cachehits, newhits, fails, total_current)

def edit_fetch_games(name, db: NewsDatabase):
    logger.info('Editing games like "%s"', name)
    games = db.get_games_like(name)
    before_on = set()
    before_off = set()
    args = ['whiptail', '--title', 'Select games to fetch news for',
            '--separate-output', '--checklist',
            'Use arrow keys to move, Space to toggle, Tab to go to OK, ESC to cancel.',
            '50', '100', '43', '--']
    for game in games:
        if game['shouldFetch']:
            before_on.add(game['appid'])
            status = 'on'
        else:
            before_off.add(game['appid'])
            status = 'off'
        args.append(str(game['appid']))
        args.append(game['name'])
        args.append(status)

    proc = subprocess.run(args, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        logger.info('Cancelled editing games.')
        return
    #Convert stderr output to set of int appids...
    out = proc.stderr.strip() #mainly to remove trailing newline
    if out:
        selected = frozenset(map(int, out.split('\n')))
    else: #i.e. deselected everything, so output was empty
        selected = frozenset()
    logger.debug('Before on: %s\nBefore off: %s\nSelected (enable): %s',
            before_on, before_off, selected)
    #disable: ids in before_on that are not in selected
    disabled = before_on - selected
    #enable: ids in selected that are also in before_off
    enabled = selected & before_off
    logger.debug('Enabled %s\nDisabled: %s', enabled, disabled)

    if disabled:
        db.disable_fetching_ids(disabled)
        logger.info('Disabled %d games.', len(disabled))
    if enabled:
        db.enable_fetching_ids(enabled)
        logger.info('Enabled %d games.', len(enabled))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--first-run', action='store_true')
    parser.add_argument('-a', '--add-profile-games', metavar='Steam ID|Vanity url')
    parser.add_argument('--recently-played', action='store_true',
                       help='When adding profile games, only add recently played games (requires API key)')
    parser.add_argument('--recently-played-count', type=int, metavar='N',
                       help='Limit recently played games to last N games (default: all from last 2 weeks, or set STEAM_NEWS_RECENTLY_PLAYED_COUNT env var)')
    parser.add_argument('--replace', action='store_true',
                       help='Disable all existing games before adding new ones (useful when switching from all games to recently played)')
    parser.add_argument('--api-key', metavar='KEY', help='Steam Web API key (or set STEAM_NEWS_API_KEY env var)')
    parser.add_argument('-f', '--fetch', action='store_true')
    parser.add_argument('-p', '--publish', metavar='XML output path')
    parser.add_argument('--prune', action='store_true',
                       help='Prune news items older than retention period from database')
    parser.add_argument('-g', '--edit-games-like', metavar='partial title')
    parser.add_argument('-w', '--workers', type=int, metavar='N',
                       help='Number of concurrent workers for fetching (default: 10, or set STEAM_NEWS_WORKERS env var)')
    parser.add_argument('-r', '--retention-days', type=int, metavar='DAYS',
                       help='Number of days to retain news items (default: 14, or set STEAM_NEWS_RETENTION_DAYS env var)')
    parser.add_argument('-l', '--language', metavar='LANG',
                       help='Filter articles by language during publish (ISO 639-1 code, e.g., "en"). '
                            'Requires langdetect: pip install langdetect. '
                            '(Or set STEAM_NEWS_LANGUAGE env var)')
    parser.add_argument('--list-sources', action='store_true',
                       help='List distinct news sources (feedlabels) in the database and exit')
    parser.add_argument('-v', '--verbose', action='store_true')
    #TODO maybe arg for DB path...?
    args = parser.parse_args()

    lvl = logging.INFO if not args.verbose else logging.DEBUG
    logging.basicConfig(stream=sys.stdout,
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            level=lvl)

    # Get retention days from CLI arg, env var, or default
    retention_days = args.retention_days
    if retention_days is None:
        retention_days = int(os.environ.get('STEAM_NEWS_RETENTION_DAYS', 14))

    # Get workers from CLI arg, env var, or default
    workers = args.workers
    if workers is None:
        workers = int(os.environ.get('STEAM_NEWS_WORKERS', 10))

    # Get recently played count from CLI arg or env var
    recently_played_count = args.recently_played_count
    if recently_played_count is None and args.recently_played:
        env_count = os.environ.get('STEAM_NEWS_RECENTLY_PLAYED_COUNT')
        if env_count:
            recently_played_count = int(env_count)

    # Get language filter from CLI arg or env var
    language = args.language
    if language is None:
        language = os.environ.get('STEAM_NEWS_LANGUAGE')

    with NewsDatabase(retention_days=retention_days) as db:
        if args.list_sources:
            sources = db.get_distinct_sources()
            if not sources:
                print('No news sources found. Run --fetch first.')
            else:
                print('{:<40s} {}'.format('Source', 'Feed Name'))
                print('-' * 60)
                for feedlabel, feedname in sources:
                    label = feedlabel or '(none - uses feedname)'
                    print('{:<40s} {}'.format(label, feedname or ''))
            sys.exit(0)

        if args.first_run:
            db.first_run()

        if args.add_profile_games:
            seed_database(args.add_profile_games, db, api_key=args.api_key, 
                        recently_played=args.recently_played,
                        recently_played_count=recently_played_count,
                        replace=args.replace)

        if args.edit_games_like:
            edit_fetch_games(args.edit_games_like, db)
        else: #editing is mutually exclusive w/ fetch & publish
            if args.fetch:
                newsids = db.get_fetch_games()
                getAllRecentNews(newsids, db, max_workers=workers)
                # Prune old news items from database
                db.prune_old_news()

            if args.prune:
                db.prune_old_news()

            if args.publish:
                publish(db, args.publish, language=language)

if __name__ == '__main__':
    main()
