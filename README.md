# Steam News Feed Generator

## Motivations
Steam provides a set of news feeds at http://store.steampowered.com/news/ for information
about the games they sell.
If you're signed in, they even customize the entires to only your games at
http://store.steampowered.com/news/?feed=mygames
but this is not accessible outside of Steam short of web scraping.

However, Steam does provide an API for getting news items for individual games
by their AppIDs. The scripts in this repository allow one to fetch news for
a large number of games and merge them all into a single RSS feed,
with roughly the same content as the `mygames` link above.
A SQLite database is used to store the list of AppIDs to fetch news for,
as well as a cache of all the news items retrieved.

## Configuration

The application can be configured via command-line flags or environment variables. Environment variables are prefixed with `STEAM_NEWS_`.

| Configuration | CLI Flag | Environment Variable | Default | Description |
|--------------|----------|---------------------|---------|-------------|
| Steam API Key | `--api-key KEY` | `STEAM_NEWS_API_KEY` | None | Steam Web API key for resolving vanity URLs and fetching owned games |
| Database Path | N/A | `STEAM_NEWS_DATABASE_PATH` | `SteamNews.db` | Path to SQLite database file |
| Retention Days | `-r DAYS`, `--retention-days DAYS` | `STEAM_NEWS_RETENTION_DAYS` | 14 | Number of days to retain news items. Older items are ignored when fetching and pruned from the database |
| Workers | `-w N`, `--workers N` | `STEAM_NEWS_WORKERS` | 10 | Number of concurrent workers for fetching news |
| Recently Played Count | `--recently-played-count N` | `STEAM_NEWS_RECENTLY_PLAYED_COUNT` | None | Limit recently played games to last N games played (only applies with `--recently-played`) |
| Verbose Logging | `-v`, `--verbose` | N/A | False | Enable debug-level logging output |

**Note:** CLI flags take precedence over environment variables when both are provided.

## Usage
`SteamNews.py` is the main script. Run it with `--help` to get the command-line
arguments it works with.

On first install, run
`./SteamNews.py --first-run --add-profile-games <Steam ID/vanity URL ending>`
to create the database & seed it with a games list from a **public** Steam profile.

### News Source Methods

You can choose between two methods for determining which games to fetch news for:

1. **All Owned Games** (default): Fetches news for all games in your Steam library
   ```bash
   ./SteamNews.py --add-profile-games <Steam ID/vanity URL>
   ```

2. **Recently Played Games**: Fetches news only for recently played games (requires Steam API key)
   
   - **All games you've ever played** (default when using `--recently-played`):
     ```bash
     ./SteamNews.py --add-profile-games <Steam ID> --recently-played --api-key <YOUR_KEY>
     ```
   
   - **Last N games played** (configurable count, sorted by last played timestamp):
     ```bash
     # Last 5 games played
     ./SteamNews.py --add-profile-games <Steam ID> --recently-played --recently-played-count 5
     
     # Or with environment variables:
     export STEAM_NEWS_API_KEY=<YOUR_KEY>
     export STEAM_NEWS_RECENTLY_PLAYED_COUNT=10
     ./SteamNews.py --add-profile-games <Steam ID> --recently-played
     ```

#### Switching Between Methods

By default, adding games is **additive** - new games are added to the existing list. If you want to switch from "all games" to "recently played" (or vice versa), use the `--replace` flag to disable all existing games first:

```bash
# Switch from all games to recently played (last 10 games)
./SteamNews.py --add-profile-games <Steam ID> --recently-played --recently-played-count 10 --replace

# Switch back to all games
./SteamNews.py --add-profile-games <Steam ID> --replace
```

Without `--replace`, games are simply added to the existing list, which is useful for combining games from multiple profiles.

You can re-run with `-a`/`--add-profile-games` to combine or update from other
profiles, if you like.

From there, if you know you don't need news for some of your games, run with
`-g`/`--edit-games-like` followed by a partial name of a game in question--
you'll get a `whiptail` dialog to turn those on or off.
Other editing of the games list (e.g. adding games you don't own on Steam)
still needs to be done by hand with `sqlite3` or similar.

Once you're happy with the games list, run with `-f`/`--fetch` to pull
news from Steam's API. The AppIDs it fetches are based on the games pulled from
the profile(s) in the above steps, minus those disabled by "editing".
Fetching respects the `Expires` headers sent by the API and only adds
the 10 most recent news items, as long as they're within the retention period
(default 14 days, configurable via `--retention-days` or `STEAM_NEWS_RETENTION_DAYS`).

After fetching, old news items (older than the retention period) are automatically
pruned from the database to keep it clean and manageable.

You can also manually prune old items without fetching using `--prune`:
```bash
# Prune items older than default retention period (14 days)
./SteamNews.py --prune

# Prune items older than custom retention period
./SteamNews.py --prune --retention-days 7
```

Finally, you can run `-p`/`--publish` followed by a path to an XML file to output
to convert the newest news items into an RSS feed.

`updateAndPublish.sh` is a sample Bash script to fetch, publish,
and copy the result where it will be published.
Note that you can combine `--fetch` and `--publish` to do both in the same run!

## Dependencies
This is a Python 3 project. The only external libraries in use are
[PyRSS2Gen](http://dalkescientific.com/Python/PyRSS2Gen.html)
and [bbcode](https://github.com/dcwatson/bbcode).

```bash
python3 -m pip install -r requirements.txt
```

You'll also want the `whiptail` program installed for the terminal interface to edit
which games to fetch; otherwise you'll need to use the `sqlite3` program directly.

# Licence
MIT, go nuts.
