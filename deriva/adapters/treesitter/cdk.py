"""AWS CDK apps read statically (tree-sitter TypeScript, no ``cdk synth``): the CloudFormation resources they declare.

``cdk synth`` runs the app (Node, packages, network), so it is neither deterministic nor allowed in extraction.
Instead every ``new <construct>(scope, id, props)`` whose construct is in the versioned table becomes a resource
in the shape of a CloudFormation template (``Type``, ``Properties``), so the Deployment step reads CDK and
CloudFormation alike. A construct is named by its module and class (``aws-ecs.FargateService``), whatever the
import alias.

Values are evaluated only from literals: strings, numbers, template strings, local constants, and the entries of
a literal array that a ``for ... of`` loop walks, directly or through a method it calls with the loop variable
(one resource per entry). Names (the construct id and its ``*Name`` properties) let the step match a container to
its deployable unit; the listed properties (an engine) qualify a managed service.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import tree_sitter
import tree_sitter_typescript

_FUNCTIONS = ("method_definition", "function_declaration", "function_expression", "arrow_function")


@dataclass(frozen=True)
class CdkConstruct:
    """A construct of the table: its CloudFormation type, the environment a container runs in, fixed properties."""

    type: str
    environment: str | None = None
    properties: tuple[tuple[str, str], ...] = ()


_PARSER: tree_sitter.Parser | None = None


def _parser() -> tree_sitter.Parser:
    global _PARSER
    if _PARSER is None:
        _PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_typescript.language_typescript()))
    return _PARSER


def _module(source: str) -> str:
    """The CDK module of an import (``aws-cdk-lib/aws-ecs`` and ``@aws-cdk/aws-ecs`` -> ``aws-ecs``)."""
    return source.rstrip("/").rsplit("/", 1)[-1]


class _File:
    def __init__(self, text: str):
        self.source = text.encode("utf-8")
        self.root = _parser().parse(self.source).root_node
        self.namespaces: dict[str, str] = {}  # import alias -> module
        self.classes: dict[str, str] = {}  # imported class name (or alias) -> "module.Class"
        self.constants: dict[str, tree_sitter.Node] = {}  # top-level const name -> value
        for node in self.root.named_children:
            if node.type == "import_statement":
                self._import(node)
            elif node.type in ("lexical_declaration", "export_statement"):
                for declarator in self._declarators(node):
                    name, value = declarator.child_by_field_name("name"), declarator.child_by_field_name("value")
                    if name is not None and value is not None:
                        self.constants[self.text(name)] = value

    def text(self, node: tree_sitter.Node) -> str:
        return self.source[node.start_byte : node.end_byte].decode("utf-8")

    def _declarators(self, node: tree_sitter.Node) -> list[tree_sitter.Node]:
        declarations = [node] if node.type == "lexical_declaration" else [c for c in node.named_children if c.type == "lexical_declaration"]
        return [d for declaration in declarations for d in declaration.named_children if d.type == "variable_declarator"]

    def _import(self, node: tree_sitter.Node) -> None:
        source = node.child_by_field_name("source")
        if source is None:
            return
        module = _module(self.text(source).strip("'\""))
        for clause in (c for c in node.named_children if c.type == "import_clause"):
            for part in clause.named_children:
                if part.type == "namespace_import":
                    alias = next((c for c in part.named_children if c.type == "identifier"), None)
                    if alias is not None:
                        self.namespaces[self.text(alias)] = module
                elif part.type == "named_imports":
                    for spec in (s for s in part.named_children if s.type == "import_specifier"):
                        name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                        if name is not None:
                            self.classes[self.text(alias or name)] = f"{module}.{self.text(name)}"

    def construct(self, node: tree_sitter.Node) -> str | None:
        """The table key of a ``new`` expression's constructor (``module.Class``)."""
        ctor = node.child_by_field_name("constructor")
        if ctor is None:
            return None
        if ctor.type == "identifier":
            return self.classes.get(self.text(ctor))
        if ctor.type == "member_expression":
            obj, prop = ctor.child_by_field_name("object"), ctor.child_by_field_name("property")
            if obj is not None and prop is not None and obj.type == "identifier" and self.text(obj) in self.namespaces:
                return f"{self.namespaces[self.text(obj)]}.{self.text(prop)}"
        return None


def _ancestors(node: tree_sitter.Node) -> Iterable[tree_sitter.Node]:
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _function_of(node: tree_sitter.Node) -> tree_sitter.Node | None:
    return next((a for a in _ancestors(node) if a.type in _FUNCTIONS), None)


def _locals(f: _File, function: tree_sitter.Node | None, before: int) -> dict[str, tree_sitter.Node]:
    """The ``const`` values declared in a function before a position (its body's own statements and blocks)."""
    found: dict[str, tree_sitter.Node] = {}
    if function is None:
        return found
    stack = [function]
    while stack:
        node = stack.pop()
        for child in node.named_children:
            if child.type in _FUNCTIONS or child.start_byte >= before:
                continue
            if child.type == "lexical_declaration":
                for declarator in f._declarators(child):
                    name, value = declarator.child_by_field_name("name"), declarator.child_by_field_name("value")
                    if name is not None and value is not None:
                        found[f.text(name)] = value
            else:
                stack.append(child)
    return found


class _Scope:
    """Name bindings for evaluation: loop or parameter values (Python values) and constant nodes."""

    def __init__(self, f: _File, values: Mapping[str, Any], constants: Mapping[str, tree_sitter.Node]):
        self.f, self.values, self.constants = f, values, constants

    def evaluate(self, node: tree_sitter.Node | None, depth: int = 0) -> Any:
        if node is None or depth > 20:
            return None
        f = self.f
        kind = node.type
        if kind == "string":
            return "".join(f.text(c) for c in node.named_children if c.type == "string_fragment")
        if kind == "number":
            return f.text(node)
        if kind == "template_string":
            parts: list[str] = []
            for child in node.named_children:
                if child.type == "string_fragment":
                    parts.append(f.text(child))
                elif child.type == "template_substitution":
                    value = self.evaluate(child.named_children[0] if child.named_children else None, depth + 1)
                    if not isinstance(value, str):
                        return None
                    parts.append(value)
            return "".join(parts)
        if kind in ("identifier", "shorthand_property_identifier"):
            name = f.text(node)
            if name in self.values:
                return self.values[name]
            constant = self.constants.get(name) or f.constants.get(name)
            return self.evaluate(constant, depth + 1) if constant is not None and constant != node else None
        if kind == "member_expression":
            obj = self.evaluate(node.child_by_field_name("object"), depth + 1)
            prop = node.child_by_field_name("property")
            return obj.get(f.text(prop)) if isinstance(obj, dict) and prop is not None else None
        if kind == "object":
            return self.object(node, depth)
        if kind == "array":
            return [self.evaluate(c, depth + 1) for c in node.named_children]
        if kind in ("as_expression", "satisfies_expression", "parenthesized_expression", "non_null_expression"):
            return self.evaluate(node.named_children[0] if node.named_children else None, depth + 1)
        return None

    def object(self, node: tree_sitter.Node, depth: int = 0) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for child in node.named_children:
            if child.type == "pair":
                key, value = child.child_by_field_name("key"), child.child_by_field_name("value")
                if key is not None:
                    out[self.f.text(key).strip("'\"")] = self.evaluate(value, depth + 1)
            elif child.type == "shorthand_property_identifier":
                out[self.f.text(child)] = self.evaluate(child, depth + 1)
        return out

    def qualifier(self, node: tree_sitter.Node | None) -> str | None:
        """A property's qualifying value: a string, or the last name of an enum member or factory call
        (``rds.DatabaseInstanceEngine.postgres(...)`` -> ``postgres``)."""
        if node is None:
            return None
        value = self.evaluate(node)
        if isinstance(value, str):
            return value.lower()
        target = node.child_by_field_name("function") if node.type == "call_expression" else node
        if target is not None and target.type == "member_expression":
            prop = target.child_by_field_name("property")
            return self.f.text(prop).lower() if prop is not None else None
        return None


def _loop_bindings(f: _File, node: tree_sitter.Node, function: tree_sitter.Node | None) -> list[dict[str, Any]]:
    """One binding per entry of each literal array a ``for ... of`` loop around the node walks (within its function)."""
    bindings: list[dict[str, Any]] = [{}]
    for loop in _ancestors(node):
        if loop == function:
            break
        if loop.type != "for_in_statement" or not any(c.type == "of" for c in loop.children):
            continue
        left, right = loop.child_by_field_name("left"), loop.child_by_field_name("right")
        entries = _Scope(f, {}, _locals(f, function, loop.start_byte)).evaluate(right)
        if left is None or left.type != "identifier" or not isinstance(entries, list):
            continue
        bindings = [{**b, f.text(left): entry} for b in bindings for entry in entries]
    return bindings


def _parameter_bindings(f: _File, function: tree_sitter.Node | None) -> list[dict[str, Any]]:
    """For a method or function: the values its parameters take at its call sites in the file (each loop entry
    when it is called inside a loop over a literal array). None found: one binding without values."""
    if function is None or function.type not in ("method_definition", "function_declaration"):
        return [{}]
    name_node = function.child_by_field_name("name")
    params_node = function.child_by_field_name("parameters")
    if name_node is None or params_node is None:
        return [{}]
    name = f.text(name_node)
    params = [p.child_by_field_name("pattern") for p in params_node.named_children]
    names = [f.text(p) if p is not None and p.type == "identifier" else None for p in params]
    found: list[dict[str, Any]] = []
    stack = [f.root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type != "call_expression":
            continue
        callee = node.child_by_field_name("function")
        called = None
        if callee is not None and callee.type == "identifier":
            called = f.text(callee)
        elif callee is not None and callee.type == "member_expression" and (prop := callee.child_by_field_name("property")) is not None:
            called = f.text(prop)
        if called != name:
            continue
        args = node.child_by_field_name("arguments")
        caller = _function_of(node)
        for binding in _loop_bindings(f, node, caller):
            scope = _Scope(f, binding, _locals(f, caller, node.start_byte))
            values = {p: scope.evaluate(a) for p, a in zip(names, args.named_children if args else [], strict=False) if p}
            found.append({k: v for k, v in values.items() if v is not None})
    return sorted(found, key=repr) if found else [{}]


def cdk_resources(files: Mapping[str, str], constructs: Mapping[str, CdkConstruct], properties: tuple[str, ...]) -> dict[str, dict[str, dict[str, Any]]]:
    """The CloudFormation-like resources per file: logical id -> {Type, Properties, Names, Environment}.

    Args:
        files: Path -> text of the TypeScript files of the CDK apps
        constructs: The construct table (``module.Class`` -> CdkConstruct)
        properties: The CloudFormation property names read as qualifiers (``Engine``); a construct property
            ``engine`` is read as ``Engine``
    """
    wanted = {p[:1].lower() + p[1:]: p for p in properties}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for path, text in sorted(files.items()):
        f = _File(text)
        resources: dict[str, dict[str, Any]] = {}
        stack = [f.root]
        news: list[tree_sitter.Node] = []
        while stack:
            node = stack.pop()
            stack.extend(node.named_children)
            if node.type == "new_expression":
                news.append(node)
        for node in sorted(news, key=lambda n: n.start_byte):
            key = f.construct(node)
            construct = constructs.get(key) if key else None
            if construct is None:
                continue
            function = _function_of(node)
            args = node.child_by_field_name("arguments")
            arguments = args.named_children if args else []
            for outer in _parameter_bindings(f, function):
                for binding in _loop_bindings(f, node, function):
                    scope = _Scope(f, {**outer, **binding}, _locals(f, function, node.start_byte))
                    identifier = scope.evaluate(arguments[1]) if len(arguments) > 1 else None
                    logical = identifier if isinstance(identifier, str) and identifier else f.text(arguments[1]) if len(arguments) > 1 else key
                    props_node = arguments[2] if len(arguments) > 2 and arguments[2].type == "object" else None
                    props: dict[str, Any] = dict(construct.properties)
                    names = [identifier] if isinstance(identifier, str) and identifier else []
                    for child in props_node.named_children if props_node else []:
                        key_node = child.child_by_field_name("key") if child.type == "pair" else child if child.type == "shorthand_property_identifier" else None
                        if key_node is None:
                            continue
                        prop = f.text(key_node).strip("'\"")
                        value_node = child.child_by_field_name("value") if child.type == "pair" else child
                        if prop in wanted and wanted[prop] not in props and (qualifier := scope.qualifier(value_node)):
                            props[wanted[prop]] = qualifier
                        if prop.endswith("Name") and isinstance(name := scope.evaluate(value_node), str) and name and name not in names:
                            names.append(name)
                    resource: dict[str, Any] = {"Type": construct.type, "Properties": props, "Names": names}
                    if construct.environment:
                        resource["Environment"] = construct.environment
                    resources.setdefault(str(logical), resource)
        if resources:
            out[path] = resources
    return out
