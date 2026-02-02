import os
import sqlite3
from unittest.mock import patch

import pytest
from database import NewsDatabase
from SteamNews import main


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


from NewsPublisher import filter_rows_by_source


def _make_row(gid, feedlabel, feedname):
    """Helper to create a dict mimicking a sqlite3.Row for filtering."""
    return {'gid': gid, 'feedlabel': feedlabel, 'feedname': feedname}


def test_filter_exclude_source():
    rows = [
        _make_row('1', 'Rock, Paper, Shotgun', 'rps'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
        _make_row('3', 'Steam Community Announcements', 'steam_community_announcements'),
    ]
    result = filter_rows_by_source(rows, exclude_sources=['Rock, Paper, Shotgun'])
    assert [r['gid'] for r in result] == ['2', '3']


def test_filter_include_source():
    rows = [
        _make_row('1', 'Rock, Paper, Shotgun', 'rps'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
        _make_row('3', 'Steam Community Announcements', 'steam_community_announcements'),
    ]
    result = filter_rows_by_source(rows, include_sources=['PC Gamer'])
    assert [r['gid'] for r in result] == ['2']


def test_filter_include_multiple_sources():
    rows = [
        _make_row('1', 'Rock, Paper, Shotgun', 'rps'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
        _make_row('3', 'Steam Community Announcements', 'steam_community_announcements'),
    ]
    result = filter_rows_by_source(rows, include_sources=['PC Gamer', 'Rock, Paper, Shotgun'])
    assert [r['gid'] for r in result] == ['1', '2']


def test_filter_no_sources_returns_all():
    rows = [
        _make_row('1', 'Rock, Paper, Shotgun', 'rps'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
    ]
    result = filter_rows_by_source(rows)
    assert len(result) == 2


def test_filter_exclude_null_feedlabel_uses_feedname():
    rows = [
        _make_row('1', None, 'steam_community_blog'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
    ]
    result = filter_rows_by_source(rows, exclude_sources=['steam_community_blog'])
    assert [r['gid'] for r in result] == ['2']


def test_filter_include_null_feedlabel_uses_feedname():
    rows = [
        _make_row('1', None, 'steam_community_blog'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
    ]
    result = filter_rows_by_source(rows, include_sources=['steam_community_blog'])
    assert [r['gid'] for r in result] == ['1']


def test_filter_is_case_insensitive():
    rows = [
        _make_row('1', 'Rock, Paper, Shotgun', 'rps'),
        _make_row('2', 'PC Gamer', 'pcgamer'),
    ]
    result = filter_rows_by_source(rows, exclude_sources=['rock, paper, shotgun'])
    assert [r['gid'] for r in result] == ['2']


import time
from NewsPublisher import publish


@pytest.fixture
def populated_db(db, tmp_path):
    """The db fixture already has data. Update dates to be recent so get_news_rows returns them."""
    now = int(time.time())
    db.db.execute("UPDATE NewsItems SET date = ?", (now,))
    db.db.commit()
    db.retention_days = 30
    return db


def test_publish_with_exclude_source(populated_db, tmp_path):
    output = str(tmp_path / 'out.xml')
    publish(populated_db, output_path=output, exclude_sources=['Rock, Paper, Shotgun'])
    with open(output) as f:
        content = f.read()
    # Titles 1 and 4 are from RPS, should be excluded
    assert 'Title 1' not in content
    assert 'Title 4' not in content
    # Others should be present
    assert 'Title 2' in content
    assert 'Title 3' in content


def test_publish_with_include_source(populated_db, tmp_path):
    output = str(tmp_path / 'out.xml')
    publish(populated_db, output_path=output, include_sources=['PC Gamer'])
    with open(output) as f:
        content = f.read()
    assert 'Title 2' in content
    assert 'Title 1' not in content
    assert 'Title 3' not in content


def test_list_sources_cli(populated_db, capsys):
    with patch('SteamNews.NewsDatabase') as MockDB:
        MockDB.return_value.__enter__ = lambda s: populated_db
        MockDB.return_value.__exit__ = lambda s, *a: populated_db.close(optimize=False)
        with pytest.raises(SystemExit) as exc_info:
            with patch('sys.argv', ['SteamNews.py', '--list-sources']):
                main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert 'Rock, Paper, Shotgun' in captured.out
    assert 'PC Gamer' in captured.out


def test_exclude_source_cli_flag(populated_db, tmp_path):
    output = str(tmp_path / 'out.xml')
    with patch('SteamNews.NewsDatabase') as MockDB:
        MockDB.return_value.__enter__ = lambda s: populated_db
        MockDB.return_value.__exit__ = lambda s, *a: populated_db.close(optimize=False)
        with patch('sys.argv', ['SteamNews.py', '--publish', output,
                                '--exclude-source', 'Rock, Paper, Shotgun']):
            main()
    with open(output) as f:
        content = f.read()
    assert 'Title 1' not in content
    assert 'Title 2' in content


def test_include_and_exclude_are_mutually_exclusive():
    with pytest.raises(SystemExit) as exc_info:
        with patch('sys.argv', ['SteamNews.py',
                                '--include-source', 'Foo',
                                '--exclude-source', 'Bar']):
            main()
    assert exc_info.value.code != 0


def test_exclude_source_env_var(populated_db, tmp_path):
    output = str(tmp_path / 'out.xml')
    with patch('SteamNews.NewsDatabase') as MockDB:
        MockDB.return_value.__enter__ = lambda s: populated_db
        MockDB.return_value.__exit__ = lambda s, *a: populated_db.close(optimize=False)
        with patch.dict(os.environ, {'STEAM_NEWS_EXCLUDE_SOURCES': 'Rock, Paper, Shotgun|PC Gamer'}):
            with patch('sys.argv', ['SteamNews.py', '--publish', output]):
                main()
    with open(output) as f:
        content = f.read()
    assert 'Title 1' not in content
    assert 'Title 2' not in content
    assert 'Title 3' in content


def test_include_source_env_var(populated_db, tmp_path):
    output = str(tmp_path / 'out.xml')
    with patch('SteamNews.NewsDatabase') as MockDB:
        MockDB.return_value.__enter__ = lambda s: populated_db
        MockDB.return_value.__exit__ = lambda s, *a: populated_db.close(optimize=False)
        with patch.dict(os.environ, {'STEAM_NEWS_INCLUDE_SOURCES': 'PC Gamer'}):
            with patch('sys.argv', ['SteamNews.py', '--publish', output]):
                main()
    with open(output) as f:
        content = f.read()
    assert 'Title 2' in content
    assert 'Title 1' not in content
