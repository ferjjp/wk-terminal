import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import build_db
from wanikani_tui import attention, reader


def test_reader_counts_and_highlights():
    db = build_db(":memory:")
    rep = reader.analyse(db, "水を飲む。新聞と人と龍。")  # 水 started, 人 in WK (level 2, locked), 飲/龍 outside the fixture
    assert rep.kanji_total == 6 and rep.kanji_distinct == 6  # 水 飲 新 聞 人 龍
    assert sum(rep.by_group.values()) == 1                  # 水 (started)
    assert "人" in rep.locked and rep.locked["人"]["level"] == 2
    assert rep.outside["龍"] == 1 and rep.outside["飲"] == 1
    assert "新聞" in rep.vocab_unknown                       # WK word, lesson not started
    assert 0 < rep.coverage < 1
    plain = rep.highlighted.plain
    assert plain == "水を飲む。新聞と人と龍。"


def test_reader_no_kanji():
    db = build_db(":memory:")
    rep = reader.analyse(db, "ひらがなだけ")
    assert rep.kanji_total == 0 and rep.coverage == 1.0


def test_goal_and_streak():
    db = build_db(":memory:")
    local_noon = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)

    def day(n_days_ago, count):
        sid = db.begin_session("review")
        at = (local_noon - timedelta(days=n_days_ago)).astimezone(timezone.utc)  # noon local, whatever the UTC date
        for i in range(count):
            db.conn.execute(
                "INSERT INTO session_items(session_id,subject_id,subject_type,incorrect_meaning,incorrect_reading,old_stage,new_stage,at)"
                " VALUES(?,?,?,?,?,?,?,?)", (sid, 10, "kanji", 0, 0, 1, 2, at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
        db.conn.commit()

    day(3, 5); day(2, 5); day(1, 5); day(0, 2)
    st = db.goal_status(5)
    assert st["today"] == 2 and not st["met"] and st["streak"] == 3   # today unmet, streak counts from yesterday
    st = db.goal_status(2)
    assert st["met"] and st["streak"] == 4
    st = db.goal_status(0)
    assert st["met"] and st["streak"] == 4


def test_good_moment(monkeypatch):
    monkeypatch.setattr(attention, "do_not_disturb", lambda: True)
    assert attention.good_moment(120)[0] is False
    monkeypatch.setattr(attention, "do_not_disturb", lambda: False)
    monkeypatch.setattr(attention, "idle_seconds", lambda: 900.0)
    ok, why = attention.good_moment(120)
    assert ok is False and "away" in why
    monkeypatch.setattr(attention, "idle_seconds", lambda: 5.0)
    assert attention.good_moment(120)[0] is True
    monkeypatch.setattr(attention, "idle_seconds", lambda: None)
    assert attention.good_moment(120)[0] is True
    monkeypatch.setattr(attention, "do_not_disturb", lambda: True)
    assert attention.good_moment(120, respect_dnd=False)[0] is True


def test_save_setting_keeps_comments(tmp_path, monkeypatch):
    from wanikani_tui import config

    f = tmp_path / "config.toml"
    f.write_text('[review]\nanki = false   # keep me\n\n[ui]\ntheme = "textual-dark"       # any Textual theme\nvim_keys = true\n\n[daemon]\nsync_minutes = 10\n')
    monkeypatch.setattr(config, "config_file", lambda: f)
    config.save_setting("ui", "theme", "nord")
    text = f.read_text()
    assert 'theme = "nord"  # any Textual theme' in text and "# keep me" in text and "sync_minutes = 10" in text
    config.save_setting("goal", "evening_nudge", "21:00")   # new section appended
    assert "[goal]\nevening_nudge = \"21:00\"" in f.read_text()
    config.save_setting("ui", "compact", "true")            # new key inside an existing section
    assert 'compact = "true"' in f.read_text().split("[daemon]")[0]
    import tomllib
    tomllib.loads(f.read_text())
