"""JCL structural extractor (jobs and procedures).

JCL is line-oriented: a statement is ``//name operation operands``, continued on
the next line when the operands end with a comma. The mapping:

- a JOB statement is a type of kind ``job``, a PROC statement (or a member with
  steps but no JOB or PROC statement, named after the file) a type of kind
  ``procedure``; the decorators list the datasets it names (``dataset:``)
- each EXEC statement is a method of its job or procedure (a step); the DD
  statements with a dataset name are its parameters (DD name, dataset, disposition)
- ``EXEC PGM=X`` and ``EXEC PROC=X`` (or ``EXEC X``) are calls from the step to
  that program or procedure; so is ``RUN PROGRAM(X)`` in the in-stream data of a
  step, and the application program a database region controller is told to run
  (second PARM value)
- a procedure has an entry point method named after it (no class) that calls its
  steps, so a call to the procedure resolves like a call to a top-level function

Symbolic parameters are replaced by the values of SET statements and PROC
defaults; a generation or member suffix is dropped from dataset names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import ExtractedCall, ExtractedMethod, ExtractedType, FilterConstants
from . import register_extractor
from .structural import ParsedSource, StructuralExtractor, member_name

# Utility programs supplied by the operating system, database and transaction monitor
JCL_SYSTEM_PROGRAMS = {
    "IEFBR14",
    "IDCAMS",
    "IEBGENER",
    "IEBCOPY",
    "IEBUPDTE",
    "IEBCOMPR",
    "IEBPTPCH",
    "IEHLIST",
    "IEHPROGM",
    "IEWL",
    "HEWL",
    "IGYCRCTL",
    "ASMA90",
    "SORT",
    "DFSORT",
    "ICEMAN",
    "ICETOOL",
    "ICEGENER",
    "IKJEFT01",
    "IKJEFT1A",
    "IKJEFT1B",
    "IRXJCL",
    "ADRDSSU",
    "BPXBATCH",
    "FTP",
    "SDSF",
    "DFSRRC00",
    "DFSUDMP0",
    "DFSURGL0",
    "DFSURGU0",
    "DSNUTILB",
    "DSNTEP2",
    "DSNTEP4",
    "DSNTIAD",
    "DSNTIAUL",
    "DFHCSDUP",
}

# Programs that run the application program named second in their PARM
JCL_REGION_CONTROLLERS = {"DFSRRC00"}

_NAME = re.compile(r"[A-Z0-9@#$][A-Z0-9@#$_-]*")
_SYMBOL = re.compile(r"(?<!&)&([A-Z0-9@#$]+)\.?")
_RUN_PROGRAM = re.compile(r"\bRUN\s+PROGRAM\s*\(\s*([A-Z0-9@#$]+)\s*\)", re.IGNORECASE)


@dataclass
class _Statement:
    name: str
    operation: str
    operands: str
    line: int
    line_end: int


@dataclass
class _Unit:
    """A job or a procedure with its steps."""

    name: str
    kind: str  # 'job' or 'procedure'
    line_start: int
    line_end: int
    steps: list[ExtractedMethod] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)  # 'PGM=X' or 'PROC=X' per step
    datasets: set[str] = field(default_factory=set)
    entry: ExtractedMethod | None = None


def _operand_field(text: str) -> str:
    """The operand field: up to the first blank outside quotes (a comment follows it)."""
    quoted = False
    for position, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            return text[:position]
    return text


def _split_operands(text: str) -> list[str]:
    """Split an operand field at its top-level commas."""
    parts: list[str] = []
    depth = 0
    quoted = False
    current = ""
    for char in text:
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and not quoted and depth <= 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part for part in parts if part]


def _statements(lines: list[str]) -> tuple[list[_Statement], dict[int, str]]:
    """The JCL statements (continuations joined) and the in-stream data lines by line number."""
    statements: list[_Statement] = []
    data: dict[int, str] = {}
    in_stream = False
    continued = False
    for number, raw in enumerate(lines, start=1):
        line = raw[:71].rstrip()
        if not line.startswith("//"):
            if in_stream and not line.startswith("/*"):
                data[number] = line
            else:
                in_stream = False
            continue
        if line.startswith("//*"):
            continue
        rest = line[2:]
        if continued and statements and rest[:1] in ("", " "):
            # A continuation belongs to its statement: the in-stream data of a continued DD * follows it
            operands = _operand_field(rest.lstrip())
            statements[-1].operands += operands
            statements[-1].line_end = number
            continued = operands.endswith(",")
            continue
        in_stream = False
        name, _, tail = rest.partition(" ") if rest[:1] not in ("", " ") else ("", "", rest)
        tail = tail.lstrip()
        operation, _, operand_text = tail.partition(" ")
        operands = _operand_field(operand_text.lstrip())
        if not operation:
            continued = False
            continue
        statement = _Statement(name.upper(), operation.upper(), operands, number, number)
        statements.append(statement)
        continued = operands.endswith(",")
        if statement.operation == "DD":
            first = _split_operands(operands)[:1]
            in_stream = bool(first) and first[0].upper() in ("*", "DATA")
    return statements, data


class _Reader:
    """Builds jobs, procedures and steps from the statements of one member."""

    def __init__(self, source: str, file_path: str | None) -> None:
        self.lines = source.splitlines()
        self.statements, self.data = _statements(self.lines)
        self.member = member_name(file_path)
        self.units: list[_Unit] = []
        self.job: _Unit | None = None
        self.procedure: _Unit | None = None
        self.step: ExtractedMethod | None = None
        self.dd_name = ""
        self.symbols: dict[str, str] = {}
        self.calls: list[ExtractedCall] = []
        self.last_line = max((s.line_end for s in self.statements), default=0)
        self.last_line = max([self.last_line, *self.data])

    def _substitute(self, text: str) -> str:
        return _SYMBOL.sub(lambda match: self.symbols.get(match.group(1), match.group(0)), text.upper())

    def _keywords(self, operands: str) -> tuple[list[str], dict[str, str]]:
        """Positional and keyword operands of a statement."""
        positional: list[str] = []
        keywords: dict[str, str] = {}
        for part in _split_operands(operands):
            key, equals, value = part.partition("=")
            if equals and _NAME.fullmatch(key.upper()):
                keywords[key.upper()] = value
            else:
                positional.append(part)
        return positional, keywords

    @property
    def unit(self) -> _Unit | None:
        return self.procedure or self.job

    def read(self) -> None:
        for statement in self.statements:
            handler = getattr(self, f"_on_{statement.operation.lower()}", None)
            if handler:
                handler(statement)
        self._end_step(self.last_line)
        for unit in self.units:
            if unit.line_end == 0:
                unit.line_end = max(unit.line_start, self.last_line)
        for number, line in self.data.items():
            self._in_stream(number, line)
        self.calls.sort(key=lambda call: call.line)

    # --------------------------------------------------------------- statements

    def _on_job(self, statement: _Statement) -> None:
        self._end_step(statement.line - 1)
        if self.job:
            self.job.line_end = statement.line - 1
        self.procedure = None
        self.job = self._new_unit(statement.name or self.member or "JOB", "job", statement.line)

    def _on_proc(self, statement: _Statement) -> None:
        self._end_step(statement.line - 1)
        self.procedure = self._new_unit(statement.name or self.member or "PROC", "procedure", statement.line, entry_end=statement.line_end)
        _, defaults = self._keywords(statement.operands)
        for key, value in defaults.items():
            self.symbols.setdefault(key, value.strip("'"))

    def _on_pend(self, statement: _Statement) -> None:
        self._end_step(statement.line - 1)
        if self.procedure:
            self.procedure.line_end = statement.line
        self.procedure = None

    def _on_set(self, statement: _Statement) -> None:
        _, values = self._keywords(statement.operands)
        for key, value in values.items():
            self.symbols[key] = self._substitute(value.strip("'"))

    def _on_exec(self, statement: _Statement) -> None:
        self._end_step(statement.line - 1)
        if self.unit is None:
            # A member with steps but no JOB or PROC statement is a procedure named after the member
            self.procedure = self._new_unit(self.member or "PROC", "procedure", statement.line, entry_end=statement.line)
        unit = self.unit
        assert unit is not None
        positional, keywords = self._keywords(statement.operands)
        program = self._substitute(keywords.get("PGM", ""))
        procedure = self._substitute(keywords.get("PROC", "") or (positional[0] if positional else ""))
        ordinal = len(unit.steps) + 1
        name = statement.name or f"STEP{ordinal:02d}"
        taken = {step.name for step in unit.steps}
        if name in taken:
            name = next(f"{name}-{n}" for n in range(2, len(taken) + 3) if f"{name}-{n}" not in taken)
        target = program or procedure
        kind = "program" if program else "procedure"
        self.step = ExtractedMethod(
            name=name,
            class_name=unit.name,
            line_start=statement.line,
            line_end=statement.line_end,
            docstring=f"Runs {kind} {target}." if target else None,
        )
        unit.steps.append(self.step)
        unit.targets.append(f"{'PGM' if program else 'PROC'}={target}")
        if unit.entry:
            self.calls.append(self._call(unit.entry, name, statement.line))
        if _NAME.fullmatch(target):
            self.calls.append(self._call(self.step, target, statement.line))
        if program in JCL_REGION_CONTROLLERS:
            values = self._substitute(keywords.get("PARM", "")).strip("'()").split(",")
            if len(values) > 1 and _NAME.fullmatch(values[1]):
                self.calls.append(self._call(self.step, values[1], statement.line))
        self.dd_name = ""

    def _on_dd(self, statement: _Statement) -> None:
        if statement.name:
            self.dd_name = statement.name
        if self.step is None or self.unit is None:
            return
        _, keywords = self._keywords(statement.operands)
        dataset = self._substitute(keywords.get("DSN", "") or keywords.get("DSNAME", "")).strip("'")
        dataset = re.sub(r"\.G\d{4}V\d{2}$", "", dataset.split("(", 1)[0], flags=re.IGNORECASE)
        if not dataset or dataset == "NULLFILE" or dataset.startswith("*"):
            return
        disposition = keywords.get("DISP", "").upper().strip("()").split(",")[0] or None
        self.step.parameters.append({"name": self.dd_name, "annotation": dataset, "disp": disposition})
        self.unit.datasets.add(dataset)

    def _in_stream(self, number: int, line: str) -> None:
        """A program run through the terminal monitor is named in the in-stream data of its step."""
        match = _RUN_PROGRAM.search(line)
        if not match:
            return
        for unit in self.units:
            for step in unit.steps:
                if step.line_start <= number <= step.line_end:
                    self.calls.append(self._call(step, match.group(1).upper(), number))
                    return

    # ------------------------------------------------------------------ helpers

    def _new_unit(self, name: str, kind: str, line: int, entry_end: int | None = None) -> _Unit:
        unit = _Unit(name=name, kind=kind, line_start=line, line_end=0)
        if entry_end is not None:
            unit.entry = ExtractedMethod(
                name=name,
                class_name=None,
                line_start=line,
                line_end=entry_end,
                docstring=f"Entry point of procedure {name}.",
            )
        self.units.append(unit)
        return unit

    def _end_step(self, line: int) -> None:
        if self.step:
            self.step.line_end = max(self.step.line_start, line)
            self.step = None

    @staticmethod
    def _call(caller: ExtractedMethod, callee: str, line: int) -> ExtractedCall:
        return ExtractedCall(caller_name=caller.name, caller_class=caller.class_name, callee_name=callee, callee_qualifier=None, line=line)

    def result(self) -> ParsedSource:
        parsed = ParsedSource(calls=self.calls)
        for unit in self.units:
            label = "JCL job" if unit.kind == "job" else "JCL procedure"
            docstring = f"{label} {unit.name}."
            if unit.steps:
                steps = ", ".join(f"{step.name} ({target})" for step, target in zip(unit.steps, unit.targets, strict=True))
                docstring += f" Steps: {steps}."
            parsed.types.append(
                ExtractedType(
                    name=unit.name,
                    kind=unit.kind,
                    line_start=unit.line_start,
                    line_end=unit.line_end,
                    docstring=docstring,
                    decorators=[f"dataset:{name}" for name in sorted(unit.datasets)],
                )
            )
            if unit.entry:
                parsed.methods.append(unit.entry)
            parsed.methods.extend(unit.steps)
        parsed.methods.sort(key=lambda method: method.line_start)
        return parsed


class JclExtractor(StructuralExtractor):
    """JCL extractor for jobs and procedures."""

    @property
    def language_name(self) -> str:
        return "jcl"

    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        reader = _Reader(source, file_path)
        reader.read()
        return reader.result()

    def get_filter_constants(self) -> FilterConstants:
        """System utility programs, so they are not taken for the repository's own."""
        return FilterConstants(builtin_functions=JCL_SYSTEM_PROGRAMS)


register_extractor("jcl", JclExtractor)

__all__ = ["JCL_REGION_CONTROLLERS", "JCL_SYSTEM_PROGRAMS", "JclExtractor"]
