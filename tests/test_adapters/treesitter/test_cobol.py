"""Tests for the COBOL structural extractor (programs and copybooks)."""

from __future__ import annotations

import pytest

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.cobol import (
    COBOL_SYSTEM_COPYBOOKS,
    COBOL_SYSTEM_PROGRAMS,
    CobolExtractor,
)

BATCH_PROGRAM = """\
000100* A comment line with CALL 'IGNORED' and COPY IGNORED.
000200 IDENTIFICATION DIVISION.
000300 PROGRAM-ID.    PROGA.
000400 ENVIRONMENT DIVISION.
000500 INPUT-OUTPUT SECTION.
000600 FILE-CONTROL.
000700     SELECT FILE-A ASSIGN TO FILEA
000800            ORGANIZATION IS INDEXED.
000900     SELECT FILE-B ASSIGN TO UT-S-FILEB.
001000 DATA DIVISION.
001100 FILE SECTION.
001200 FD  FILE-A.
001300 01  FD-REC-A.
001400     05 FD-KEY-A                PIC 9(11).
001500 WORKING-STORAGE SECTION.
001600 COPY BOOKA.
001700 01  WS-AREA.
001800     05 WS-TARGET               PIC X(8) VALUE 'PROGC'.
001900     05 WS-TEXT                 PIC X(20) VALUE 'CALL FAILED'.
002000 LINKAGE SECTION.
002100 01  LK-PARM.
002200     05 LK-LEN                  PIC S9(4) COMP.
002300 PROCEDURE DIVISION USING LK-PARM.
002400     DISPLAY 'START'.
002500 0000-MAIN.
002600     PERFORM 1000-READ THRU 1000-EXIT
002700     PERFORM UNTIL WS-TARGET = SPACES
002800         CONTINUE
002900     END-PERFORM
003000     CALL 'PROGB' USING WS-AREA
003100     CALL WS-TARGET
003200     CALL 'CEE3AND'
003300     GOBACK.
003400 1000-READ.
003500     READ FILE-A.
003600 1000-EXIT.
003700     EXIT.
"""

ONLINE_PROGRAM = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CONSTANTS.
           05 LIT-FILE                PIC X(8) VALUE 'FILEC   '.
           05 LIT-NEXT                PIC X(8) VALUE 'PROGE'.
           05 WS-NEXT                 PIC X(8).
           05 WS-DYNAMIC              PIC X(8).
           COPY BOOKB.
           COPY DFHAID.
           EXEC SQL INCLUDE BOOKC END-EXEC.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
       MAIN-SECTION SECTION.
       MAIN-PARA.
           EXEC CICS RECEIVE
                MAP('MAPA')
                MAPSET('SETA')
           END-EXEC
           EXEC CICS READ
                DATASET   (LIT-FILE)
                INTO      (WS-CONSTANTS)
           END-EXEC
           EXEC SQL
                SELECT COL_A INTO :WS-NEXT
                  FROM SCHEMA_A.TABLE_A
                 WHERE COL_B = :WS-DYNAMIC
           END-EXEC
           EXEC SQL UPDATE TABLE_B SET COL_A = 1 END-EXEC
           EXEC SQL INSERT INTO TABLE_C (COL_A) VALUES (1) END-EXEC
           EXEC SQL DELETE FROM TABLE_D END-EXEC
           EXEC CICS WRITEQ TD QUEUE('QUEA') FROM(WS-NEXT) END-EXEC
           IF WS-DYNAMIC = SPACES
               MOVE LIT-NEXT TO WS-NEXT
           ELSE
               MOVE 'PROGF' TO
                    WS-NEXT
           END-IF
           EXEC CICS XCTL
                PROGRAM (WS-NEXT)
           END-EXEC.
       OTHER-PARA.
           EXEC CICS LINK PROGRAM('PROGG') END-EXEC
           EXEC CICS XCTL PROGRAM(WS-DYNAMIC) END-EXEC
           EXEC CICS RETURN TRANSID('TRNA') END-EXEC.
"""

COPYBOOK = """\
      * Record layout
       01  RECORD-A.
           05  FIELD-A                           PIC X(16).
           05  GROUP-B.
               10 FIELD-C                        PIC S9(10)V99 COMP-3.
               10 FIELD-D                        PIC 9(03).
                  88 FIELD-D-LOW                 VALUE 1.
           05  FILLER                            PIC X(59).
       01  RECORD-B.
           05  FIELD-E                           PIC X(8) VALUE 'PROGZ'.
"""

FRAGMENT = """\
           05  FIELD-A                  PIC X(06).
           05  FIELD-B                  PIC S9(05) COMP-3.
"""

PROCEDURE_COPYBOOK = """\
       COMMON-PARA.
           PERFORM COMMON-EXIT
           CALL 'PROGB'.
       COMMON-EXIT.
           EXIT.
"""


@pytest.fixture
def manager():
    return TreeSitterManager()


def names(items):
    return [item.name for item in items]


def callees(calls, caller):
    return [call.callee_name for call in calls if call.caller_name == caller]


class TestRegistration:
    def test_extractor_is_registered(self):
        extractor = get_extractor("cobol")
        assert isinstance(extractor, CobolExtractor)
        assert extractor.language_name == "cobol"

    def test_needs_no_grammar(self):
        assert CobolExtractor().get_language() is None

    @pytest.mark.parametrize("path", ["src/proga.cbl", "SRC/PROGA.CBL", "a.cob", "a.cobol", "copy/booka.cpy", "COPY/BOOKA.CPY"])
    def test_extensions_detect_cobol(self, path):
        assert TreeSitterManager.detect_language(path) == "cobol"

    def test_language_is_supported(self):
        assert TreeSitterManager.supports_language("cobol")
        assert "cobol" in TreeSitterManager.get_supported_languages()

    def test_filter_constants_hold_system_names(self, manager):
        constants = manager.get_filter_constants(file_path="a.cbl")
        assert constants.stdlib_modules == COBOL_SYSTEM_COPYBOOKS
        assert constants.builtin_functions == COBOL_SYSTEM_PROGRAMS
        assert "SQLCA" in COBOL_SYSTEM_COPYBOOKS
        assert "CEE3AND" in COBOL_SYSTEM_PROGRAMS


class TestBatchProgram:
    def test_program_is_one_type(self, manager):
        types = manager.extract_types(BATCH_PROGRAM, file_path="proga.cbl")
        assert names(types) == ["PROGA"]
        program = types[0]
        assert program.kind == "program"
        assert (program.line_start, program.line_end) == (2, 37)

    def test_batch_program_notes_its_files(self, manager):
        program = manager.extract_types(BATCH_PROGRAM, file_path="proga.cbl")[0]
        assert program.decorators == ["batch", "file:FILEA", "file:FILEB"]
        assert program.docstring == "Batch COBOL program PROGA. Files: FILEA, FILEB."

    def test_paragraphs_are_methods_after_the_entry_point(self, manager):
        methods = manager.extract_methods(BATCH_PROGRAM, file_path="proga.cbl")
        assert names(methods) == ["PROGA", "0000-MAIN", "1000-READ", "1000-EXIT"]
        entry, main, read, last = methods
        assert entry.class_name is None
        assert (entry.line_start, entry.line_end) == (23, 24)
        assert entry.parameters == [{"name": "LK-PARM"}]
        assert main.class_name == "PROGA"
        assert (main.line_start, main.line_end) == (25, 33)
        assert (read.line_start, read.line_end) == (34, 35)
        assert (last.line_start, last.line_end) == (36, 37)

    def test_copy_is_an_import(self, manager):
        imports = manager.extract_imports(BATCH_PROGRAM, file_path="proga.cbl")
        assert [(i.module, i.line) for i in imports] == [("BOOKA", 16)]

    def test_calls_and_performs(self, manager):
        calls = manager.extract_calls(BATCH_PROGRAM, file_path="proga.cbl")
        assert callees(calls, "0000-MAIN") == ["1000-READ", "PROGB", "PROGC", "CEE3AND"]
        call = next(c for c in calls if c.callee_name == "PROGB")
        assert call.caller_class == "PROGA"
        assert call.callee_qualifier is None
        assert call.line == 30

    def test_entry_point_with_statements_does_not_fall_through(self, manager):
        calls = manager.extract_calls(BATCH_PROGRAM, file_path="proga.cbl")
        assert callees(calls, "PROGA") == []

    def test_entry_point_statements_are_its_calls(self, manager):
        source = BATCH_PROGRAM.replace("DISPLAY 'START'.", "PERFORM 1000-READ.")
        calls = manager.extract_calls(source, file_path="proga.cbl")
        assert callees(calls, "PROGA") == ["1000-READ"]
        assert calls[0].caller_class is None

    def test_literals_and_comments_are_not_statements(self, manager):
        result = manager.extract_all(BATCH_PROGRAM, file_path="proga.cbl")
        assert "IGNORED" not in [c.callee_name for c in result["calls"]]
        assert "FAILED" not in [c.callee_name for c in result["calls"]]
        assert "IGNORED" not in [i.module for i in result["imports"]]

    def test_program_records_are_not_types(self, manager):
        types = manager.extract_types(BATCH_PROGRAM, file_path="proga.cbl")
        assert "WS-AREA" not in names(types)


class TestOnlineProgram:
    def test_online_program_notes_its_resources(self, manager):
        program = manager.extract_types(ONLINE_PROGRAM, file_path="progd.cbl")[0]
        assert program.name == "PROGD"
        assert program.decorators == [
            "online",
            "cics",
            "sql",
            "file:FILEC",
            "table:SCHEMA_A.TABLE_A",
            "table:TABLE_B",
            "table:TABLE_C",
            "table:TABLE_D",
            "map:MAPA",
            "mapset:SETA",
            "queue:QUEA",
            "transaction:TRNA",
        ]
        assert program.docstring is not None
        assert program.docstring.startswith("Online COBOL program PROGD.")

    def test_sections_and_paragraphs_are_methods(self, manager):
        methods = manager.extract_methods(ONLINE_PROGRAM, file_path="progd.cbl")
        assert names(methods) == ["PROGD", "MAIN-SECTION", "MAIN-PARA", "OTHER-PARA"]
        section = methods[1]
        assert (section.line_start, section.line_end) == (15, 46)

    def test_empty_entry_point_and_section_fall_through(self, manager):
        calls = manager.extract_calls(ONLINE_PROGRAM, file_path="progd.cbl")
        assert callees(calls, "PROGD") == ["MAIN-SECTION"]
        assert callees(calls, "MAIN-SECTION") == ["MAIN-PARA"]
        assert calls[0].caller_class is None
        assert "OTHER-PARA" not in [c.callee_name for c in calls]

    def test_program_transfers_are_calls(self, manager):
        calls = manager.extract_calls(ONLINE_PROGRAM, file_path="progd.cbl")
        assert callees(calls, "MAIN-PARA") == ["PROGE", "PROGF"]
        assert callees(calls, "OTHER-PARA") == ["PROGG"]

    def test_copybooks_and_sql_includes_are_imports(self, manager):
        imports = manager.extract_imports(ONLINE_PROGRAM, file_path="progd.cbl")
        assert [i.module for i in imports] == ["BOOKB", "DFHAID", "BOOKC", "SQLCA"]

    def test_message_queue_and_database_calls_are_noted(self, manager):
        source = ONLINE_PROGRAM.replace("EXEC CICS LINK PROGRAM('PROGG') END-EXEC", "CALL 'MQOPEN'\n           CALL 'CBLTDLI'")
        program = manager.extract_types(source, file_path="progd.cbl")[0]
        assert "mq" in program.decorators
        assert "ims" in program.decorators

    def test_dli_segments_are_noted(self, manager):
        source = ONLINE_PROGRAM.replace(
            "EXEC CICS LINK PROGRAM('PROGG') END-EXEC",
            "EXEC DLI GU USING PCB(1) SEGMENT (SEGA) INTO (WS-NEXT) END-EXEC",
        )
        program = manager.extract_types(source, file_path="progd.cbl")[0]
        assert "ims" in program.decorators
        assert "segment:SEGA" in program.decorators


class TestSeveralPrograms:
    def test_each_program_id_is_a_type(self, manager):
        second = ONLINE_PROGRAM.replace("PROGD", "PROGH")
        result = manager.extract_all(ONLINE_PROGRAM + second, file_path="both.cbl")
        assert names(result["types"]) == ["PROGD", "PROGH"]
        first, last = result["types"]
        assert (first.line_start, first.line_end) == (1, 46)
        assert (last.line_start, last.line_end) == (47, 92)
        assert [m.class_name for m in result["methods"] if m.name == "MAIN-PARA"] == ["PROGD", "PROGH"]


class TestCopybook:
    def test_each_record_is_a_type(self, manager):
        types = manager.extract_types(COPYBOOK, file_path="copy/booka.cpy")
        assert names(types) == ["RECORD-A", "RECORD-B"]
        record = types[0]
        assert record.kind == "record"
        assert (record.line_start, record.line_end) == (2, 8)

    def test_fields_are_listed_in_the_docstring(self, manager):
        record = manager.extract_types(COPYBOOK, file_path="copy/booka.cpy")[0]
        assert record.docstring == "Data record RECORD-A. Fields: FIELD-A X(16), GROUP-B, FIELD-C S9(10)V99 COMP-3, FIELD-D 9(03)."

    def test_data_copybook_has_no_methods_or_calls(self, manager):
        result = manager.extract_all(COPYBOOK, file_path="copy/booka.cpy")
        assert result["methods"] == []
        assert result["calls"] == []
        assert result["imports"] == []

    def test_fragment_is_named_after_the_member(self, manager):
        types = manager.extract_types(FRAGMENT, file_path="copy/bookd.cpy")
        assert names(types) == ["BOOKD"]
        assert types[0].docstring == "Data record BOOKD. Fields: FIELD-A X(06), FIELD-B S9(05) COMP-3."
        assert (types[0].line_start, types[0].line_end) == (1, 2)

    def test_procedure_copybook_gives_methods_without_a_type(self, manager):
        result = manager.extract_all(PROCEDURE_COPYBOOK, file_path="copy/booke.cpy")
        assert result["types"] == []
        assert names(result["methods"]) == ["COMMON-PARA", "COMMON-EXIT"]
        assert result["methods"][0].class_name is None
        assert callees(result["calls"], "COMMON-PARA") == ["COMMON-EXIT", "PROGB"]


class TestRobustness:
    @pytest.mark.parametrize("source", ["", "\n\n", "not cobol at all", "       PROGRAM-ID.", "       01", "\x00\x01 EXEC CICS"])
    def test_odd_input_gives_empty_or_partial_results(self, manager, source):
        result = manager.extract_all(source, file_path="x.cbl")
        assert set(result) == {"types", "methods", "imports", "calls"}

    def test_lowercase_source_is_read(self, manager):
        types = manager.extract_types(BATCH_PROGRAM.lower(), file_path="proga.cbl")
        assert names(types) == ["PROGA"]

    def test_crlf_line_endings(self, manager):
        methods = manager.extract_methods(BATCH_PROGRAM.replace("\n", "\r\n"), file_path="proga.cbl")
        assert names(methods) == ["PROGA", "0000-MAIN", "1000-READ", "1000-EXIT"]

    def test_text_after_column_72_is_ignored(self, manager):
        line = "           CALL 'PROGB'".ljust(72) + "CALL 'PROGX'\n"
        source = "       PROGRAM-ID. PROGA.\n       PROCEDURE DIVISION.\n       MAIN-PARA.\n" + line
        calls = manager.extract_calls(source, file_path="proga.cbl")
        assert callees(calls, "MAIN-PARA") == ["PROGB"]
