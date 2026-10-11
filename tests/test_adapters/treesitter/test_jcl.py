"""Tests for the JCL structural extractor (jobs and procedures)."""

from __future__ import annotations

import pytest

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.jcl import JCL_SYSTEM_PROGRAMS, JclExtractor

JOB = """\
//JOBA     JOB 'RUN A',CLASS=A,MSGCLASS=0,
//         NOTIFY=&SYSUID
//* A comment with EXEC PGM=IGNORED
//   SET HLQ=LEVEL.ONE
//STEP01   EXEC PGM=PROGA
//STEPLIB  DD DISP=SHR,
//            DSN=&HLQ..LOADLIB
//SYSOUT   DD SYSOUT=*
//FILEA    DD DISP=SHR,
//         DSN=LEVEL.ONE.FILEA.KSDS
//FILEB    DD DISP=(NEW,CATLG,DELETE),
//         UNIT=SYSDA,
//         DSN=LEVEL.ONE.FILEB(+1)
//STEP02   EXEC PROC=PROCA,
//         PARM1=LEVEL.ONE
//STEP03   EXEC PROCB
//STEP04   EXEC PGM=IKJEFT01
//SYSTSIN  DD *
  DSN SYSTEM(SYSA)
  RUN PROGRAM(PROGB) PLAN(PLANA)
  END
/*
//STEP05   EXEC PGM=SORT        RUN PROGRAM(IGNORED)
//SORTIN   DD DSN=LEVEL.ONE.FILEA.KSDS,DISP=SHR
//         DD DSN=LEVEL.ONE.FILEC,DISP=SHR
//SYSIN    DD *
 SORT FIELDS=(1,4,CH,A)
/*
//         EXEC PGM=PROGC
"""

PROCEDURE = """\
//PROCA  PROC LIB=LEVEL.TWO
//PRC001 EXEC PGM=PROGD
//FILEIN  DD DISP=SHR,
//        DSN=&LIB(MEMBERA)
//TEMP    DD DSN=&&WORK,DISP=(NEW,PASS)
// PEND
"""

MEMBER_WITHOUT_HEADER = """\
//STEP01 EXEC PGM=PROGE
//FILEA  DD DSN=LEVEL.ONE.FILEA,DISP=OLD
"""


@pytest.fixture
def manager():
    return TreeSitterManager()


def names(items):
    return [item.name for item in items]


class TestRegistration:
    def test_extractor_is_registered(self):
        extractor = get_extractor("jcl")
        assert isinstance(extractor, JclExtractor)
        assert extractor.language_name == "jcl"
        assert extractor.get_language() is None

    @pytest.mark.parametrize("path", ["jobs/joba.jcl", "JOBS/JOBA.JCL", "proc/proca.prc", "proc/proca.proc"])
    def test_extensions_detect_jcl(self, path):
        assert TreeSitterManager.detect_language(path) == "jcl"

    def test_language_is_supported(self):
        assert TreeSitterManager.supports_language("jcl")
        assert "jcl" in TreeSitterManager.get_supported_languages()

    def test_system_programs_are_filtered(self, manager):
        constants = manager.get_filter_constants(file_path="a.jcl")
        assert constants.builtin_functions == JCL_SYSTEM_PROGRAMS
        assert {"IEFBR14", "IDCAMS", "SORT", "IKJEFT01"} <= JCL_SYSTEM_PROGRAMS


class TestJob:
    def test_job_is_one_type(self, manager):
        types = manager.extract_types(JOB, file_path="joba.jcl")
        assert names(types) == ["JOBA"]
        job = types[0]
        assert job.kind == "job"
        assert (job.line_start, job.line_end) == (1, 29)

    def test_job_notes_its_datasets(self, manager):
        job = manager.extract_types(JOB, file_path="joba.jcl")[0]
        assert job.decorators == [
            "dataset:LEVEL.ONE.FILEA.KSDS",
            "dataset:LEVEL.ONE.FILEB",
            "dataset:LEVEL.ONE.FILEC",
            "dataset:LEVEL.ONE.LOADLIB",
        ]
        assert job.docstring == "JCL job JOBA. Steps: STEP01 (PGM=PROGA), STEP02 (PROC=PROCA), STEP03 (PROC=PROCB), STEP04 (PGM=IKJEFT01), STEP05 (PGM=SORT), STEP06 (PGM=PROGC)."

    def test_steps_are_methods(self, manager):
        methods = manager.extract_methods(JOB, file_path="joba.jcl")
        assert names(methods) == ["STEP01", "STEP02", "STEP03", "STEP04", "STEP05", "STEP06"]
        first = methods[0]
        assert first.class_name == "JOBA"
        assert (first.line_start, first.line_end) == (5, 13)
        assert first.docstring == "Runs program PROGA."
        assert methods[1].docstring == "Runs procedure PROCA."
        assert (methods[-1].line_start, methods[-1].line_end) == (29, 29)

    def test_datasets_are_step_parameters(self, manager):
        first = manager.extract_methods(JOB, file_path="joba.jcl")[0]
        assert first.parameters == [
            {"name": "STEPLIB", "annotation": "LEVEL.ONE.LOADLIB", "disp": "SHR"},
            {"name": "FILEA", "annotation": "LEVEL.ONE.FILEA.KSDS", "disp": "SHR"},
            {"name": "FILEB", "annotation": "LEVEL.ONE.FILEB", "disp": "NEW"},
        ]

    def test_concatenated_dataset_keeps_the_dd_name(self, manager):
        sort = manager.extract_methods(JOB, file_path="joba.jcl")[4]
        assert [(p["name"], p["annotation"]) for p in sort.parameters] == [
            ("SORTIN", "LEVEL.ONE.FILEA.KSDS"),
            ("SORTIN", "LEVEL.ONE.FILEC"),
        ]

    def test_programs_and_procedures_are_calls(self, manager):
        calls = manager.extract_calls(JOB, file_path="joba.jcl")
        assert [(c.caller_name, c.callee_name) for c in calls] == [
            ("STEP01", "PROGA"),
            ("STEP02", "PROCA"),
            ("STEP03", "PROCB"),
            ("STEP04", "IKJEFT01"),
            ("STEP04", "PROGB"),
            ("STEP05", "SORT"),
            ("STEP06", "PROGC"),
        ]
        assert calls[0].caller_class == "JOBA"
        assert calls[0].callee_qualifier is None
        assert calls[0].line == 5
        assert calls[4].line == 20

    def test_region_controller_runs_the_program_in_its_parm(self, manager):
        source = "//JOBE JOB CLASS=A\n//STEP01 EXEC PGM=DFSRRC00,\n//       PARM='BMP,PROGA,PSBA'\n"
        calls = manager.extract_calls(source, file_path="jobe.jcl")
        assert [(c.caller_name, c.callee_name) for c in calls] == [("STEP01", "DFSRRC00"), ("STEP01", "PROGA")]

    def test_comments_are_not_statements(self, manager):
        calls = manager.extract_calls(JOB, file_path="joba.jcl")
        assert "IGNORED" not in [c.callee_name for c in calls]

    def test_job_has_no_imports(self, manager):
        assert manager.extract_imports(JOB, file_path="joba.jcl") == []


class TestProcedure:
    def test_procedure_is_a_type(self, manager):
        types = manager.extract_types(PROCEDURE, file_path="proca.prc")
        assert names(types) == ["PROCA"]
        assert types[0].kind == "procedure"
        assert (types[0].line_start, types[0].line_end) == (1, 6)
        assert types[0].decorators == ["dataset:&&WORK", "dataset:LEVEL.TWO"]

    def test_procedure_has_an_entry_point_that_runs_its_steps(self, manager):
        result = manager.extract_all(PROCEDURE, file_path="proca.prc")
        assert [(m.name, m.class_name) for m in result["methods"]] == [("PROCA", None), ("PRC001", "PROCA")]
        assert [(c.caller_name, c.callee_name) for c in result["calls"]] == [("PROCA", "PRC001"), ("PRC001", "PROGD")]

    def test_member_without_header_is_named_after_the_file(self, manager):
        result = manager.extract_all(MEMBER_WITHOUT_HEADER, file_path="lib/procc.proc")
        assert names(result["types"]) == ["PROCC"]
        assert result["types"][0].kind == "procedure"
        assert [(m.name, m.class_name) for m in result["methods"]] == [("PROCC", None), ("STEP01", "PROCC")]

    def test_in_stream_procedure_is_its_own_type(self, manager):
        source = "//JOBX JOB CLASS=A\n" + PROCEDURE + "//STEP01 EXEC PROCA\n"
        result = manager.extract_all(source, file_path="jobx.jcl")
        assert [(t.name, t.kind) for t in result["types"]] == [("JOBX", "job"), ("PROCA", "procedure")]
        assert [(m.name, m.class_name) for m in result["methods"]] == [("PROCA", None), ("PRC001", "PROCA"), ("STEP01", "JOBX")]


class TestRobustness:
    @pytest.mark.parametrize("source", ["", "\n", "no jcl here", "//", "// EXEC", "//A DD", "//A EXEC PGM="])
    def test_odd_input_gives_empty_or_partial_results(self, manager, source):
        result = manager.extract_all(source, file_path="x.jcl")
        assert set(result) == {"types", "methods", "imports", "calls"}

    def test_repeated_step_names_stay_distinct(self, manager):
        source = "//JOBC JOB CLASS=A\n//STEP01 EXEC PGM=PROGA\n//STEP01 EXEC PGM=PROGB\n"
        methods = manager.extract_methods(source, file_path="jobc.jcl")
        assert names(methods) == ["STEP01", "STEP01-2"]

    def test_unresolved_symbolic_program_is_not_a_call(self, manager):
        source = "//JOBD JOB CLASS=A\n//STEP01 EXEC PGM=&PGMNAME\n"
        result = manager.extract_all(source, file_path="jobd.jcl")
        assert names(result["methods"]) == ["STEP01"]
        assert result["calls"] == []


class TestReviewFixes:
    def test_in_stream_data_after_a_continued_dd_is_read(self, manager):
        """A DD * whose statement continues on the next line still owns the data records that follow."""
        source = "//JOBA JOB CLASS=A\n//STEP01 EXEC PGM=IKJEFT01\n//SYSTSIN DD *,\n//         DLM=ZZ\n  RUN PROGRAM(PROGB) PLAN(PLANA)\n/*\n"

        calls = manager.extract_all(source, file_path="joba.jcl")["calls"]

        assert "PROGB" in {c.callee_name for c in calls}

    def test_a_generation_is_dropped_from_the_dataset_name(self, manager):
        source = "//JOBA JOB CLASS=A\n//STEP01 EXEC PGM=PROGA\n//FILEA DD DSN=LEVEL.ONE.FILEA.G0001V00,DISP=SHR\n"

        assert manager.extract_methods(source, file_path="joba.jcl")[0].parameters == [{"name": "FILEA", "annotation": "LEVEL.ONE.FILEA", "disp": "SHR"}]
