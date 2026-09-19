"""Tests for the entry-point plugin mechanism in adapters/__init__.py — a
third-party adapter registered under the "corpusatlas.adapters" group should
be found by `build()` exactly like one of the seven built in, without ever
being able to shadow a built-in name.

No real installed plugin package is needed: importlib.metadata.EntryPoint
just needs a dotted path it can import, and this test module is already
importable as itself once pytest/tests/run.py has loaded it — so a fake
adapter class defined right here, referenced by this module's own __name__,
is a real, loadable entry point.
"""
import sys
from importlib.metadata import EntryPoint
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import corpusatlas.adapters as adapters_mod
from corpusatlas.model import Document


class FakeExternalAdapter:
    """Stands in for a third-party adapter package."""

    def __init__(self, greeting: str = "hi"):
        self.greeting = greeting

    def documents(self):
        yield Document(id="ext", title=self.greeting, url="/ext", kind="article")


def _fake_entry_points(group):
    assert group == adapters_mod.ENTRY_POINT_GROUP
    return [EntryPoint(name="fake_external", value=f"{__name__}:FakeExternalAdapter",
                       group=adapters_mod.ENTRY_POINT_GROUP)]


def _no_entry_points(group):
    return []


def test_build_finds_an_external_adapter_by_entry_point():
    original = adapters_mod._entry_points
    adapters_mod._entry_points = _fake_entry_points
    try:
        adapter = adapters_mod.build({"type": "fake_external", "greeting": "hello"})
        docs = list(adapter.documents())
    finally:
        adapters_mod._entry_points = original

    assert isinstance(adapter, FakeExternalAdapter)
    assert docs[0].title == "hello"


def test_a_built_in_name_is_never_shadowed_by_an_entry_point():
    """Even if a plugin registers itself as "html_blog", REGISTRY wins."""
    def _shadowing_entry_points(group):
        return [EntryPoint(name="html_blog", value=f"{__name__}:FakeExternalAdapter",
                           group=adapters_mod.ENTRY_POINT_GROUP)]

    original = adapters_mod._entry_points
    adapters_mod._entry_points = _shadowing_entry_points
    try:
        adapter = adapters_mod.build({"type": "html_blog", "path": "/does/not/matter"})
    finally:
        adapters_mod._entry_points = original

    assert isinstance(adapter, adapters_mod.HtmlBlogAdapter)


def test_an_unknown_type_reports_both_built_in_and_external_names():
    original = adapters_mod._entry_points
    adapters_mod._entry_points = _fake_entry_points
    try:
        try:
            adapters_mod.build({"type": "nonsense"})
            raised = False
        except ValueError as e:
            raised = True
            message = str(e)
    finally:
        adapters_mod._entry_points = original

    assert raised
    assert "html_blog" in message and "fake_external" in message


def test_no_entry_points_installed_still_resolves_built_ins():
    original = adapters_mod._entry_points
    adapters_mod._entry_points = _no_entry_points
    try:
        adapter = adapters_mod.build({"type": "obsidian", "path": "/does/not/matter"})
    finally:
        adapters_mod._entry_points = original

    assert isinstance(adapter, adapters_mod.ObsidianAdapter)
