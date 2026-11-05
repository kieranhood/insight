"""The topology graph: which device hangs off which switch port.

Built from switch port neighbour (LLDP) and uplink data, with manual overrides from the
inventory taking precedence. Used to attach symptoms (unreachable APs) to causes (the
switch they share).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from insight.model import Port, device_key


@dataclass(frozen=True)
class Attachment:
    parent_key: str
    port_id: str | None
    manual: bool = False


class Topology:
    def __init__(self) -> None:
        self._parent: dict[str, Attachment] = {}

    @classmethod
    def build(
        cls,
        ports: Iterable[Port],
        overrides: dict[str, tuple[str, str | None]] | None = None,
    ) -> Topology:
        topo = cls()
        for port in ports:
            if not port.neighbour_mac:
                continue
            neighbour = device_key(mac=port.neighbour_mac, native_id=port.neighbour_mac)
            if neighbour == port.device_key:
                continue
            if port.is_uplink:
                # This device's uplink connects to the neighbour, which is its parent.
                topo._parent.setdefault(port.device_key, Attachment(neighbour, None))
            else:
                topo._parent[neighbour] = Attachment(port.device_key, port.port_id)
        for child, (parent, port_id) in (overrides or {}).items():
            topo._parent[child] = Attachment(parent, port_id, manual=True)
        topo._break_cycles()
        return topo

    def _break_cycles(self) -> None:
        for start in list(self._parent):
            seen = {start}
            node = start
            while node in self._parent:
                node = self._parent[node].parent_key
                if node in seen:
                    # Drop the non-manual edge closing the loop.
                    if not self._parent[start].manual:
                        del self._parent[start]
                    break
                seen.add(node)

    def parent(self, key: str) -> Attachment | None:
        return self._parent.get(key)

    def children(self, key: str) -> list[str]:
        return sorted(child for child, att in self._parent.items() if att.parent_key == key)

    def downstream(self, key: str) -> list[str]:
        """Every device that reaches the network through `key`, directly or indirectly."""
        result: list[str] = []
        stack = self.children(key)
        while stack:
            node = stack.pop()
            if node in result:
                continue
            result.append(node)
            stack.extend(self.children(node))
        return sorted(result)

    def path_to_root(self, key: str) -> list[str]:
        path: list[str] = []
        node = key
        while (att := self._parent.get(node)) is not None and att.parent_key not in path:
            path.append(att.parent_key)
            node = att.parent_key
        return path

    def edges(self) -> dict[str, Attachment]:
        return dict(self._parent)
