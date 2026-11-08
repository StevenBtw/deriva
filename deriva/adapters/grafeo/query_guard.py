"""What a user-typed query may do on Deriva's graph: read, and call only grafeo's read-only procedures.

A query someone types (the studio's query bar, a draft candidate query in a dry run) runs in a transaction that is
rolled back, but a rollback cannot make everything safe: a schema statement (CREATE CONSTRAINT and the like) survives
it, and LOAD CSV or a load procedure reads local files and returns what it read. Such a query is refused before any
database is asked. One check for every caller, so the routes and the services cannot drift apart.
"""

from __future__ import annotations

import re

__all__ = ["READ_PROCEDURES", "WRITE_CLAUSES", "QueryRefused", "check_read_only", "is_write_query", "read_only_refusal", "refused_procedure"]

# String literals, backticked names and comments: words there are no clauses (scanned left to right, so a // inside a
# string stays part of the string). The two languages differ in comments: GQL also starts one with --, which in Cypher is
# an undirected edge, so a query is read both ways and a finding in either reading counts (a quote inside a -- comment
# would otherwise open a string that hides what follows)
_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""
_SKIPPED_CYPHER = re.compile(_STRING + r"|`[^`]*`|//[^\n]*|/\*.*?\*/", re.DOTALL)
_SKIPPED_GQL = re.compile(_STRING + r"|`[^`]*`|//[^\n]*|--[^\n]*|/\*.*?\*/", re.DOTALL)
# A backticked name stays visible as this mark, so a procedure named in backticks cannot pass as no name
_HIDDEN = "\x00"
# The clauses that write, change the schema or load files: the check and its refusal message both come from this list
WRITE_CLAUSES = ("ALTER", "CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP", "INSERT", "LOAD")
_WRITE = re.compile(rf"\b({'|'.join(WRITE_CLAUSES)})\b", re.IGNORECASE)
# The procedures a user-typed query may call: grafeo's read-only ones (graph algorithms, catalog lists, searches), as
# grafeo.procedures() lists them. Any other is refused, so a procedure added later stays out until it is listed here:
# grafeo.load_nodes_csv and grafeo.load_edges_csv read local files, and a rolled-back query still returns what they read.
# A stopgap: grafeo 0.6.2 is to offer a read-only (untrusted) transaction that refuses all file IO, which replaces it
READ_PROCEDURES = frozenset(
    {
        "grafeo.articulation_points",
        "grafeo.bellman_ford",
        "grafeo.betweenness_centrality",
        "grafeo.bfs",
        "grafeo.bridges",
        "grafeo.closeness_centrality",
        "grafeo.clustering_coefficient",
        "grafeo.connected_components",
        "grafeo.degree_centrality",
        "grafeo.dfs",
        "grafeo.dijkstra",
        "grafeo.floyd_warshall",
        "grafeo.kcore",
        "grafeo.kruskal",
        "grafeo.label_propagation",
        "grafeo.labels",
        "grafeo.louvain",
        "grafeo.max_flow",
        "grafeo.min_cost_max_flow",
        "grafeo.pagerank",
        "grafeo.prim",
        "grafeo.procedures",
        "grafeo.propertykeys",
        "grafeo.relationshiptypes",
        "grafeo.search.mmr",
        "grafeo.search.text",
        "grafeo.search.vector",
        "grafeo.sssp",
        "grafeo.strongly_connected_components",
        "grafeo.topological_sort",
    }
)
# CALL and what follows it: a procedure name (dotted), or a subquery's brace
# CALL as a word of its own, not a property (n.call) or a label (:Call); what follows decides whether it is a clause
_CALL = re.compile(r"(?<![.:\w$])CALL\b", re.IGNORECASE)
_NAME = re.compile(r"[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*")


def _readings(query: str) -> tuple[str, str]:
    """The query with its strings and comments blanked, read as Cypher and as GQL (backticked names marked)."""

    def blank(match: re.Match[str]) -> str:
        return _HIDDEN if match.group(0).startswith("`") else " "

    return _SKIPPED_CYPHER.sub(blank, query), _SKIPPED_GQL.sub(blank, query)


def is_write_query(query: str) -> bool:
    """True when the query uses a write clause outside string literals, backticked names and comments, read as either
    language."""
    return any(_WRITE.search(reading) for reading in _readings(query))


def refused_procedure(query: str) -> str | None:
    """The first procedure the query calls that is not on ``READ_PROCEDURES`` (``"?"`` for one whose name is hidden in
    backticks, in whole or in part), in either reading; None when every CALL clause is a listed procedure or a subquery
    (``CALL { ... }``). A CALL followed by no name (a variable or label called call) is no clause."""
    for reading in _readings(query):
        for call in _CALL.finditer(reading):
            rest = reading[call.end() :].lstrip()
            if rest.startswith("{"):
                continue
            if rest.startswith(_HIDDEN):
                return "?"
            name = _NAME.match(rest)
            if name is None:
                continue
            if rest[name.end() :].lstrip().startswith((".", _HIDDEN)):
                return "?"
            written = re.sub(r"\s+", "", name.group(0))
            if written.lower() not in READ_PROCEDURES:
                return written
    return None


class QueryRefused(ValueError):
    """A user-typed query that the read-only path does not run (its message says why)."""


def read_only_refusal(query: str) -> str | None:
    """Why a user-typed query is refused (a write or schema clause, LOAD, a procedure off ``READ_PROCEDURES``), or None
    when it may run."""
    if is_write_query(query):
        return f"Queries here are read-only: this one writes or loads ({', '.join(WRITE_CLAUSES[:-1])} or {WRITE_CLAUSES[-1]})"
    if (procedure := refused_procedure(query)) is not None:
        return f"Only grafeo's read-only procedures can be called (graph algorithms, catalog lists, searches), not {procedure}"
    return None


def check_read_only(query: str) -> None:
    """Raise ``QueryRefused`` for a query the read-only path does not run."""
    if (reason := read_only_refusal(query)) is not None:
        raise QueryRefused(reason)
