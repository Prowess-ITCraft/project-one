"""The daily copy of backups off the server: new files only, never a half file."""

from pathlib import Path
from typing import Any

from app import ops
from app.core.config import get_settings
from app.core.s3 import ensure_bucket, s3_client


def test_copies_new_backups_once(settings_env: None, tmp_path: Path) -> None:
    bucket = get_settings().s3_bucket_backups
    ensure_bucket(bucket)
    client = s3_client()
    client.put_object(Bucket=bucket, Key="pg_dump/2026/10/03/210000.dump", Body=b"first night")
    client.put_object(Bucket=bucket, Key="pg_dump/2026/10/04/210000.dump", Body=b"second night")

    first = ops.export_backups(str(tmp_path))
    assert first >= 2
    copy = tmp_path / "pg_dump" / "2026" / "10" / "04" / "210000.dump"
    assert copy.read_bytes() == b"second night"

    # nothing new: nothing copied
    assert ops.export_backups(str(tmp_path)) == 0

    # a copy cut short last time (wrong size) is replaced, and no .part file is left behind
    copy.write_bytes(b"sec")
    assert ops.export_backups(str(tmp_path)) == 1
    assert copy.read_bytes() == b"second night"
    assert not list(tmp_path.rglob("*.part"))


def test_old_backups_are_pruned(settings_env: None, monkeypatch: Any) -> None:
    """Backups older than the retention period are removed."""
    bucket = get_settings().s3_bucket_backups
    ensure_bucket(bucket)
    client = s3_client()
    client.put_object(Bucket=bucket, Key="pg_dump/2026/09/01/210000.dump", Body=b"old enough")
    # everything just written counts as old once the retention period is negative
    monkeypatch.setattr(get_settings(), "backup_retention_days", -1)
    assert ops.prune_backups() >= 1
    left = client.list_objects_v2(Bucket=bucket, Prefix="pg_dump/").get("KeyCount", 0)
    assert left == 0
