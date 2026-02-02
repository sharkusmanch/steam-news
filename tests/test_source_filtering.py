import sqlite3
import pytest
from database import NewsDatabase


@pytest.fixture
def db(tmp_path):
    """Create a temporary NewsDatabase with test data."""
    db_path = str(tmp_path / 'test.db')
    ndb = NewsDatabase(path=db_path)
    ndb.open()
    ndb.first_run()

    # Insert test games
    ndb.db.execute("INSERT INTO Games VALUES (10, 'Game A', 1, 0)")
    ndb.db.execute("INSERT INTO Games VALUES (20, 'Game B', 1, 0)")
    ndb.db.commit()

    # Insert test news items with different feedlabels
    ndb.db.execute(
        "INSERT INTO NewsItems VALUES ('gid1', 'Title 1', 'http://a', 1, 'auth', 'content', 'Rock, Paper, Shotgun', 1000000, 'rps', 0, 10)")
    ndb.db.execute(
        "INSERT INTO NewsItems VALUES ('gid2', 'Title 2', 'http://b', 1, 'auth', 'content', 'PC Gamer', 1000001, 'pcgamer', 0, 10)")
    ndb.db.execute(
        "INSERT INTO NewsItems VALUES ('gid3', 'Title 3', 'http://c', 1, 'auth', 'content', 'Steam Community Announcements', 1000002, 'steam_community_announcements', 1, 20)")
    ndb.db.execute(
        "INSERT INTO NewsItems VALUES ('gid4', 'Title 4', 'http://d', 1, 'auth', 'content', 'Rock, Paper, Shotgun', 1000003, 'rps', 0, 20)")
    ndb.db.execute(
        "INSERT INTO NewsItems VALUES ('gid5', 'Title 5', 'http://e', 1, 'auth', 'content', NULL, 1000004, 'steam_community_blog', 0, 10)")
    ndb.db.commit()

    # Insert source mappings
    ndb.db.execute("INSERT INTO NewsSources VALUES ('gid1', 10)")
    ndb.db.execute("INSERT INTO NewsSources VALUES ('gid2', 10)")
    ndb.db.execute("INSERT INTO NewsSources VALUES ('gid3', 20)")
    ndb.db.execute("INSERT INTO NewsSources VALUES ('gid4', 20)")
    ndb.db.execute("INSERT INTO NewsSources VALUES ('gid5', 10)")
    ndb.db.commit()

    yield ndb
    ndb.close()


def test_get_distinct_sources(db):
    sources = db.get_distinct_sources()
    assert sources == [
        ('PC Gamer', 'pcgamer'),
        ('Rock, Paper, Shotgun', 'rps'),
        ('Steam Community Announcements', 'steam_community_announcements'),
        (None, 'steam_community_blog'),
    ]


def test_get_distinct_sources_includes_null_feedlabel(db):
    sources = db.get_distinct_sources()
    # NULL feedlabel rows should still appear, with None as feedlabel
    assert (None, 'steam_community_blog') in sources
