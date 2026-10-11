"""A realistic sample of a graph too large to draw: node types in their real proportions, the most connected nodes first.

Structure only (no LLM, no randomness): the same graph gives the same sample. Each node type gets slots in
proportion to its count (at least one while slots last); the slots fill best-first with the node that has the most
edges into the sample so far, then the most edges overall, then a stable hash of its id. So the sample keeps
relationships instead of scattering unconnected nodes.
"""

from __future__ import annotations

import hashlib
import heapq
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence


def allocate(counts: Mapping[str, int], slots: int) -> dict[str, int]:
    """Slots per type in proportion to its count (largest remainder), at least one for every type while slots last."""
    quotas = {name: 0 for name in counts}
    present = {name: count for name, count in counts.items() if count > 0}
    total = sum(present.values())
    if slots >= total:
        return {name: present.get(name, 0) for name in counts}
    by_size = sorted(present, key=lambda name: (-present[name], name))
    if slots < len(present):
        for name in by_size[:slots]:
            quotas[name] = 1
        return quotas
    exact = {name: slots * present[name] / total for name in present}
    for name in present:
        quotas[name] = max(1, int(exact[name]))
    # Hand out what rounding down left over (largest remainder first), or take back what the one-slot minimum overdrew
    left = slots - sum(quotas.values())
    by_remainder = sorted(present, key=lambda name: (-(exact[name] - int(exact[name])), -present[name], name))
    while left > 0:
        # Never more slots than a type has nodes: a full type passes its turn
        room = [name for name in by_remainder if quotas[name] < present[name]]
        if not room:
            break
        for name in room[:left]:
            quotas[name] += 1
            left -= 1
    overdrawn = sorted((name for name in present if quotas[name] > 1), key=lambda name: (exact[name] - quotas[name], name))
    for name in overdrawn[: max(0, -left)]:
        quotas[name] -= 1
    return quotas


def _rank(node: str) -> bytes:
    return hashlib.blake2b(node.encode(), digest_size=8).digest()


def sample_nodes(types: Mapping[str, str], edges: Iterable[tuple[str, str]], budget: int, first: Sequence[str] = ()) -> list[str]:
    """Up to ``budget`` node ids of ``types`` (id to node type): ``first`` (known ids, in order), then the best-first fill."""
    if budget <= 0:
        return []
    neighbours: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        if a != b and a in types and b in types:
            neighbours[a].add(b)
            neighbours[b].add(a)

    picked = list(dict.fromkeys(node for node in first if node in types))[:budget]
    chosen = set(picked)
    # First nodes count toward their type's share; where they exceed it, the other types make room
    target = allocate(Counter(types.values()), budget)
    held = Counter(types[node] for node in picked)
    remaining = {name: max(0, quota - held[name]) for name, quota in target.items()}
    room = budget - len(picked)
    if sum(remaining.values()) > room:
        remaining = allocate(remaining, room)

    links: Counter[str] = Counter()
    for node in picked:
        for other in neighbours[node]:
            links[other] += 1
    heap = [(-links[node], -len(neighbours[node]), _rank(node), node) for node in types if node not in chosen and remaining[types[node]] > 0]
    heapq.heapify(heap)
    # An entry goes stale when its node gains a link; the newer entry ranks higher and is taken first
    while heap and len(picked) < budget:
        *_, node = heapq.heappop(heap)
        if node in chosen or remaining[types[node]] == 0:
            continue
        picked.append(node)
        chosen.add(node)
        remaining[types[node]] -= 1
        for other in neighbours[node]:
            if other not in chosen and remaining[types[other]] > 0:
                links[other] += 1
                heapq.heappush(heap, (-links[other], -len(neighbours[other]), _rank(other), other))
    return picked
