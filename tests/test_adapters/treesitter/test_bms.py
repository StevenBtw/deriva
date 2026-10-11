"""Tests for the BMS structural extractor (screen maps)."""

from __future__ import annotations

import pytest

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.bms import BmsExtractor


def line(text: str, continued: bool = False) -> str:
    """One macro source line, with the continuation mark in column 72 when continued."""
    return (text.ljust(71) + "-" if continued else text) + "\n"


MAPSET = (
    "* A comment naming DFHMDI\n"
    + line("SETA    DFHMSD CTRL=(ALARM,FREEKB),", True)
    + line("               LANG=COBOL,", True)
    + line("               MODE=INOUT")
    + line("MAPA    DFHMDI COLUMN=1,", True)
    + line("               LINE=1,", True)
    + line("               SIZE=(24,80)")
    + line("        DFHMDF ATTRB=(ASKIP,NORM),", True)
    + line("               LENGTH=6,", True)
    + line("               POS=(1,1),", True)
    + line("               INITIAL='Name, first :'")
    + line("FIELDA  DFHMDF ATTRB=(FSET,IC,NORM,UNPROT),", True)
    + line("               LENGTH=8,", True)
    + line("               POS=(1,8)")
    + line("FIELDB  DFHMDF ATTRB=(ASKIP,FSET,NORM),", True)
    + line("               LENGTH=40,", True)
    + line("               POS=(2,1)")
    + line("MAPB    DFHMDI SIZE=(12,40)")
    + line("        DFHMDF POS=(1,1),LENGTH=4,INITIAL='It''s'")
    + line("        DFHMSD TYPE=FINAL")
    + line("        END")
)


@pytest.fixture
def manager():
    return TreeSitterManager()


class TestRegistration:
    def test_extractor_is_registered(self):
        extractor = get_extractor("bms")
        assert isinstance(extractor, BmsExtractor)
        assert extractor.language_name == "bms"
        assert extractor.get_language() is None

    @pytest.mark.parametrize("path", ["maps/seta.bms", "MAPS/SETA.BMS"])
    def test_extension_detects_bms(self, path):
        assert TreeSitterManager.detect_language(path) == "bms"

    def test_language_is_supported(self):
        assert TreeSitterManager.supports_language("bms")
        assert "bms" in TreeSitterManager.get_supported_languages()


class TestMaps:
    def test_each_map_is_a_screen_type(self, manager):
        types = manager.extract_types(MAPSET, file_path="seta.bms")
        assert [(t.name, t.kind) for t in types] == [("MAPA", "screen"), ("MAPB", "screen")]
        first, second = types
        assert (first.line_start, first.line_end) == (5, 17)
        assert (second.line_start, second.line_end) == (18, 19)

    def test_map_notes_its_mapset(self, manager):
        types = manager.extract_types(MAPSET, file_path="seta.bms")
        assert [t.decorators for t in types] == [["mapset:SETA"], ["mapset:SETA"]]

    def test_fields_and_labels_are_listed_in_the_docstring(self, manager):
        first, second = manager.extract_types(MAPSET, file_path="seta.bms")
        assert first.docstring == "Screen map MAPA of mapset SETA (24x80). Fields: FIELDA, FIELDB. Input fields: FIELDA. Labels: 'Name, first :'."
        assert second.docstring == "Screen map MAPB of mapset SETA (12x40). Labels: 'It's'."

    def test_maps_have_no_methods_imports_or_calls(self, manager):
        result = manager.extract_all(MAPSET, file_path="seta.bms")
        assert result["methods"] == []
        assert result["imports"] == []
        assert result["calls"] == []


class TestRobustness:
    @pytest.mark.parametrize("source", ["", "\n", "no macros here", "SETA DFHMSD", "MAPA DFHMDI", " DFHMDF INITIAL='open"])
    def test_odd_input_gives_empty_or_partial_results(self, manager, source):
        result = manager.extract_all(source, file_path="x.bms")
        assert set(result) == {"types", "methods", "imports", "calls"}

    def test_map_without_mapset_statement(self, manager):
        types = manager.extract_types("MAPA DFHMDI SIZE=(24,80)\n", file_path="x.bms")
        assert [t.name for t in types] == ["MAPA"]
        assert types[0].decorators == []
        assert types[0].docstring == "Screen map MAPA (24x80)."
