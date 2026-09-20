"""Tests for incremental watch daemon and delta change detection."""
import tempfile
from pathlib import Path
from corpusatlas.watch_daemon import IncrementalWatcher


def test_incremental_watcher_delta_detection():
    with tempfile.TemporaryDirectory() as tmpdir:
        watch_dir = Path(tmpdir)
        f1 = watch_dir / "doc1.md"
        f1.write_text("# Doc 1\n", encoding="utf-8")

        watcher = IncrementalWatcher([watch_dir])
        added, modified, deleted = watcher.scan_delta()

        # Initial scan: f1 is added
        assert f1 in added
        assert len(modified) == 0
        assert len(deleted) == 0

        # No change scan
        added, modified, deleted = watcher.scan_delta()
        assert len(added) == 0 and len(modified) == 0 and len(deleted) == 0

        # Modify f1
        f1.write_text("# Doc 1 Updated\nContent\n", encoding="utf-8")
        added, modified, deleted = watcher.scan_delta()
        assert f1 in modified
        assert len(added) == 0 and len(deleted) == 0

        # Add f2
        f2 = watch_dir / "doc2.md"
        f2.write_text("# Doc 2\n", encoding="utf-8")
        added, modified, deleted = watcher.scan_delta()
        assert f2 in added
        assert len(modified) == 0 and len(deleted) == 0

        # Delete f1
        f1.unlink()
        added, modified, deleted = watcher.scan_delta()
        assert f1 in deleted
        assert len(added) == 0 and len(modified) == 0
