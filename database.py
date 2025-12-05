import sqlite3
import logging
import os
import time

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 14


class NewsDatabase:
    def __init__(self, path=None, retention_days=DEFAULT_RETENTION_DAYS):
        if path is None:
            path = os.environ.get('STEAM_NEWS_DATABASE_PATH', 'SteamNews.db')
        self.path = path
        self.retention_days = retention_days
        self.db = None

    def open(self):
        if not self.db:
            logger.debug('Opening DB @ %s', self.path)
            # Ensure the directory exists
            db_dir = os.path.dirname(self.path)
            if db_dir and not os.path.exists(db_dir):
                try:
                    os.makedirs(db_dir, exist_ok=True)
                    logger.debug('Created directory: %s', db_dir)
                except OSError as e:
                    logger.error('Failed to create directory %s: %s', db_dir, e)
                    raise
            elif db_dir:
                logger.debug('Directory already exists: %s', db_dir)
            
            # Check if directory is writable
            if db_dir and not os.access(db_dir, os.W_OK):
                logger.error('Directory %s is not writable', db_dir)
                raise PermissionError(f'Directory {db_dir} is not writable')
            
            self.db = sqlite3.connect(self.path)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys = ON')
            
            # Run migrations if needed
            self._migrate_database()

    def close(self, optimize=True):
        if self.db:
            if optimize:
                logger.debug('Optimizing DB before close...')
                self.db.execute('PRAGMA optimize')
            logger.debug('Closing DB @ %s', self.path)
            self.db.close()
            self.db = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        #only do sqlite optimize if we didn't close via exception
        self.close(optimize=exc_type is None)
        return False

    def first_run(self):
        #The indentation here is more for the benefit of the sqlite3 tool
        # than the python source... /shrug
        self.db.executescript('''
CREATE TABLE Games(
    appid INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    shouldFetch INTEGER NOT NULL DEFAULT 1,
    last_played INTEGER DEFAULT 0);
CREATE TABLE ExpireTimes(
    appid INTEGER PRIMARY KEY
        REFERENCES Games(appid) ON DELETE CASCADE ON UPDATE CASCADE,
    unixseconds INTEGER NOT NULL DEFAULT 0);
CREATE TABLE NewsItems(
    gid TEXT NOT NULL PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT,
    is_external_url INTEGER,
    author TEXT,
    contents TEXT,
    feedlabel TEXT,
    date INTEGER NOT NULL DEFAULT (strftime('%s')),
    feedname TEXT,
    feed_type INTEGER,
    appid INTEGER NOT NULL);
CREATE TABLE NewsSources(
    gid TEXT NOT NULL
        REFERENCES NewsItems(gid) ON DELETE CASCADE ON UPDATE CASCADE,
    appid INTEGER NOT NULL
        REFERENCES Games(appid) ON DELETE CASCADE ON UPDATE CASCADE,
    PRIMARY KEY(gid, appid));
CREATE INDEX NewsDateIdx ON NewsItems(date);
CREATE INDEX NewsSourceAppIDIdx ON NewsSources(appid);
CREATE UNIQUE INDEX NewsTitleIdx ON NewsItems(title);''')

        #having news item appid foreign key on games can break,
        # since the news appid might not be the one we fetched against
        #FK in NewsSources -> Games is fine, though removing entries
        # from NewsSources could lead to loss of data useful for publishing...
        self.db.commit()
        logger.info('Created DB tables!')

    def _migrate_database(self):
        """Apply database migrations for schema updates."""
        try:
            # Check if Games table exists
            c = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Games'")
            if not c.fetchone():
                # No tables yet, nothing to migrate
                return
            
            # Migration 1: Add last_played column to Games table if it doesn't exist
            c = self.db.execute("PRAGMA table_info(Games)")
            columns = [row[1] for row in c.fetchall()]
            if 'last_played' not in columns:
                logger.info('Migrating database: adding last_played column to Games table...')
                self.db.execute('ALTER TABLE Games ADD COLUMN last_played INTEGER DEFAULT 0')
                self.db.commit()
                logger.info('Migration complete: last_played column added.')
            
            # Migration 2: Add unique index on NewsItems.title if it doesn't exist
            c = self.db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='NewsTitleIdx'")
            if not c.fetchone():
                logger.info('Migrating database: adding unique index on NewsItems.title...')
                # First, need to check for and handle any existing duplicate titles
                self.db.execute('''
                    DELETE FROM NewsItems
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM NewsItems
                        GROUP BY title
                    )
                ''')
                self.db.execute('CREATE UNIQUE INDEX NewsTitleIdx ON NewsItems(title)')
                self.db.commit()
                logger.info('Migration complete: NewsTitleIdx index added.')
                
        except Exception as e:
            logger.error('Error during database migration: %s', e)
            raise

    def add_games(self, games: dict, timestamps: dict = None):
        """Add or update games in the database.
        
        Args:
            games: dict of {appid: name}
            timestamps: optional dict of {appid: last_played_timestamp}
        """
        with self.db as db:
            if timestamps:
                # Update or insert with timestamps
                data = [(appid, name, timestamps.get(appid, 0)) for appid, name in games.items()]
                db.executemany('''
                    INSERT INTO Games (appid, name, last_played) VALUES (?, ?, ?)
                    ON CONFLICT(appid) DO UPDATE SET
                        name=excluded.name,
                        last_played=excluded.last_played
                    ''', data)
                logger.info('Added/updated %d games with play timestamps.', len(data))
            else:
                # Legacy mode: just insert or ignore
                cur = db.executemany('INSERT OR IGNORE INTO Games VALUES (?, ?, 1, 0)',
                        games.items())
                logger.info('Added %d new games to be fetched.', cur.rowcount)

    def get_games_like(self, name: str):
        #Since you can't do '%?%' in the SQL, do that here instead
        name = name.strip().strip('%')
        if name:
            n = '%' + name + '%'
            c = self.db.execute('''SELECT * FROM Games
                WHERE name LIKE ? ORDER BY name''', (n,))
        else:
            c = self.db.execute('SELECT * FROM Games ORDER BY name')
        return c.fetchall()

    def disable_fetching_ids(self, appids):
        with self.db as db:
            #sadly can't use executemany() w/ a "bare" list-- each item needs to be a tuple
            for aid in appids:
                db.execute('UPDATE Games SET shouldFetch = 0 WHERE appid = ?', (aid,))

    def enable_fetching_ids(self, appids):
        with self.db as db:
            for aid in appids:
                db.execute('UPDATE Games SET shouldFetch = 1 WHERE appid = ?', (aid,))

    def get_fetch_games(self):
        c = self.db.execute('SELECT appid, name FROM Games WHERE shouldFetch != 0')
        return dict(c.fetchall())

    def get_recently_played_games(self, count=None):
        """Get recently played games from database, sorted by last_played timestamp.
        
        Args:
            count: Optional limit on number of games to return
        
        Returns:
            dict: {appid: name} for recently played games
        """
        if count:
            c = self.db.execute('''
                SELECT appid, name FROM Games 
                WHERE shouldFetch != 0 AND last_played > 0
                ORDER BY last_played DESC
                LIMIT ?
            ''', (count,))
        else:
            c = self.db.execute('''
                SELECT appid, name FROM Games 
                WHERE shouldFetch != 0 AND last_played > 0
                ORDER BY last_played DESC
            ''')
        return dict(c.fetchall())

    def get_all_game_ids(self):
        """Get all game IDs in the database."""
        c = self.db.execute('SELECT appid FROM Games')
        return [row[0] for row in c.fetchall()]

    def update_expire_time(self, appid, expires):
        with self.db as db:
            db.execute('INSERT OR REPLACE INTO ExpireTimes VALUES (?, ?)',
                  (appid, expires))

    def is_news_cached(self, appid):
        c = self.db.execute('SELECT unixseconds FROM ExpireTimes WHERE appid = ?',
                (appid,))
        exptime = c.fetchone()
        if exptime is None: #i.e. appid not found
            return False
        else:
            #TODO maybe use datetime.timestamp() & now() instead?
            return time.time() < exptime[0]

    def insert_news_item(self, ned: dict):
        #TODO maybe convert the dict to a namedtuple...?
        with self.db as db:
            # Try to insert the news item
            # If title already exists, this will fail silently due to UNIQUE constraint
            db.execute('''INSERT OR IGNORE INTO NewsItems
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (ned['gid'], ned['title'], ned['url'], ned['is_external_url'],
                    ned['author'], ned['contents'], ned['feedlabel'], ned['date'],
                    ned['feedname'], ned['feed_type'], ned['appid']))

            # Find the gid for this title (might be different if title already existed)
            c = db.execute('SELECT gid FROM NewsItems WHERE title = ?', (ned['title'],))
            existing_gid = c.fetchone()[0]
            
            # Link this source appid to the gid (handles both new and existing articles)
            db.execute('INSERT OR IGNORE INTO NewsSources VALUES (?, ?)',
                    (existing_gid, ned['realappid']))

    def get_news_rows(self):
        #sadly our sqlite3 version isn't new enough for unixepoch()
        # so we have to use strftime('%s') for sqlite to make a unix timestamp
        c = self.db.execute('''SELECT * FROM NewsItems
            WHERE date >= strftime('%s', 'now', '-' || ? || ' day')
            ORDER BY date DESC''', (self.retention_days,))
        return c.fetchall()

    def get_source_names_for_item(self, gid):
        c = self.db.execute('''SELECT name
            FROM NewsSources NATURAL JOIN Games
            WHERE gid = ? ORDER BY appid''', (gid,))
        #fetchall gives a bunch of tuples, so we have to unpack them with a for loop...
        return list(x[0] for x in c.fetchall())

    def prune_old_news(self):
        """Remove news items older than retention_days from the database."""
        with self.db as db:
            cur = db.execute('''DELETE FROM NewsItems
                WHERE date < strftime('%s', 'now', '-' || ? || ' day')''', (self.retention_days,))
            deleted = cur.rowcount

        if deleted > 0:
            logger.info('Pruned %d old news items (older than %d days).', deleted, self.retention_days)
            # VACUUM and ANALYZE must run outside a transaction
            logger.debug('Running VACUUM to reclaim disk space...')
            self.db.execute('VACUUM')
            logger.debug('Running ANALYZE to update query statistics...')
            self.db.execute('ANALYZE')
        return deleted
