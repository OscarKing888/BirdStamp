import sqlite3
from pathlib import Path

from app_common.report_db import (
    ReportDB,
    existing_report_db_paths,
    find_report_root,
    resolve_existing_report_db_path,
)


def _touch_sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS smoke_test (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()


def test_existing_report_db_paths_prioritizes_superpicky(tmp_path: Path) -> None:
    root_db = tmp_path / "report.db"
    superpicky_db = tmp_path / ".superpicky" / "report.db"
    _touch_sqlite_db(root_db)
    _touch_sqlite_db(superpicky_db)

    paths = existing_report_db_paths(str(tmp_path))

    assert paths == [str(superpicky_db), str(root_db)]
    assert resolve_existing_report_db_path(str(tmp_path)) == str(superpicky_db)


def test_open_if_exists_supports_root_report_db_and_find_report_root(tmp_path: Path) -> None:
    root_db = tmp_path / "report.db"
    _touch_sqlite_db(root_db)
    nested = tmp_path / "child" / "leaf"
    nested.mkdir(parents=True)

    db = ReportDB.open_if_exists(str(tmp_path))
    assert db is not None
    try:
        assert Path(db.db_path) == root_db
        assert db.exists() is True
    finally:
        db.close()

    assert find_report_root(str(nested), max_levels=4) == str(tmp_path)
