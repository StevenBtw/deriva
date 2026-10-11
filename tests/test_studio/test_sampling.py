"""A realistic sample of a large graph: node types in their real proportions, the most connected nodes first."""

from __future__ import annotations

from collections import Counter

from deriva.studio.sampling import allocate, sample_nodes

# The node types of an extracted repository graph (deriva's own, 2026-10-09), without its one repository
COUNTS = {"Method": 1392, "TypeDefinition": 882, "File": 334, "Directory": 51, "BusinessConcept": 44, "ExternalDependency": 39, "Technology": 14}


def tree(directories: int = 4, files: int = 20, methods: int = 5) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Directories contain files, files contain methods, and each method calls the next one in its file."""
    types: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    for d in range(directories):
        types[f"d{d}"] = "Directory"
    for f in range(files):
        types[f"f{f}"] = "File"
        edges.append((f"d{f % directories}", f"f{f}"))
        for m in range(methods):
            types[f"f{f}m{m}"] = "Method"
            edges.append((f"f{f}", f"f{f}m{m}"))
            if m:
                edges.append((f"f{f}m{m - 1}", f"f{f}m{m}"))
    return types, edges


def induced(sample: list[str], edges: list[tuple[str, str]]) -> list[tuple[str, str]]:
    chosen = set(sample)
    return [(a, b) for a, b in edges if a in chosen and b in chosen]


def test_allocate_gives_each_type_its_share_and_at_least_one_slot():
    quotas = allocate(COUNTS, 299)

    total = sum(COUNTS.values())
    assert sum(quotas.values()) == 299
    assert min(quotas.values()) >= 1
    for name, count in COUNTS.items():
        assert abs(quotas[name] - 299 * count / total) < 1.5, name


def test_allocate_takes_back_what_the_one_slot_minimum_overdraws():
    assert allocate({"a": 100, "b": 1, "c": 1}, 5) == {"a": 3, "b": 1, "c": 1}


def test_allocate_with_fewer_slots_than_types_serves_the_largest_types():
    assert allocate({"a": 10, "b": 5, "c": 1}, 2) == {"a": 1, "b": 1, "c": 0}


def test_allocate_with_room_for_everything_takes_everything():
    assert allocate({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}


def test_a_graph_within_the_budget_comes_back_whole():
    types, edges = tree(directories=1, files=2, methods=2)

    assert sorted(sample_nodes(types, edges, 100)) == sorted(types)


def test_the_sample_has_the_real_mix_of_node_types():
    types, edges = tree()

    sample = sample_nodes(types, edges, 31)

    assert len(sample) == 31
    assert Counter(types[n] for n in sample) == Counter(allocate(Counter(types.values()), 31))


def test_the_most_connected_nodes_come_first_so_no_node_stands_alone():
    types, edges = tree()

    sample = sample_nodes(types, edges, 31)

    touched = {n for edge in induced(sample, edges) for n in edge}
    assert set(sample) == touched


def test_the_sample_does_not_depend_on_the_order_of_the_input():
    types, edges = tree()

    reordered = dict(reversed(list(types.items())))

    assert sample_nodes(types, edges, 31) == sample_nodes(reordered, list(reversed(edges)), 31)


def test_first_nodes_lead_and_count_toward_their_type():
    types, edges = tree()

    sample = sample_nodes(types, edges, 31, first=["f7m3", "f9m1", "unknown"])

    assert sample[:2] == ["f7m3", "f9m1"]
    assert Counter(types[n] for n in sample) == Counter(allocate(Counter(types.values()), 31))


def test_first_nodes_beyond_their_share_stay_and_the_others_make_room():
    types, edges = tree()

    sample = sample_nodes(types, edges, 31, first=["d0", "d1", "d2"])

    assert sample[:3] == ["d0", "d1", "d2"]
    assert len(sample) == 31


def test_first_nodes_are_cut_at_the_budget():
    types, edges = tree()

    assert sample_nodes(types, edges, 2, first=["d0", "d1", "d2"]) == ["d0", "d1"]
