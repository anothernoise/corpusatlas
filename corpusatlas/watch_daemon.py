"""Incremental file watcher and change delta tracker for continuous graph updates.

Maintains file states (mtime and byte size) across source directories to detect
added, modified, and deleted documents without requiring heavy external inotify/watchdog packages.
Zero external dependencies.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


class IncrementalWatcher:
    """Tracks filesystem state changes across watched directories and files."""

    def __init__(self, watch_paths: Iterable[Path | str]):
        self.watch_paths = [Path(p) for p in watch_paths]
        # path -> (st_mtime, st_size)
        self.file_states: dict[Path, tuple[float, int]] = {}
        self._initialized = False

    def _discover_files(self) -> dict[Path, tuple[float, int]]:
        current_states: dict[Path, tuple[float, int]] = {}
        for p in self.watch_paths:
            if not p.exists():
                continue
            if p.is_file():
                try:
                    stat = p.stat()
                    current_states[p] = (stat.st_mtime, stat.st_size)
                except OSError:
                    pass
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            stat = f.stat()
                            current_states[f] = (stat.st_mtime, stat.st_size)
                        except OSError:
                            pass
        return current_states

    def scan_delta(self) -> tuple[set[Path], set[Path], set[Path]]:
        """Compute delta changes since the last scan.

        Returns:
            (added_files, modified_files, deleted_files)
        """
        current_states = self._discover_files()

        if not self._initialized:
            self._initialized = True
            self.file_states = current_states
            # On first scan, all discovered files are considered added
            return set(current_states.keys()), set(), set()

        old_files = set(self.file_states.keys())
        cur_files = set(current_states.keys())

        added = cur_files - old_files
        deleted = old_files - cur_files
        modified = set()

        for f in cur_files & old_files:
            if current_states[f] != self.file_states[f]:
                modified.add(f)

        self.file_states = current_states
        return added, modified, deleted
