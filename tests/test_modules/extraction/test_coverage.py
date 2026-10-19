"""Extraction coverage: what of a checkout reached the graph, and whether the result is complete."""

from __future__ import annotations

from deriva.modules.extraction.coverage import coverage_report


def _file(file_type: str, subtype: str = "") -> dict[str, str]:
    return {"file_type": file_type, "subtype": subtype}


def test_a_checkout_whose_source_files_gave_symbols_is_complete():
    report = coverage_report(
        checkout_files=["src/a.py", "src/b.py", "README.md"],
        graph_files={"src/a.py": _file("source", "python"), "src/b.py": _file("source", "python"), "README.md": _file("docs", "markdown")},
        read_by_step={"src/a.py": "parser", "src/b.py": "parser"},
        symbol_files={"src/a.py", "src/b.py"},
        node_counts={"File": 3, "TypeDefinition": 4},
        unreadable={},
    )

    assert report["complete"] is True and report["reasons"] == [] and report["notes"] == []
    assert report["files"] == 3 and report["in_graph"] == 3
    py = next(row for row in report["extensions"] if row["extension"] == ".py")
    assert py == {"extension": ".py", "files": 2, "in_graph": 2, "file_type": "source", "subtype": "python", "reader": "parser", "with_symbols": 2, "unreadable": 0}
    assert report["nodes"] == {"File": 3, "TypeDefinition": 4}


def test_extensions_are_listed_by_file_count():
    report = coverage_report(
        checkout_files=["a.md", "b.py", "c.py"],
        graph_files={"a.md": _file("docs"), "b.py": _file("source", "python"), "c.py": _file("source", "python")},
        read_by_step={"b.py": "parser", "c.py": "parser"},
        symbol_files={"b.py", "c.py"},
        node_counts={},
        unreadable={},
    )

    assert [row["extension"] for row in report["extensions"]] == [".py", ".md"]


def test_source_files_without_any_symbol_make_the_run_incomplete():
    report = coverage_report(
        checkout_files=["src/A.java", "src/B.java"],
        graph_files={"src/A.java": _file("source", "java"), "src/B.java": _file("source", "java")},
        read_by_step={"src/A.java": "parser", "src/B.java": "parser"},
        symbol_files=set(),
        node_counts={"File": 2},
        unreadable={},
    )

    assert report["complete"] is False
    assert report["reasons"] == ["none of the 2 source files gave a type or method (.java 2)"]


def test_extensions_no_step_reads_or_without_symbols_are_notes_not_reasons():
    """Shell scripts or a config .js file have no types by nature: the run stays complete while others gave symbols."""
    report = coverage_report(
        checkout_files=["a.kt", "b.kt", "c.py", "jest.config.js"],
        graph_files={"a.kt": _file("source", "kotlin"), "b.kt": _file("source", "kotlin"), "c.py": _file("source", "python"), "jest.config.js": _file("source", "javascript")},
        read_by_step={"c.py": "parser", "jest.config.js": "parser"},
        symbol_files={"c.py"},
        node_counts={},
        unreadable={},
    )

    assert report["complete"] is True and report["reasons"] == []
    assert report["notes"] == ["2 source files are read by no extraction step: .kt (2)", ".js: none of its 1 file gave a type or method"]
    assert next(row for row in report["extensions"] if row["extension"] == ".kt")["reader"] is None


def test_unreadable_and_missing_files_are_listed_in_full_and_counted():
    report = coverage_report(
        checkout_files=["deep/x.py", "y.py", "gone.xsd"],
        graph_files={"deep/x.py": _file("source", "python"), "y.py": _file("source", "python")},
        read_by_step={"deep/x.py": "parser", "y.py": "parser"},
        symbol_files={"y.py"},
        node_counts={},
        unreadable={"deep/x.py": "path over 260 characters: [WinError 3]"},
    )

    assert report["complete"] is False
    assert report["reasons"] == ["1 file is not in the graph (gone.xsd)", "1 file could not be read (deep/x.py: path over 260 characters: [WinError 3])"]
    assert report["missing"] == ["gone.xsd"]
    assert report["unreadable"] == [{"path": "deep/x.py", "reason": "path over 260 characters: [WinError 3]"}]
    assert report["in_graph"] == 2


def test_a_file_without_an_extension_is_listed_under_its_name():
    report = coverage_report(
        checkout_files=["Dockerfile"],
        graph_files={"Dockerfile": _file("infrastructure", "docker")},
        read_by_step={},
        symbol_files=set(),
        node_counts={},
        unreadable={},
    )

    assert report["extensions"][0]["extension"] == "(no extension)"
    assert report["complete"] is True
