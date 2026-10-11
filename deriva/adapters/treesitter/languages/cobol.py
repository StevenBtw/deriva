"""COBOL structural extractor (programs and copybooks, fixed reference format).

No COBOL grammar ships with the tree-sitter packages, and the structure needed
here is shallow, so the source is tokenised and scanned once:

- a program (PROGRAM-ID) is a type of kind ``program``; its decorators say whether
  it is ``online`` (EXEC CICS) or ``batch``, which interfaces it uses (``cics``,
  ``sql``, ``mq``, ``ims``) and which resources it names (``file:``, ``table:``,
  ``segment:``, ``psb:``, ``map:``, ``mapset:``, ``queue:``, ``transaction:``)
- the program's entry point is a method named after the program (no class), so a
  call to the program resolves like a call to a top-level function; sections and
  paragraphs are methods of the program; an entry point or section without
  statements of its own calls the section or paragraph it falls through to
- COPY and EXEC SQL INCLUDE are imports
- CALL, EXEC CICS LINK and EXEC CICS XCTL are calls to the named program;
  PERFORM is a call to the paragraph or section
- a copybook (no PROGRAM-ID) gives a type of kind ``record`` per level-01 entry,
  with its fields listed in the docstring

Operands given as data names are resolved through the VALUE clauses and the
literal MOVE statements of the same source; operands that only get a value at
run time are left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NamedTuple

from ..models import ExtractedCall, ExtractedImport, ExtractedMethod, ExtractedType, FilterConstants
from . import register_extractor
from .structural import ParsedSource, StructuralExtractor, member_name

# Copybooks supplied by the platform (transaction monitor, database, message queue)
COBOL_SYSTEM_COPYBOOKS = {
    "DFHAID",
    "DFHBMSCA",
    "DFHEIBLK",
    "SQLCA",
    "SQLDA",
    "CMQV",
    "CMQODV",
    "CMQMDV",
    "CMQGMOV",
    "CMQPMOV",
    "CMQTML",
    "DLIUIB",
}

# Message queue interface entry points
COBOL_MQ_PROGRAMS = {
    "MQCONN",
    "MQCONNX",
    "MQDISC",
    "MQOPEN",
    "MQCLOSE",
    "MQGET",
    "MQPUT",
    "MQPUT1",
    "MQINQ",
    "MQSET",
    "MQBEGIN",
    "MQCMIT",
    "MQBACK",
    "MQSUB",
    "MQSUBRQ",
    "MQCB",
    "MQCTL",
    "MQSTAT",
}

# Hierarchical database call interface entry points
COBOL_IMS_PROGRAMS = {"CBLTDLI", "AIBTDLI", "CEETDLI"}

# Programs supplied by the platform (language environment, database, queue and database interfaces)
COBOL_SYSTEM_PROGRAMS = (
    {
        "CEE3AND",
        "CEE3DMP",
        "CEEDATE",
        "CEEDATM",
        "CEEDAYS",
        "CEEGMT",
        "CEEHDLR",
        "CEELOCT",
        "CEEMSG",
        "CEESECS",
        "ILBOABN0",
        "DSNALI",
        "DSNELI",
        "DSNHLI",
        "DSNRLI",
        "DSNTIAR",
    }
    | COBOL_MQ_PROGRAMS
    | COBOL_IMS_PROGRAMS
)

# Reserved words that can stand alone before a period in Area A, so are never paragraph names
_NOT_PARAGRAPHS = {
    "EXIT",
    "GOBACK",
    "CONTINUE",
    "DECLARATIVES",
    "ELSE",
    "EJECT",
    "SKIP1",
    "SKIP2",
    "SKIP3",
    "FILE-CONTROL",
    "I-O-CONTROL",
    "SPECIAL-NAMES",
    "SOURCE-COMPUTER",
    "OBJECT-COMPUTER",
    "REPOSITORY",
    "PROGRAM-ID",
    "AUTHOR",
    "INSTALLATION",
    "DATE-WRITTEN",
    "DATE-COMPILED",
    "SECURITY",
}
_DATA_SECTIONS = {
    "CONFIGURATION",
    "INPUT-OUTPUT",
    "FILE",
    "WORKING-STORAGE",
    "LOCAL-STORAGE",
    "LINKAGE",
    "SCREEN",
    "REPORT",
    "COMMUNICATION",
}
_DIVISIONS = {"IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE"}
_USAGES = {
    "BINARY",
    "PACKED-DECIMAL",
    "DISPLAY-1",
    "NATIONAL",
    "POINTER",
    "INDEX",
    "COMP",
    "COMP-1",
    "COMP-2",
    "COMP-3",
    "COMP-4",
    "COMP-5",
    "COMPUTATIONAL",
    "COMPUTATIONAL-1",
    "COMPUTATIONAL-2",
    "COMPUTATIONAL-3",
    "COMPUTATIONAL-4",
    "COMPUTATIONAL-5",
}
_DATA_CLAUSES = _USAGES | {"PIC", "PICTURE", "VALUE", "VALUES", "REDEFINES", "OCCURS", "USAGE", "EXTERNAL", "GLOBAL", "SYNC", "JUSTIFIED", "BLANK", "SIGN"}
_USING_NOISE = {"BY", "REFERENCE", "VALUE", "CONTENT", "OPTIONAL"}

# Transaction monitor options whose operand names a resource, and the decorator category it gets
_CICS_RESOURCES = {
    "FILE": "file",
    "DATASET": "file",
    "MAP": "map",
    "MAPSET": "mapset",
    "QUEUE": "queue",
    "TRANSID": "transaction",
}
_DLI_RESOURCES = {"SEGMENT": "segment", "PSB": "psb"}
_INTERFACES = ("cics", "sql", "mq", "ims")
_RESOURCE_LABELS = {
    "file": "Files",
    "table": "Tables",
    "segment": "Segments",
    "psb": "PSBs",
    "map": "Maps",
    "mapset": "Mapsets",
    "queue": "Queues",
    "transaction": "Transactions",
}

_AREA_A = range(7, 11)  # columns 8 to 11, zero-based
_CODE_END = 72
_TOKEN = re.compile(r"""'(?:[^']|'')*'?|"(?:[^"]|"")*"?|[()]|[^\s'"()]+""")
_SQL_NOT_TABLES = {"OF", "SET", "SELECT", "TABLE", "FINAL"}
_LEVEL = re.compile(r"\d{1,2}")
_NAME = re.compile(r"[A-Za-z0-9@#$][A-Za-z0-9@#$_-]{0,29}")
_TABLE = re.compile(r"[A-Za-z@#$][A-Za-z0-9@#$_.]*")
_WORD = re.compile(r"[A-Z0-9][A-Z0-9-]*")


class _Token(NamedTuple):
    text: str  # upper case, except literals
    line: int  # 1-indexed
    col: int  # zero-based column in the source line
    end: int
    literal: bool


@dataclass
class _Reference:
    """An operand that names a program or resource, to resolve once the whole source is read."""

    category: str  # 'call' or a resource category
    token: _Token
    caller: ExtractedMethod | None
    as_written: bool = False  # the word itself is the name (not a data name)


@dataclass
class _Record:
    name: str
    line_start: int
    line_end: int
    picture: str = ""
    fields: list[str] = field(default_factory=list)


@dataclass
class _Unit:
    """A program, or the copybook text outside any program."""

    name: str | None
    line_start: int
    line_end: int = 0
    methods: list[ExtractedMethod] = field(default_factory=list)
    constants: dict[str, str] = field(default_factory=dict)
    moves: dict[str, list[_Token]] = field(default_factory=dict)
    references: list[_Reference] = field(default_factory=list)
    performs: list[tuple[_Token, ExtractedMethod]] = field(default_factory=list)
    interfaces: set[str] = field(default_factory=set)
    tables: set[str] = field(default_factory=set)
    records: list[_Record] = field(default_factory=list)
    entry: ExtractedMethod | None = None
    section: ExtractedMethod | None = None
    paragraph: ExtractedMethod | None = None

    @property
    def caller(self) -> ExtractedMethod | None:
        return self.paragraph or self.section or self.entry


def _tokenize(source: str) -> list[_Token]:
    """Tokens of the code area (columns 8 to 72) of every non-comment line."""
    tokens: list[_Token] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.expandtabs(8)
        if len(line) <= 7 or line[6] in "*/dD":
            continue
        for match in _TOKEN.finditer(line[:_CODE_END], 7):
            text = match.group()
            if text.startswith("*>"):
                break
            if text[0] in "'\"":
                tokens.append(_Token(text, number, match.start(), match.end(), True))
                continue
            # A comma or semicolon before a space is a separator; inside a word it belongs to it
            text = text.upper().rstrip(",;")
            period = text.endswith(".")
            word = text.rstrip(".,;") if period else text
            if word:
                tokens.append(_Token(word, number, match.start(), match.start() + len(word), False))
            if period:
                tokens.append(_Token(".", number, match.end() - 1, match.end(), False))
    return tokens


def _literal_value(text: str) -> str:
    """The text of a literal token without its quotes and padding."""
    quote = text[0]
    body = text[1:-1] if len(text) > 1 and text.endswith(quote) else text[1:]
    return body.replace(quote * 2, quote).strip()


class _Scanner:
    """One pass over the tokens of a source file."""

    def __init__(self, source: str, file_path: str | None) -> None:
        self.tokens = _tokenize(source)
        self.member = member_name(file_path)
        self.units: list[_Unit] = []
        self.unit = _Unit(name=None, line_start=1)  # copybook text, until a PROGRAM-ID is seen
        self.units.append(self.unit)
        self.imports: list[ExtractedImport] = []
        self.in_procedure: bool | None = None  # None: no division seen (copybook)
        self.division_line: int | None = None  # line of an IDENTIFICATION DIVISION not yet claimed
        self.fragment: _Record | None = None
        self.body_start = 0  # index of the first token after the header of the open method
        self.last_line = self.tokens[-1].line if self.tokens else 0

    # ------------------------------------------------------------------ helpers

    def _text(self, index: int) -> str:
        return self.tokens[index].text if 0 <= index < len(self.tokens) else ""

    def _sentence_end(self, index: int) -> int:
        """Index of the period that ends the sentence at index (or the last token)."""
        while index < len(self.tokens) - 1 and self.tokens[index].text != ".":
            index += 1
        return index

    # --------------------------------------------------------------------- scan

    def scan(self) -> None:
        index = 0
        while index < len(self.tokens):
            token = self.tokens[index]
            if token.literal:
                index += 1
                continue
            index = self._dispatch(index, token, sentence_start=index == 0 or self._text(index - 1) == ".")
        self._close(self.last_line)

    def _dispatch(self, index: int, token: _Token, sentence_start: bool) -> int:
        """Handle the token at index; returns the index of the next token to read."""
        text = token.text
        nxt = self._text(index + 1)
        if text == "PROGRAM-ID":
            return self._program_id(index)
        if text in _DIVISIONS and nxt == "DIVISION":
            return self._division(index)
        if text == "END" and nxt == "PROGRAM":
            self._close(token.line)
            self.unit = _Unit(name=None, line_start=token.line + 1)
            self.units.append(self.unit)
            self.in_procedure = None
            return self._sentence_end(index) + 1
        if text == "COPY":
            return self._copy(index)
        if text == "EXEC":
            return self._exec(index)
        if text in _DATA_SECTIONS and nxt == "SECTION":
            self.in_procedure = False
            return index + 2
        if self.in_procedure is not True:
            if sentence_start and _LEVEL.fullmatch(text):
                return self._data_entry(index)
            if text == "SELECT":
                return self._select(index)
        if self.in_procedure is not False:
            if token.col in _AREA_A and _WORD.fullmatch(text) and text not in _NOT_PARAGRAPHS and not text.startswith("END-"):
                if nxt in (".", "SECTION"):
                    self._start_method(index, section=nxt == "SECTION")
                    return index + 2
            if text == "CALL":
                target = self.tokens[index + 1] if index + 1 < len(self.tokens) else None
                if target and target.text not in (".", "(", ")"):
                    self.unit.references.append(_Reference("call", target, self.unit.caller))
                return index + 2
            if text == "PERFORM":
                caller = self.unit.caller
                if caller and index + 1 < len(self.tokens):
                    self.unit.performs.append((self.tokens[index + 1], caller))
                return index + 1
            if text == "MOVE" and self._text(index + 2) == "TO" and index + 3 < len(self.tokens):
                self.unit.moves.setdefault(self._text(index + 3), []).append(self.tokens[index + 1])
                return index + 4
        return index + 1

    # ----------------------------------------------------------- program frame

    def _program_id(self, index: int) -> int:
        end = self._sentence_end(index + 2) if self._text(index + 1) == "." else self._sentence_end(index)
        names = [t for t in self.tokens[index + 1 : end + 1] if t.text != "."]
        if not names:
            return index + 1
        first = names[0]
        name = _literal_value(first.text) if first.literal else first.text
        line_start = self.division_line or self.tokens[index].line
        self.division_line = None
        self._close(line_start - 1)
        self.unit = _Unit(name=name, line_start=line_start)
        self.units.append(self.unit)
        self.in_procedure = False
        return end + 1

    def _division(self, index: int) -> int:
        token = self.tokens[index]
        if token.text in ("IDENTIFICATION", "ID"):
            self.division_line = token.line
            self.in_procedure = False
            return index + 2
        if token.text != "PROCEDURE":
            self.in_procedure = False
            return index + 2
        self.in_procedure = True
        end = self._sentence_end(index)
        unit = self.unit
        if unit.name:
            parameters = []
            using = False
            for item in self.tokens[index + 2 : end]:
                if item.text == "USING":
                    using = True
                elif item.text == "RETURNING":
                    using = False
                elif using and not item.literal and item.text not in _USING_NOISE:
                    parameters.append({"name": item.text})
            unit.entry = ExtractedMethod(
                name=unit.name,
                class_name=None,
                line_start=token.line,
                line_end=token.line,
                docstring=f"Entry point of program {unit.name}.",
                parameters=parameters,
            )
            unit.methods.append(unit.entry)
        self.body_start = end + 1
        return end + 1

    def _start_method(self, index: int, section: bool) -> None:
        token = self.tokens[index]
        if self.in_procedure is None:
            self.in_procedure = True
        unit = self.unit
        before = unit.caller
        if before and before is not unit.paragraph and all(t.text == "." for t in self.tokens[self.body_start : index]):
            # An entry point or section without statements of its own falls through to this method
            unit.references.append(_Reference("call", token, before, as_written=True))
        if unit.entry and len(unit.methods) == 1:
            unit.entry.line_end = max(unit.entry.line_start, token.line - 1)
        self._end_methods(token.line - 1, sections=section)
        method = ExtractedMethod(name=token.text, class_name=unit.name, line_start=token.line, line_end=token.line)
        unit.methods.append(method)
        if section:
            unit.section = method
        else:
            unit.paragraph = method
        self.body_start = index + 2

    def _end_methods(self, line: int, sections: bool) -> None:
        unit = self.unit
        if unit.paragraph:
            unit.paragraph.line_end = max(unit.paragraph.line_start, line)
            unit.paragraph = None
        if sections and unit.section:
            unit.section.line_end = max(unit.section.line_start, line)
            unit.section = None

    def _close(self, line: int) -> None:
        """End the current unit and its open methods at the given line."""
        unit = self.unit
        unit.line_end = max(unit.line_start, line)
        if unit.entry and len(unit.methods) == 1:
            unit.entry.line_end = max(unit.entry.line_start, line)
        self._end_methods(line, sections=True)
        if self.fragment:
            unit.records.append(self.fragment)
            self.fragment = None

    # ---------------------------------------------------------------- statements

    def _copy(self, index: int) -> int:
        if index + 1 >= len(self.tokens):
            return index + 1
        target = self.tokens[index + 1]
        name = _literal_value(target.text) if target.literal else target.text
        if _NAME.fullmatch(name):
            self.imports.append(ExtractedImport(module=name, names=[], line=self.tokens[index].line))
        return index + 2

    def _select(self, index: int) -> int:
        end = self._sentence_end(index)
        for position in range(index + 1, end):
            if self.tokens[position].text == "ASSIGN":
                target = position + 2 if self._text(position + 1) == "TO" else position + 1
                if target <= end and self._text(target) != ".":
                    token = self.tokens[target]
                    name = _literal_value(token.text) if token.literal else token.text
                    # An assignment name ends with the external file name (label-organisation-name)
                    ddname = name.rsplit("-", 1)[-1]
                    self.unit.references.append(_Reference("file", token._replace(text=ddname, literal=False), None, as_written=True))
                break
        return end + 1

    def _data_entry(self, index: int) -> int:
        end = self._sentence_end(index)
        level = int(self.tokens[index].text)
        body = self.tokens[index + 1 : end]
        name = "FILLER"
        if body and not body[0].literal and body[0].text not in _DATA_CLAUSES:
            name = body[0].text
        picture = ""
        usage = ""
        value: str | None = None
        for position, item in enumerate(body):
            if item.literal:
                continue
            if item.text in ("PIC", "PICTURE") and not picture:
                picture = self._picture(body, position + 1)
            elif item.text in ("VALUE", "VALUES") and value is None:
                following = [t for t in body[position + 1 : position + 3] if t.text not in ("IS", "ARE")]
                if following and following[0].literal:
                    value = _literal_value(following[0].text)
            elif item.text in _USAGES and not usage:
                usage = item.text
        if level not in (66, 88) and name != "FILLER" and value is not None:
            self.unit.constants.setdefault(name, value)
        if self.unit.name is None:
            self._record_entry(level, name, " ".join(part for part in (picture, usage) if part), self.tokens[index].line, self.tokens[end].line)
        return end + 1

    @staticmethod
    def _picture(body: list[_Token], position: int) -> str:
        """The picture string: the adjacent tokens after PIC [IS]."""
        if position < len(body) and body[position].text == "IS":
            position += 1
        parts: list[str] = []
        while position < len(body):
            item = body[position]
            if parts and (item.line != body[position - 1].line or item.col != body[position - 1].end):
                break
            parts.append(item.text)
            position += 1
        return "".join(parts)

    def _record_entry(self, level: int, name: str, layout: str, line_start: int, line_end: int) -> None:
        """Collect copybook data entries: a record per level 01, a member-named record for a fragment."""
        unit = self.unit
        if level == 1:
            if self.fragment:
                unit.records.append(self.fragment)
                self.fragment = None
            if name == "FILLER":
                name = self.member or name
            unit.records.append(_Record(name=name, line_start=line_start, line_end=line_end, picture=layout))
            return
        if level > 49:
            if unit.records and not self.fragment:
                unit.records[-1].line_end = line_end
            return
        if not unit.records and not self.fragment:
            self.fragment = _Record(name=self.member or name, line_start=line_start, line_end=line_end)
        record = self.fragment or unit.records[-1]
        record.line_end = line_end
        if name != "FILLER":
            record.fields.append(f"{name} {layout}".strip())

    def _exec(self, index: int) -> int:
        """An EXEC ... END-EXEC block of an embedded interface."""
        end = index + 1
        while end < len(self.tokens) and self.tokens[end].text != "END-EXEC":
            end += 1
        block = self.tokens[index + 1 : end]
        if not block:
            return end + 1
        kind = block[0].text
        unit = self.unit
        if kind == "CICS":
            unit.interfaces.add("cics")
            command = block[1].text if len(block) > 1 else ""
            for option, operand, _ in self._options(block[2:]):
                if option == "PROGRAM" and command in ("LINK", "XCTL"):
                    unit.references.append(_Reference("call", operand, unit.caller))
                elif option in _CICS_RESOURCES:
                    unit.references.append(_Reference(_CICS_RESOURCES[option], operand, unit.caller))
        elif kind == "DLI":
            unit.interfaces.add("ims")
            for option, operand, nested in self._options(block[2:]):
                if option in _DLI_RESOURCES:
                    # A name in single parentheses is the name itself; in double parentheses a data name
                    unit.references.append(_Reference(_DLI_RESOURCES[option], operand, unit.caller, as_written=not nested))
        elif kind == "SQL":
            unit.interfaces.add("sql")
            self._sql(block[1:])
        return end + 1

    @staticmethod
    def _options(block: list[_Token]) -> list[tuple[str, _Token, bool]]:
        """The (option, first operand token, operand is nested in double parentheses) triples of a command."""
        options: list[tuple[str, _Token, bool]] = []
        position = 0
        while position < len(block) - 2:
            if not block[position].literal and block[position + 1].text == "(" and not block[position + 1].literal:
                operand = position + 2
                nested = False
                if block[operand].text == "(" and not block[operand].literal and operand + 1 < len(block):
                    operand += 1
                    nested = True
                if block[operand].text != ")" or block[operand].literal:
                    options.append((block[position].text, block[operand], nested))
                depth = 1
                position += 2
                while position < len(block) and depth:
                    if not block[position].literal:
                        depth += {"(": 1, ")": -1}.get(block[position].text, 0)
                    position += 1
                continue
            position += 1
        return options

    def _sql(self, block: list[_Token]) -> None:
        """Tables named by an SQL statement, and INCLUDE as an import."""
        words = [t.text for t in block]
        if len(block) > 1 and words[0] == "INCLUDE" and _NAME.fullmatch(words[1]):
            self.imports.append(ExtractedImport(module=words[1], names=[], line=block[0].line))
            return
        if len(words) > 3 and words[0] == "DECLARE" and words[2] == "TABLE":
            self.unit.tables.add(words[1])
            return
        for position, word in enumerate(words[:-1]):
            follows_table = word in ("FROM", "JOIN", "UPDATE") or (word == "INTO" and position > 0 and words[position - 1] == "INSERT")
            if follows_table and not block[position + 1].literal and _TABLE.fullmatch(words[position + 1]) and words[position + 1] not in _SQL_NOT_TABLES:
                self.unit.tables.add(words[position + 1])

    # ------------------------------------------------------------------ results

    def _resolve(self, unit: _Unit, token: _Token, as_written: bool) -> list[str]:
        """The names an operand can stand for: itself, its VALUE, or the literals moved to it."""
        if token.literal:
            values = {_literal_value(token.text)}
        elif as_written:
            values = {token.text}
        else:
            values = set()
            if token.text in unit.constants:
                values.add(unit.constants[token.text])
            for moved in unit.moves.get(token.text, []):
                if moved.literal:
                    values.add(_literal_value(moved.text))
                elif moved.text in unit.constants:
                    values.add(unit.constants[moved.text])
        return sorted(value for value in values if _NAME.fullmatch(value))

    def result(self) -> ParsedSource:
        parsed = ParsedSource(imports=self.imports)
        for unit in self.units:
            resources: dict[str, set[str]] = {"table": set(unit.tables)}
            calls: list[ExtractedCall] = []
            for reference in unit.references:
                names = self._resolve(unit, reference.token, reference.as_written)
                if reference.category != "call":
                    resources.setdefault(reference.category, set()).update(names)
                    continue
                unit.interfaces.update("mq" for name in names if name in COBOL_MQ_PROGRAMS)
                unit.interfaces.update("ims" for name in names if name in COBOL_IMS_PROGRAMS)
                if reference.caller:
                    calls.extend(self._call(reference.caller, name, reference.token.line) for name in names)
            method_names = {method.name for method in unit.methods if method is not unit.entry}
            calls.extend(self._call(caller, token.text, token.line) for token, caller in unit.performs if not token.literal and token.text in method_names)
            calls.sort(key=lambda call: call.line)
            parsed.calls.extend(calls)
            parsed.methods.extend(unit.methods)
            if unit.name:
                parsed.types.append(self._program_type(unit, resources))
            else:
                parsed.types.extend(self._record_type(record) for record in unit.records)
        return parsed

    @staticmethod
    def _call(caller: ExtractedMethod, callee: str, line: int) -> ExtractedCall:
        return ExtractedCall(caller_name=caller.name, caller_class=caller.class_name, callee_name=callee, callee_qualifier=None, line=line)

    @staticmethod
    def _program_type(unit: _Unit, resources: dict[str, set[str]]) -> ExtractedType:
        online = "cics" in unit.interfaces
        decorators = ["online" if online else "batch"]
        decorators.extend(interface for interface in _INTERFACES if interface in unit.interfaces)
        sentences = [f"{'Online' if online else 'Batch'} COBOL program {unit.name}."]
        for category, label in _RESOURCE_LABELS.items():
            names = sorted(resources.get(category, ()))
            decorators.extend(f"{category}:{name}" for name in names)
            if names:
                sentences.append(f"{label}: {', '.join(names)}.")
        return ExtractedType(
            name=unit.name or "",
            kind="program",
            line_start=unit.line_start,
            line_end=unit.line_end,
            docstring=" ".join(sentences),
            decorators=decorators,
        )

    @staticmethod
    def _record_type(record: _Record) -> ExtractedType:
        docstring = f"Data record {record.name}."
        if record.fields:
            docstring += f" Fields: {', '.join(record.fields)}."
        elif record.picture:
            docstring = f"Data item {record.name} {record.picture}."
        return ExtractedType(name=record.name, kind="record", line_start=record.line_start, line_end=record.line_end, docstring=docstring)


class CobolExtractor(StructuralExtractor):
    """COBOL extractor for programs and copybooks."""

    @property
    def language_name(self) -> str:
        return "cobol"

    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        scanner = _Scanner(source, file_path)
        scanner.scan()
        return scanner.result()

    def get_filter_constants(self) -> FilterConstants:
        """System copybooks and programs, so they are not taken for the repository's own."""
        return FilterConstants(stdlib_modules=COBOL_SYSTEM_COPYBOOKS, builtin_functions=COBOL_SYSTEM_PROGRAMS)


register_extractor("cobol", CobolExtractor)

__all__ = [
    "COBOL_IMS_PROGRAMS",
    "COBOL_MQ_PROGRAMS",
    "COBOL_SYSTEM_COPYBOOKS",
    "COBOL_SYSTEM_PROGRAMS",
    "CobolExtractor",
]
