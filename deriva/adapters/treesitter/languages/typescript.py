"""TypeScript language extractor using tree-sitter-typescript.

TypeScript keeps JavaScript's node types for classes, functions, imports and calls, so this extractor builds on the
JavaScript one and adds what TypeScript has of its own: abstract classes, interfaces, type aliases and enums as types,
``implements`` and interface ``extends`` as bases, decorators on classes and methods, typed and optional parameters
with their annotations, return types and accessibility, and exported arrow functions. A ``.tsx`` file is parsed with
the TSX grammar (JSX inside TypeScript), every other TypeScript file with the TypeScript grammar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tree_sitter

from ..models import ExtractedCall, ExtractedMethod, ExtractedType
from . import register_extractor
from .javascript import JavaScriptExtractor

# Declarations that are types of their own in TypeScript, with the kind they get
_TYPE_DECLARATIONS = {"interface_declaration": "interface", "type_alias_declaration": "type_alias", "enum_declaration": "enum"}
_CLASS_NODES = {"class_declaration", "class", "abstract_class_declaration"}
_PARAMETERS = ("required_parameter", "optional_parameter")


class TypeScriptExtractor(JavaScriptExtractor):
    """Extractor for TypeScript and TSX source code."""

    @property
    def language_name(self) -> str:
        return "typescript"

    def get_language(self) -> Any:
        """Return the tree-sitter TypeScript language."""
        import tree_sitter_typescript

        return tree_sitter_typescript.language_typescript()

    def grammar_for(self, file_path: str | None) -> str:
        """The grammar one file needs: tsx for a .tsx file (JSX inside TypeScript), typescript for any other."""
        return "tsx" if file_path and file_path.lower().endswith(".tsx") else "typescript"

    def get_language_for(self, file_path: str | None) -> Any:
        """The tree-sitter language of ``grammar_for(file_path)``."""
        import tree_sitter_typescript

        return tree_sitter_typescript.language_tsx() if self.grammar_for(file_path) == "tsx" else self.get_language()

    # =========================================================================
    # Types, methods and calls: the JavaScript ones plus TypeScript's own
    # =========================================================================

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        types = super().extract_types(tree, source)
        root = tree.root_node
        for node in self.walk_tree(root, set(_TYPE_DECLARATIONS)):
            name_node = self.find_child_by_field(node, "name")
            if name_node is None:
                continue
            types.append(
                ExtractedType(
                    name=self.get_node_text(name_node, source),
                    kind=_TYPE_DECLARATIONS[node.type],
                    line_start=self.get_line_start(node),
                    line_end=self.get_line_end(node),
                    bases=self._interface_bases(node, source),
                )
            )
        for declaration, name_node, arrow in self._exported_arrows(root):
            types.append(self._extract_arrow_function_as_type(declaration, name_node, arrow, source))
        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        methods = super().extract_methods(tree, source)
        for class_name, field, name_node, arrow in self._field_arrows(tree.root_node, source):
            methods.append(self._extract_arrow_method(field, name_node, arrow, source, class_name))
        for declaration, name_node, arrow in self._exported_arrows(tree.root_node):
            methods.append(self._extract_arrow_function(declaration, name_node, arrow, source))
        return methods

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        calls = super().extract_calls(tree, source)
        for class_name, _, name_node, arrow in self._field_arrows(tree.root_node, source):
            calls.extend(self._extract_calls_from_arrow(arrow, source, self.get_node_text(name_node, source), class_name))
        for _, name_node, arrow in self._exported_arrows(tree.root_node):
            calls.extend(self._extract_calls_from_arrow(arrow, source, self.get_node_text(name_node, source), None))
        return calls

    def _field_arrows(self, root: tree_sitter.Node, source: bytes) -> list[tuple[str, tree_sitter.Node, tree_sitter.Node, tree_sitter.Node]]:
        """(class, field, name, arrow function) of each class field that holds an arrow function (``handler = () => ...``):
        TypeScript calls the field public_field_definition, with a name field, where JavaScript has field_definition
        with a property field, which the JavaScript extractor reads."""
        found = []
        for class_node in self._classes(root):
            body = self.find_child_by_field(class_node, "body")
            for item in body.children if body is not None else []:
                if item.type != "public_field_definition":
                    continue
                value, name_node = self.find_child_by_field(item, "value"), self.find_child_by_field(item, "name")
                if value is not None and value.type == "arrow_function" and name_node is not None:
                    found.append((self._get_class_name(class_node, source), item, name_node, value))
        return found

    # =========================================================================
    # Classes, methods and functions
    # =========================================================================

    def _classes(self, root: tree_sitter.Node) -> list[tree_sitter.Node]:
        """Class declarations (abstract ones too) and class expressions."""
        return [node for node in self.walk_tree(root, _CLASS_NODES) if node.is_named]

    def _extract_class(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        extracted = super()._extract_class(node, source)
        extracted.bases = extracted.bases + self._implemented(node, source)
        extracted.decorators = self._decorators_of(node, source)
        return extracted

    def _extract_method(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        extracted = super()._extract_method(node, source, class_name)
        extracted.return_annotation = self._return_type(node, source)
        extracted.decorators = self._decorators_before(node, source)
        extracted.visibility = self._accessibility(node, source)
        return extracted

    def _extract_function(self, node: tree_sitter.Node, source: bytes) -> ExtractedMethod:
        extracted = super()._extract_function(node, source)
        extracted.return_annotation = self._return_type(node, source)
        return extracted

    def _extract_arrow_function(self, decl_node: tree_sitter.Node, name_node: tree_sitter.Node, arrow_node: tree_sitter.Node, source: bytes) -> ExtractedMethod:
        extracted = super()._extract_arrow_function(decl_node, name_node, arrow_node, source)
        extracted.return_annotation = self._return_type(arrow_node, source)
        return extracted

    def _extract_arrow_method(self, field_node: tree_sitter.Node, name_node: tree_sitter.Node, arrow_node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        extracted = super()._extract_arrow_method(field_node, name_node, arrow_node, source, class_name)
        extracted.return_annotation = self._return_type(arrow_node, source)
        extracted.visibility = self._accessibility(field_node, source)
        return extracted

    def _exported_arrows(self, root: tree_sitter.Node) -> list[tuple[tree_sitter.Node, tree_sitter.Node, tree_sitter.Node]]:
        """(declaration, name, arrow function) of each ``export const name = (...) => ...`` at the top level (the
        JavaScript extractor reads only declarations that are not exported)."""
        found = []
        for statement in root.children:
            if statement.type != "export_statement":
                continue
            for declaration in statement.children:
                if declaration.type not in ("lexical_declaration", "variable_declaration"):
                    continue
                for declarator in self.find_children_by_type(declaration, "variable_declarator"):
                    value, name_node = self.find_child_by_field(declarator, "value"), self.find_child_by_field(declarator, "name")
                    if value is not None and value.type == "arrow_function" and name_node is not None:
                        found.append((declaration, name_node, value))
        return found

    def _extract_single_call(
        self,
        call_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str | None,
    ) -> ExtractedCall | None:
        """As in JavaScript, except that the TypeScript grammar parses ``await x.get<T>(...)`` as a call of
        ``await x.get``: the called expression is the one inside the await."""
        func = self.find_child_by_field(call_node, "function") if call_node.type == "call_expression" else None
        if func is None or func.type != "await_expression":
            return super()._extract_single_call(call_node, source, caller_name, caller_class)
        inner = next((c for c in func.named_children), None)
        if inner is None or inner.type not in ("identifier", "member_expression"):
            return None
        prop = self.find_child_by_field(inner, "property") if inner.type == "member_expression" else inner
        obj = self.find_child_by_field(inner, "object") if inner.type == "member_expression" else None
        if prop is None:
            return None
        return ExtractedCall(
            caller_name=caller_name,
            caller_class=caller_class,
            callee_name=self.get_node_text(prop, source),
            callee_qualifier=self.get_node_text(obj, source) if obj is not None else None,
            line=self.get_line_start(call_node),
            is_method_call=inner.type == "member_expression",
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _type_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """A type's name without its type arguments (``Repository<T>`` is Repository, ``ns.Writer`` stays)."""
        if node.type == "generic_type":
            inner = self.find_child_by_field(node, "name") or node.named_children[0]
            return self.get_node_text(inner, source)
        return self.get_node_text(node, source)

    def _implemented(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """The interfaces a class implements, in order."""
        found: list[str] = []
        for heritage in self.find_children_by_type(node, "class_heritage"):
            for clause in self.find_children_by_type(heritage, "implements_clause"):
                found += [self._type_name(t, source) for t in clause.named_children]
        return found

    def _interface_bases(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """The interfaces an interface extends, in order; other declarations have none."""
        clause = self.find_child_by_type(node, "extends_type_clause")
        return [self._type_name(t, source) for t in clause.named_children] if clause is not None else []

    def _decorator_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """``@Injectable()`` and ``@Injectable`` are Injectable; ``@ng.Component()`` is ng.Component."""
        expression = next((c for c in node.named_children), None)
        if expression is not None and expression.type == "call_expression":
            expression = self.find_child_by_field(expression, "function")
        return self.get_node_text(expression, source) if expression is not None else ""

    def _decorators_of(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """A class's decorators: its own, or, for an exported class, those of its export statement."""
        decorators = [c for c in node.children if c.type == "decorator"]
        if node.parent is not None and node.parent.type == "export_statement":
            decorators = [c for c in node.parent.children if c.type == "decorator"] + decorators
        return [name for d in decorators if (name := self._decorator_name(d, source))]

    def _decorators_before(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """A member's decorators: the decorator nodes right before it in the class body."""
        found: list[str] = []
        previous = node.prev_named_sibling
        while previous is not None and previous.type == "decorator":
            found.insert(0, self._decorator_name(previous, source))
            previous = previous.prev_named_sibling
        return [name for name in found if name]

    def _return_type(self, node: tree_sitter.Node, source: bytes) -> str | None:
        annotation = self.find_child_by_field(node, "return_type")
        return self.get_node_text(annotation, source).lstrip(":").strip() if annotation is not None else None

    def _accessibility(self, node: tree_sitter.Node, source: bytes) -> str | None:
        modifier = self.find_child_by_type(node, "accessibility_modifier")
        return self.get_node_text(modifier, source) if modifier is not None else None

    def _typed_parameter(self, node: tree_sitter.Node, source: bytes) -> dict[str, Any]:
        """A typed parameter: its name (``...`` in front of a rest one), its type without the colon, and whether it
        has a default value or is optional."""
        pattern = self.find_child_by_field(node, "pattern")
        annotation = self.find_child_by_field(node, "type")
        name = self.get_node_text(pattern, source) if pattern is not None else ""
        if pattern is not None and pattern.type == "rest_pattern":
            inner = self.find_child_by_type(pattern, "identifier")
            name = f"...{self.get_node_text(inner, source)}" if inner is not None else name
        return {
            "name": name,
            "annotation": self.get_node_text(annotation, source).lstrip(":").strip() if annotation is not None else None,
            "has_default": self.find_child_by_field(node, "value") is not None or node.type == "optional_parameter",
        }

    def _extract_parameters(self, node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        params_node = self.find_child_by_field(node, "parameters")
        return self._extract_parameters_from_formal(params_node, source) if params_node is not None else []

    def _extract_parameters_from_formal(self, params_node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """TypeScript parameters are required_parameter or optional_parameter nodes; any other kind is read as in
        JavaScript."""
        if not any(child.type in _PARAMETERS for child in params_node.children):
            return super()._extract_parameters_from_formal(params_node, source)
        return [self._typed_parameter(child, source) for child in params_node.children if child.type in _PARAMETERS]


# Register this extractor
register_extractor("typescript", TypeScriptExtractor)
