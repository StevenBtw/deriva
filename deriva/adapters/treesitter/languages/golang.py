"""Go language extractor using tree-sitter.

Types are a declaration's type specs: a struct, an interface, an alias (``type ID = string``, kind type_alias) or a
defined type over another type (``type Handler func(...)``, ``type total int``, kind type); embedded fields and
embedded interfaces are a type's bases, without their type arguments (``Base[T]`` is Base), while a constraint's terms
(``int | float64``, ``~int``) are none. Functions have no class; a method's class is its receiver's type (pointer and
type arguments left out). An exported name (a capital first letter) is public, any other private; a type's or
function's doc comment is the line comments right above it, a comment that ends the line before is none. Imports are
paths with an optional alias; calls are the calls inside each function's body, also through an index or type
arguments (``handlers[0]()``, ``makeThing[int]()``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tree_sitter

from ..models import ExtractedCall, ExtractedImport, ExtractedMethod, ExtractedType, FilterConstants
from . import register_extractor
from .base import LanguageExtractor

# The standard library's packages that code imports most (import paths)
GO_STDLIB = {
    "bufio",
    "bytes",
    "context",
    "crypto",
    "crypto/rand",
    "crypto/sha256",
    "crypto/tls",
    "database/sql",
    "embed",
    "encoding/base64",
    "encoding/binary",
    "encoding/csv",
    "encoding/hex",
    "encoding/json",
    "encoding/xml",
    "errors",
    "flag",
    "fmt",
    "hash",
    "html/template",
    "io",
    "io/fs",
    "io/ioutil",
    "log",
    "log/slog",
    "math",
    "math/rand",
    "mime",
    "net",
    "net/http",
    "net/http/httptest",
    "net/url",
    "os",
    "os/exec",
    "os/signal",
    "path",
    "path/filepath",
    "reflect",
    "regexp",
    "runtime",
    "sort",
    "strconv",
    "strings",
    "sync",
    "sync/atomic",
    "syscall",
    "testing",
    "text/template",
    "time",
    "unicode",
    "unicode/utf8",
}

# Predeclared functions
GO_BUILTINS = {"append", "cap", "clear", "close", "complex", "copy", "delete", "imag", "len", "make", "max", "min", "new", "panic", "print", "println", "real", "recover"}

# Predeclared types
GO_BUILTIN_TYPES = {
    "any",
    "bool",
    "byte",
    "comparable",
    "complex64",
    "complex128",
    "error",
    "float32",
    "float64",
    "int",
    "int8",
    "int16",
    "int32",
    "int64",
    "rune",
    "string",
    "uint",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "uintptr",
}

_FUNCTIONS = {"function_declaration", "method_declaration"}


class GoExtractor(LanguageExtractor):
    """Extractor for Go source code."""

    @property
    def language_name(self) -> str:
        return "golang"

    def get_filter_constants(self) -> FilterConstants:
        return FilterConstants(stdlib_modules=set(GO_STDLIB), builtin_functions=set(GO_BUILTINS), builtin_types=set(GO_BUILTIN_TYPES))

    def get_language(self) -> Any:
        """Return the tree-sitter Go language."""
        import tree_sitter_go

        return tree_sitter_go.language()

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        types: list[ExtractedType] = []
        for declaration in self.find_children_by_type(tree.root_node, "type_declaration"):
            for spec in [c for c in declaration.children if c.type in ("type_spec", "type_alias")]:
                name_node = self.find_child_by_field(spec, "name")
                if name_node is None:
                    continue
                name = self.get_node_text(name_node, source)
                body = self.find_child_by_field(spec, "type")
                # A type alias (type ID = string) is another name for a type; any other spec defines a type of its own
                kind = "type_alias" if spec.type == "type_alias" else "type"
                if spec.type == "type_spec" and body is not None and body.type in ("struct_type", "interface_type"):
                    kind = "struct" if body.type == "struct_type" else "interface"
                # A grouped declaration (type ( ... )) has one spec per line: the spec is the type's extent
                single = len([c for c in declaration.children if c.type in ("type_spec", "type_alias")]) == 1
                extent = declaration if single else spec
                types.append(
                    ExtractedType(
                        name=name,
                        kind=kind,
                        line_start=self.get_line_start(extent),
                        line_end=self.get_line_end(extent),
                        docstring=self._doc_comment(declaration, source) if single else None,
                        bases=self._embedded(body, source) if body is not None else [],
                        visibility=_visibility(name),
                    )
                )
        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        methods: list[ExtractedMethod] = []
        for node in tree.root_node.children:
            if node.type not in _FUNCTIONS:
                continue
            name_node = self.find_child_by_field(node, "name")
            if name_node is None:
                continue
            name = self.get_node_text(name_node, source)
            result = self.find_child_by_field(node, "result")
            methods.append(
                ExtractedMethod(
                    name=name,
                    class_name=self._receiver_type(node, source),
                    line_start=self.get_line_start(node),
                    line_end=self.get_line_end(node),
                    docstring=self._doc_comment(node, source),
                    parameters=self._parameters(self.find_child_by_field(node, "parameters"), source),
                    return_annotation=self.get_node_text(result, source) if result is not None else None,
                    visibility=_visibility(name),
                )
            )
        return methods

    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        imports: list[ExtractedImport] = []
        for spec in self.walk_tree(tree.root_node, {"import_spec"}):
            path = self.find_child_by_field(spec, "path")
            if path is None:
                continue
            alias = self.find_child_by_field(spec, "name")
            imports.append(
                ExtractedImport(
                    module=self.get_node_text(path, source).strip('"`'),
                    names=[],
                    alias=self.get_node_text(alias, source) if alias is not None else None,
                    line=self.get_line_start(spec),
                )
            )
        return imports

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        calls: list[ExtractedCall] = []
        for node in tree.root_node.children:
            name_node = self.find_child_by_field(node, "name") if node.type in _FUNCTIONS else None
            body = self.find_child_by_field(node, "body") if node.type in _FUNCTIONS else None
            if name_node is None or body is None:
                continue
            caller, owner = self.get_node_text(name_node, source), self._receiver_type(node, source)
            for call in self.walk_tree(body, {"call_expression"}):
                function = self.find_child_by_field(call, "function")
                # A call through an index or with type arguments (handlers[0](), makeThing[int]()) calls its operand
                while function is not None and function.type in ("index_expression", "parenthesized_expression"):
                    function = self.find_child_by_field(function, "operand") or next(iter(function.named_children), None)
                if function is None:
                    continue
                if function.type == "identifier":
                    calls.append(ExtractedCall(caller, owner, self.get_node_text(function, source), None, self.get_line_start(call)))
                elif function.type == "selector_expression":
                    operand, field = self.find_child_by_field(function, "operand"), self.find_child_by_field(function, "field")
                    if field is not None:
                        qualifier = self.get_node_text(operand, source) if operand is not None else None
                        calls.append(ExtractedCall(caller, owner, self.get_node_text(field, source), qualifier, self.get_line_start(call), is_method_call=True))
        return calls

    # =========================================================================
    # Helpers
    # =========================================================================

    def _receiver_type(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """A method's receiver type without pointer and type arguments (``(c *Cart)``, ``(s store[T])``); None for a function."""
        receiver = self.find_child_by_field(node, "receiver") if node.type == "method_declaration" else None
        if receiver is None:
            return None
        for declaration in self.find_children_by_type(receiver, "parameter_declaration"):
            kind = self.find_child_by_field(declaration, "type")
            while kind is not None and kind.type in ("pointer_type", "generic_type", "parenthesized_type"):
                kind = self.find_child_by_field(kind, "type") or next((c for c in kind.named_children), None)
            if kind is not None:
                return self.get_node_text(kind, source)
        return None

    def _embedded(self, body: tree_sitter.Node, source: bytes) -> list[str]:
        """The types a struct embeds (a field without a name) or an interface embeds (a type element), in order."""
        found: list[str] = []
        if body.type == "struct_type":
            fields = self.find_child_by_type(body, "field_declaration_list")
            for field in self.find_children_by_type(fields, "field_declaration") if fields is not None else []:
                kind = self.find_child_by_field(field, "type")
                if self.find_child_by_field(field, "name") is None and kind is not None:
                    found.append(self._base_name(kind, source))
        elif body.type == "interface_type":
            # An embedded interface is an element of one plain term; a union (int | float64) or an approximation (~int)
            # is a type constraint, no base
            for element in self.find_children_by_type(body, "type_elem"):
                terms = element.named_children
                if len(terms) == 1 and terms[0].type in ("type_identifier", "qualified_type", "generic_type"):
                    if (name := self._base_name(terms[0], source)) not in GO_BUILTIN_TYPES:
                        found.append(name)
        return found

    def _base_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """A type's name without pointer and type arguments (``*Other`` is Other, ``Base[T]`` is Base)."""
        if node.type == "generic_type":
            node = self.find_child_by_field(node, "type") or node.named_children[0]
        return self.get_node_text(node, source).lstrip("*")

    def _parameters(self, node: tree_sitter.Node | None, source: bytes) -> list[dict[str, Any]]:
        """Each parameter's name and type; a variadic one is named with "..." in front, an unnamed one by its type."""
        params: list[dict[str, Any]] = []
        for declaration in node.named_children if node is not None else []:
            if declaration.type not in ("parameter_declaration", "variadic_parameter_declaration"):
                continue
            kind = self.find_child_by_field(declaration, "type")
            annotation = self.get_node_text(kind, source) if kind is not None else None
            names = [self.get_node_text(c, source) for c in declaration.children if c.type == "identifier"]
            prefix = "..." if declaration.type == "variadic_parameter_declaration" else ""
            for name in names or [annotation or ""]:
                params.append({"name": f"{prefix}{name}", "annotation": annotation, "has_default": False})
        return params

    def _doc_comment(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """The line comments right above a declaration (no blank line between), without their markers."""
        lines: list[str] = []
        previous, line = node.prev_sibling, node.start_point[0]
        while previous is not None and previous.type == "comment" and previous.end_point[0] == line - 1:
            text = self.get_node_text(previous, source)
            # A comment that ends a line of code (func f() {} // ...) belongs to that code
            before = previous.prev_sibling
            if not text.startswith("//") or (before is not None and before.end_point[0] == previous.start_point[0]):
                break
            lines.insert(0, text[2:].strip())
            previous, line = previous.prev_sibling, previous.start_point[0]
        return "\n".join(lines) or None


def _visibility(name: str) -> str:
    """Exported (public) when the name starts with a capital letter."""
    return "public" if name[:1].isupper() else "private"


# Register this extractor
register_extractor("golang", GoExtractor)
