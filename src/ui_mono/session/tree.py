from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionTreeNode:
    session_id: str
    parent_id: str | None = None
    branch_label: str | None = None
    path: Path | None = None
    children: list["SessionTreeNode"] = field(default_factory=list)


@dataclass
class SessionTree:
    root: SessionTreeNode | None = None

    def attach(self, node: SessionTreeNode) -> None:
        if self.root is None:
            self.root = node
            return
        parent = self.find(node.parent_id) if node.parent_id else None
        if parent is None:
            self.root.children.append(node)
        else:
            parent.children.append(node)

    def find(self, session_id: str | None) -> SessionTreeNode | None:
        if session_id is None or self.root is None:
            return None
        return self._find(self.root, session_id)

    def _find(self, node: SessionTreeNode, session_id: str) -> SessionTreeNode | None:
        if node.session_id == session_id:
            return node
        for child in node.children:
            found = self._find(child, session_id)
            if found is not None:
                return found
        return None
