"""跨设备身份关联及其历史状态。

身份关联不是一次性事实：它可能先被提出、之后确认，也可能在确认后被否决。
归因审阅必须能够按审阅时点（``as_of``）还原当时的状态，而不是使用“现在”的
最终状态覆盖旧周报。本模块只保存关联变更历史，不判断业务对错。
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

VALID_STATUSES = ("proposed", "confirmed", "rejected")


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class IdentityState:
    """某一时点的身份关联视图。

    ``merge_statuses`` 决定哪些关联会被并入同一身份。正常审阅只并入
    ``confirmed``；计算“潜在身份”时可以额外并入 ``proposed``，用于说明
    哪些事件因为关联尚未确认而只能保留为未归因。
    """

    def __init__(self, records: dict[str, dict], merge_statuses: tuple[str, ...]) -> None:
        self.records = deepcopy(records)
        self.merge_statuses = tuple(merge_statuses)
        self._parent: dict[str, str] = {}
        for record in self.records.values():
            self._ensure(record["left"])
            self._ensure(record["right"])
            if record["status"] in self.merge_statuses:
                self._union(record["left"], record["right"])

    def _ensure(self, identifier: str) -> None:
        self._parent.setdefault(identifier, identifier)

    def _find(self, identifier: str) -> str:
        self._ensure(identifier)
        root = identifier
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[identifier] != identifier:
            parent = self._parent[identifier]
            self._parent[identifier] = root
            identifier = parent
        return root

    def _union(self, left: str, right: str) -> None:
        left_root, right_root = self._find(left), self._find(right)
        if left_root == right_root:
            return
        # 固定用字典序较小的成员作为根，保证输出稳定。
        if left_root < right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root

    def resolve(self, identifier: str) -> str:
        return self._find(identifier)

    def component(self, identifier: str) -> set[str]:
        root = self._find(identifier)
        return {member for member in self._parent if self._find(member) == root}

    def links(self) -> list[dict]:
        return [deepcopy(self.records[key]) for key in sorted(self.records)]

    def links_touching(self, identifier: str, statuses: tuple[str, ...] | None = None) -> list[dict]:
        component = self.component(identifier)
        allowed = set(statuses) if statuses is not None else None
        result = []
        for key in sorted(self.records):
            record = self.records[key]
            if allowed is not None and record["status"] not in allowed:
                continue
            if record["left"] in component or record["right"] in component:
                result.append(deepcopy(record))
        return result

    def link_path(self, left: str, right: str, statuses: tuple[str, ...] | None = None) -> list[str]:
        """返回两个身份之间由指定状态关联组成的路径（关联编号列表）。"""

        if left == right:
            return []
        allowed = set(statuses) if statuses is not None else None
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for key in sorted(self.records):
            record = self.records[key]
            if allowed is not None and record["status"] not in allowed:
                continue
            adjacency.setdefault(record["left"], []).append((record["right"], key))
            adjacency.setdefault(record["right"], []).append((record["left"], key))
        queue: list[tuple[str, list[str]]] = [(left, [])]
        seen = {left}
        while queue:
            current, path = queue.pop(0)
            for neighbour, link_id in adjacency.get(current, []):
                if neighbour == right:
                    return path + [link_id]
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                queue.append((neighbour, path + [link_id]))
        return []

    def fingerprint(self) -> str:
        return sha256(_canonical_json(self.links()).encode("utf-8")).hexdigest()[:16]


class IdentityGraph:
    """按时间追加身份关联的提出、确认与否决。"""

    def __init__(self) -> None:
        self._changes: list[dict] = []
        self._sequence = 0

    def link(
        self,
        left: str,
        right: str,
        status: str = "proposed",
        at: int = 0,
        *,
        link_id: str | None = None,
        confidence: str | None = None,
    ) -> str:
        if not isinstance(left, str) or not isinstance(right, str) or not left or not right:
            raise ValueError("身份编号必须为非空字符串")
        if left == right:
            raise ValueError("身份关联的两端不能相同")
        if status not in VALID_STATUSES:
            raise ValueError(f"不支持的身份关联状态: {status}")
        if not isinstance(at, int):
            raise ValueError("身份关联时间必须为整数")
        pair = _pair(left, right)
        if link_id is None:
            link_id = f"{pair[0]}|{pair[1]}"
        for change in self._changes:
            if change["link_id"] == link_id and _pair(change["left"], change["right"]) != pair:
                raise ValueError("关联编号已用于另一对身份")
        self._sequence += 1
        self._changes.append(
            {
                "link_id": link_id,
                "left": pair[0],
                "right": pair[1],
                "status": status,
                "at": at,
                "confidence": confidence if confidence is not None else status,
                "sequence": self._sequence,
            }
        )
        return link_id

    def latest_at(self) -> int | None:
        if not self._changes:
            return None
        return max(change["at"] for change in self._changes)

    def state(self, as_of: int | None = None, *, include_proposed: bool = False) -> IdentityState:
        changes = [
            change for change in self._changes
            if as_of is None or change["at"] <= as_of
        ]
        changes.sort(key=lambda change: (change["at"], change["sequence"]))
        current: dict[str, dict] = {}
        for change in changes:
            current[change["link_id"]] = {
                "link_id": change["link_id"],
                "left": change["left"],
                "right": change["right"],
                "status": change["status"],
                "at": change["at"],
                "confidence": change["confidence"],
            }
        merge_statuses = ("confirmed", "proposed") if include_proposed else ("confirmed",)
        return IdentityState(current, merge_statuses)
