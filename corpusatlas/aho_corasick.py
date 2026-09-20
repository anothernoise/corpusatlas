"""Aho-Corasick multi-pattern string matching automaton.

Linear-time O(L + M) exact keyword search across arbitrary documents,
independent of dictionary size. Supports word boundary enforcement (\b)
without regex backtracking.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterator


class _AhoNode:
    __slots__ = ("children", "fail", "outputs")

    def __init__(self):
        self.children: dict[str, _AhoNode] = {}
        self.fail: _AhoNode | None = None
        self.outputs: list[tuple[str, Any]] = []


class AhoCorasick:
    """Trie-based Aho-Corasick automaton with failure and dictionary links."""

    def __init__(self, case_sensitive: bool = False):
        self.root = _AhoNode()
        self.case_sensitive = case_sensitive
        self._built = False

    def add_word(self, word: str, payload: Any = None) -> None:
        if not word:
            return
        self._built = False
        target = word if self.case_sensitive else word.lower()
        node = self.root
        for ch in target:
            if ch not in node.children:
                node.children[ch] = _AhoNode()
            node = node.children[ch]
        node.outputs.append((word, payload))

    def build(self) -> None:
        """Construct failure transitions and output links via BFS."""
        queue: deque[_AhoNode] = deque()

        # Depth 1 nodes fail to root
        for child in self.root.children.values():
            child.fail = self.root
            queue.append(child)

        # BFS for deeper nodes
        while queue:
            curr = queue.popleft()
            for ch, child in curr.children.items():
                fail_node = curr.fail
                while fail_node is not None and ch not in fail_node.children:
                    fail_node = fail_node.fail

                child.fail = fail_node.children[ch] if fail_node is not None else self.root
                # Inherit outputs from fail link
                if child.fail.outputs:
                    child.outputs.extend(child.fail.outputs)

                queue.append(child)

        self._built = True

    def find_matches(self, text: str, word_boundaries: bool = True) -> Iterator[tuple[int, int, str, Any]]:
        """Yield (start_idx, end_idx, original_word, payload) for all matches."""
        if not self._built:
            self.build()

        search_text = text if self.case_sensitive else text.lower()
        curr: _AhoNode | None = self.root
        n = len(search_text)

        for i, ch in enumerate(search_text):
            while curr is not None and ch not in curr.children:
                curr = curr.fail

            if curr is None:
                curr = self.root
                continue

            curr = curr.children[ch]
            if curr.outputs:
                for word, payload in curr.outputs:
                    start_idx = i - len(word) + 1
                    end_idx = i + 1

                    if word_boundaries:
                        # Check character before match
                        if start_idx > 0 and (text[start_idx - 1].isalnum() or text[start_idx - 1] in ("_", "-")):
                            continue
                        # Check character after match
                        if end_idx < n and (text[end_idx].isalnum() or text[end_idx] in ("_", "-")):
                            continue

                    yield start_idx, end_idx, word, payload
