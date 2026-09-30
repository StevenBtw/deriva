"""JavaScript/TypeScript language extractor using tree-sitter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tree_sitter

from ..models import (
    ExtractedCall,
    ExtractedImport,
    ExtractedMethod,
    ExtractedType,
    FilterConstants,
)
from . import register_extractor
from .base import LanguageExtractor

# =============================================================================
# JavaScript/TypeScript Filter Constants
# =============================================================================

# Node.js built-in modules
JS_STDLIB = {
    # Node.js core modules
    "assert",
    "buffer",
    "child_process",
    "cluster",
    "console",
    "constants",
    "crypto",
    "dgram",
    "dns",
    "domain",
    "events",
    "fs",
    "http",
    "https",
    "module",
    "net",
    "os",
    "path",
    "perf_hooks",
    "process",
    "punycode",
    "querystring",
    "readline",
    "repl",
    "stream",
    "string_decoder",
    "timers",
    "tls",
    "tty",
    "url",
    "util",
    "v8",
    "vm",
    "worker_threads",
    "zlib",
    # Node.js prefixed modules
    "node:assert",
    "node:buffer",
    "node:child_process",
    "node:cluster",
    "node:console",
    "node:crypto",
    "node:dgram",
    "node:dns",
    "node:events",
    "node:fs",
    "node:http",
    "node:https",
    "node:module",
    "node:net",
    "node:os",
    "node:path",
    "node:perf_hooks",
    "node:process",
    "node:querystring",
    "node:readline",
    "node:stream",
    "node:string_decoder",
    "node:timers",
    "node:tls",
    "node:url",
    "node:util",
    "node:v8",
    "node:vm",
    "node:worker_threads",
    "node:zlib",
}

# JavaScript built-in functions and globals
JS_BUILTINS = {
    # Global functions
    "parseInt",
    "parseFloat",
    "isNaN",
    "isFinite",
    "decodeURI",
    "decodeURIComponent",
    "encodeURI",
    "encodeURIComponent",
    "escape",
    "unescape",
    "eval",
    # Console methods
    "console",
    "log",
    "warn",
    "error",
    "info",
    "debug",
    "trace",
    "dir",
    # Timers
    "setTimeout",
    "setInterval",
    "clearTimeout",
    "clearInterval",
    "setImmediate",
    "clearImmediate",
    "queueMicrotask",
    # Promise
    "Promise",
    "resolve",
    "reject",
    "all",
    "race",
    "allSettled",
    "any",
    # Built-in constructors
    "Array",
    "Object",
    "String",
    "Number",
    "Boolean",
    "Symbol",
    "BigInt",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Date",
    "RegExp",
    "Error",
    "TypeError",
    "RangeError",
    "ReferenceError",
    "SyntaxError",
    "URIError",
    "EvalError",
    "AggregateError",
    # Array methods
    "push",
    "pop",
    "shift",
    "unshift",
    "slice",
    "splice",
    "concat",
    "join",
    "reverse",
    "sort",
    "indexOf",
    "lastIndexOf",
    "includes",
    "find",
    "findIndex",
    "filter",
    "map",
    "reduce",
    "reduceRight",
    "every",
    "some",
    "flat",
    "flatMap",
    "fill",
    "copyWithin",
    "entries",
    "keys",
    "values",
    "forEach",
    "from",
    "of",
    "isArray",
    # Object methods
    "assign",
    "create",
    "defineProperty",
    "defineProperties",
    "entries",
    "freeze",
    "fromEntries",
    "getOwnPropertyDescriptor",
    "getOwnPropertyDescriptors",
    "getOwnPropertyNames",
    "getOwnPropertySymbols",
    "getPrototypeOf",
    "hasOwn",
    "is",
    "isExtensible",
    "isFrozen",
    "isSealed",
    "keys",
    "preventExtensions",
    "seal",
    "setPrototypeOf",
    "values",
    # String methods
    "charAt",
    "charCodeAt",
    "codePointAt",
    "concat",
    "endsWith",
    "includes",
    "indexOf",
    "lastIndexOf",
    "localeCompare",
    "match",
    "matchAll",
    "normalize",
    "padEnd",
    "padStart",
    "repeat",
    "replace",
    "replaceAll",
    "search",
    "slice",
    "split",
    "startsWith",
    "substring",
    "toLowerCase",
    "toUpperCase",
    "trim",
    "trimEnd",
    "trimStart",
    # JSON
    "JSON",
    "parse",
    "stringify",
    # Math
    "Math",
    "abs",
    "ceil",
    "floor",
    "round",
    "max",
    "min",
    "pow",
    "sqrt",
    "random",
    "sin",
    "cos",
    "tan",
    "log",
    "exp",
    # Other globals
    "require",
    "module",
    "exports",
    "__dirname",
    "__filename",
    "globalThis",
    "global",
    "window",
    "document",
    "fetch",
}

# JavaScript/TypeScript decorators (experimental)
JS_DECORATOR_BUILTINS = {
    # Common framework decorators
    "Component",
    "Injectable",
    "Module",
    "Controller",
    "Service",
    "Get",
    "Post",
    "Put",
    "Delete",
    "Patch",
    "Options",
    "Head",
    "Inject",
    "Optional",
    "Self",
    "SkipSelf",
    "Host",
    "Input",
    "Output",
    "ViewChild",
    "ViewChildren",
    "ContentChild",
    "ContentChildren",
    "HostBinding",
    "HostListener",
    # NestJS
    "Body",
    "Param",
    "Query",
    "Headers",
    "Req",
    "Res",
    # TypeORM
    "Entity",
    "Column",
    "PrimaryColumn",
    "PrimaryGeneratedColumn",
    "OneToOne",
    "OneToMany",
    "ManyToOne",
    "ManyToMany",
    "JoinColumn",
    "JoinTable",
    "Index",
    "Unique",
    # MobX
    "observable",
    "computed",
    "action",
    "makeObservable",
    "makeAutoObservable",
    # Class-validator
    "IsString",
    "IsNumber",
    "IsBoolean",
    "IsEmail",
    "IsUrl",
    "IsDate",
    "MinLength",
    "MaxLength",
    "Min",
    "Max",
    "IsOptional",
    "IsNotEmpty",
}

# TypeScript built-in types
JS_BUILTIN_TYPES = {
    # Primitives
    "string",
    "number",
    "boolean",
    "symbol",
    "bigint",
    "undefined",
    "null",
    "void",
    "never",
    "unknown",
    "any",
    "object",
    # Built-in objects
    "Array",
    "Object",
    "String",
    "Number",
    "Boolean",
    "Symbol",
    "BigInt",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Date",
    "RegExp",
    "Error",
    "Promise",
    "Function",
    "ArrayBuffer",
    "SharedArrayBuffer",
    "DataView",
    "Uint8Array",
    "Int8Array",
    "Uint16Array",
    "Int16Array",
    "Uint32Array",
    "Int32Array",
    "Float32Array",
    "Float64Array",
    "BigInt64Array",
    "BigUint64Array",
    # TypeScript utility types
    "Partial",
    "Required",
    "Readonly",
    "Record",
    "Pick",
    "Omit",
    "Exclude",
    "Extract",
    "NonNullable",
    "Parameters",
    "ConstructorParameters",
    "ReturnType",
    "InstanceType",
    "ThisParameterType",
    "OmitThisParameter",
    "ThisType",
    "Uppercase",
    "Lowercase",
    "Capitalize",
    "Uncapitalize",
    "Awaited",
    # DOM types (browser)
    "HTMLElement",
    "HTMLDivElement",
    "HTMLInputElement",
    "HTMLButtonElement",
    "Document",
    "Window",
    "Event",
    "MouseEvent",
    "KeyboardEvent",
    "Node",
    "Element",
    "NodeList",
    "EventTarget",
}

JS_GENERIC_CONTAINERS = {
    "Array",
    "Map",
    "Set",
    "WeakMap",
    "WeakSet",
    "Promise",
    "Partial",
    "Required",
    "Readonly",
    "Record",
    "Pick",
    "Omit",
    "Exclude",
    "Extract",
    "NonNullable",
    "Parameters",
    "ReturnType",
    "InstanceType",
    "Awaited",
}


class JavaScriptExtractor(LanguageExtractor):
    """Extractor for JavaScript/TypeScript source code using tree-sitter-javascript."""

    @property
    def language_name(self) -> str:
        return "javascript"

    def get_filter_constants(self) -> FilterConstants:
        """Return JavaScript/TypeScript-specific filter constants."""
        return FilterConstants(
            stdlib_modules=JS_STDLIB,
            builtin_functions=JS_BUILTINS,
            builtin_decorators=JS_DECORATOR_BUILTINS,
            builtin_types=JS_BUILTIN_TYPES,
            generic_containers=JS_GENERIC_CONTAINERS,
        )

    def get_language(self) -> Any:
        """Return the tree-sitter JavaScript language."""
        import tree_sitter_javascript

        return tree_sitter_javascript.language()

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        """Extract type definitions (classes, top-level functions)."""
        types: list[ExtractedType] = []
        root = tree.root_node

        # Extract classes
        for node in self.walk_tree(root, {"class_declaration", "class"}):
            types.append(self._extract_class(node, source))

        # Extract top-level functions
        for node in root.children:
            if node.type == "function_declaration":
                types.append(self._extract_function_as_type(node, source))
            elif node.type == "export_statement":
                # Handle exported functions
                for child in node.children:
                    if child.type == "function_declaration":
                        types.append(self._extract_function_as_type(child, source))
                    elif child.type == "class_declaration":
                        types.append(self._extract_class(child, source))

        # Extract top-level arrow functions assigned to const/let/var
        for node in root.children:
            if node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in self.find_children_by_type(node, "variable_declarator"):
                    value = self.find_child_by_field(declarator, "value")
                    if value and value.type == "arrow_function":
                        name_node = self.find_child_by_field(declarator, "name")
                        if name_node:
                            types.append(self._extract_arrow_function_as_type(node, name_node, value, source))

        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        """Extract methods and functions."""
        methods: list[ExtractedMethod] = []
        root = tree.root_node

        # Extract methods from classes
        for class_node in self.walk_tree(root, {"class_declaration", "class"}):
            class_name = self._get_class_name(class_node, source)
            body = self.find_child_by_field(class_node, "body")
            if body:
                for item in body.children:
                    if item.type == "method_definition":
                        methods.append(self._extract_method(item, source, class_name))
                    elif item.type == "field_definition":
                        # Handle class field arrow functions
                        value = self.find_child_by_field(item, "value")
                        if value and value.type == "arrow_function":
                            name_node = self.find_child_by_field(item, "property")
                            if name_node:
                                methods.append(self._extract_arrow_method(item, name_node, value, source, class_name))

        # Extract top-level functions
        for node in root.children:
            if node.type == "function_declaration":
                methods.append(self._extract_function(node, source))
            elif node.type == "export_statement":
                for child in node.children:
                    if child.type == "function_declaration":
                        methods.append(self._extract_function(child, source))

        # Extract top-level arrow functions
        for node in root.children:
            if node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in self.find_children_by_type(node, "variable_declarator"):
                    value = self.find_child_by_field(declarator, "value")
                    if value and value.type == "arrow_function":
                        name_node = self.find_child_by_field(declarator, "name")
                        if name_node:
                            methods.append(self._extract_arrow_function(node, name_node, value, source))

        return methods

    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        """Extract import statements."""
        imports: list[ExtractedImport] = []
        root = tree.root_node

        for node in root.children:
            if node.type == "import_statement":
                imports.append(self._extract_es6_import(node, source))
            elif node.type in ("lexical_declaration", "variable_declaration"):
                # Handle require() calls
                for declarator in self.find_children_by_type(node, "variable_declarator"):
                    value = self.find_child_by_field(declarator, "value")
                    if value and value.type == "call_expression":
                        func = self.find_child_by_field(value, "function")
                        if func and self.get_node_text(func, source) == "require":
                            imp = self._extract_require(node, declarator, value, source)
                            if imp:
                                imports.append(imp)

        return imports

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        """Extract function and method calls from JavaScript source code."""
        calls: list[ExtractedCall] = []
        root = tree.root_node

        # Extract calls from class methods
        for class_node in self.walk_tree(root, {"class_declaration", "class"}):
            class_name = self._get_class_name(class_node, source)
            body = self.find_child_by_field(class_node, "body")
            if body:
                for item in body.children:
                    if item.type == "method_definition":
                        method_name = self._get_method_name(item, source)
                        calls.extend(self._extract_calls_from_body(item, source, method_name, class_name))
                    elif item.type == "field_definition":
                        # Arrow function field
                        value = self.find_child_by_field(item, "value")
                        if value and value.type == "arrow_function":
                            name_node = self.find_child_by_field(item, "property")
                            if name_node:
                                method_name = self.get_node_text(name_node, source)
                                calls.extend(self._extract_calls_from_arrow(value, source, method_name, class_name))

        # Extract calls from top-level functions
        for node in root.children:
            if node.type == "function_declaration":
                func_name = self._get_function_name(node, source)
                calls.extend(self._extract_calls_from_body(node, source, func_name, None))
            elif node.type == "export_statement":
                for child in node.children:
                    if child.type == "function_declaration":
                        func_name = self._get_function_name(child, source)
                        calls.extend(self._extract_calls_from_body(child, source, func_name, None))

        # Extract calls from top-level arrow functions
        for node in root.children:
            if node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in self.find_children_by_type(node, "variable_declarator"):
                    value = self.find_child_by_field(declarator, "value")
                    if value and value.type == "arrow_function":
                        name_node = self.find_child_by_field(declarator, "name")
                        if name_node:
                            func_name = self.get_node_text(name_node, source)
                            calls.extend(self._extract_calls_from_arrow(value, source, func_name, None))

        return calls

    def _extract_calls_from_body(
        self,
        func_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str | None,
    ) -> list[ExtractedCall]:
        """Extract all function calls from a function body."""
        calls: list[ExtractedCall] = []
        body = self.find_child_by_field(func_node, "body")
        if not body:
            return calls

        # Find all call_expression and new_expression nodes
        call_types = {"call_expression", "new_expression"}
        for call_node in self.walk_tree(body, call_types):
            call = self._extract_single_call(call_node, source, caller_name, caller_class)
            if call:
                calls.append(call)

        return calls

    def _extract_calls_from_arrow(
        self,
        arrow_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str | None,
    ) -> list[ExtractedCall]:
        """Extract calls from an arrow function body."""
        calls: list[ExtractedCall] = []
        body = self.find_child_by_field(arrow_node, "body")
        if not body:
            return calls

        # Arrow function body can be expression or statement_block
        call_types = {"call_expression", "new_expression"}
        for call_node in self.walk_tree(body, call_types):
            call = self._extract_single_call(call_node, source, caller_name, caller_class)
            if call:
                calls.append(call)

        return calls

    def _extract_single_call(
        self,
        call_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str | None,
    ) -> ExtractedCall | None:
        """Extract a single function call or constructor invocation."""
        callee_name = ""
        callee_qualifier = None
        is_method_call = False

        if call_node.type == "call_expression":
            func = self.find_child_by_field(call_node, "function")
            if not func:
                return None

            if func.type == "identifier":
                # Simple function call: foo()
                callee_name = self.get_node_text(func, source)
            elif func.type == "member_expression":
                # Method call: obj.method() or module.func()
                is_method_call = True
                prop = self.find_child_by_field(func, "property")
                obj = self.find_child_by_field(func, "object")

                if prop:
                    callee_name = self.get_node_text(prop, source)
                if obj:
                    callee_qualifier = self.get_node_text(obj, source)
            else:
                # Complex expression (IIFE, etc.)
                return None

        elif call_node.type == "new_expression":
            # Constructor call: new ClassName()
            constructor = self.find_child_by_field(call_node, "constructor")
            if constructor:
                callee_name = self.get_node_text(constructor, source)
                callee_qualifier = "new"

        if not callee_name:
            return None

        return ExtractedCall(
            caller_name=caller_name,
            caller_class=caller_class,
            callee_name=callee_name,
            callee_qualifier=callee_qualifier,
            line=self.get_line_start(call_node),
            is_method_call=is_method_call,
        )

    def _get_function_name(self, func_node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a function declaration."""
        name_node = self.find_child_by_field(func_node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    def _get_method_name(self, method_node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a method definition."""
        name_node = self.find_child_by_field(method_node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    # =========================================================================
    # Private extraction helpers
    # =========================================================================

    def _extract_class(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a class definition."""
        name = self._get_class_name(node, source)
        bases = self._get_bases(node, source)

        return ExtractedType(
            name=name,
            kind="class",
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,  # JS doesn't have docstrings in the same way
            bases=bases,
            decorators=[],
            is_async=False,
        )

    def _extract_function_as_type(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a function declaration as a type."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in node.children)

        return ExtractedType(
            name=name,
            kind="function",
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            bases=[],
            decorators=[],
            is_async=is_async,
        )

    def _extract_arrow_function_as_type(
        self,
        decl_node: tree_sitter.Node,
        name_node: tree_sitter.Node,
        arrow_node: tree_sitter.Node,
        source: bytes,
    ) -> ExtractedType:
        """Extract an arrow function assigned to a variable as a type."""
        name = self.get_node_text(name_node, source)

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in arrow_node.children)

        return ExtractedType(
            name=name,
            kind="function",
            line_start=self.get_line_start(decl_node),
            line_end=self.get_line_end(decl_node),
            docstring=None,
            bases=[],
            decorators=[],
            is_async=is_async,
        )

    def _extract_method(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        """Extract a class method."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in node.children)

        is_static = any(self.get_node_text(child, source) == "static" for child in node.children)

        # Check for getter/setter
        is_property = any(self.get_node_text(child, source) in ("get", "set") for child in node.children)

        parameters = self._extract_parameters(node, source)

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            parameters=parameters,
            return_annotation=None,
            decorators=[],
            is_async=is_async,
            is_static=is_static,
            is_classmethod=False,
            is_property=is_property,
        )

    def _extract_arrow_method(
        self,
        field_node: tree_sitter.Node,
        name_node: tree_sitter.Node,
        arrow_node: tree_sitter.Node,
        source: bytes,
        class_name: str,
    ) -> ExtractedMethod:
        """Extract an arrow function class field as a method."""
        name = self.get_node_text(name_node, source)

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in arrow_node.children)

        is_static = any(self.get_node_text(child, source) == "static" for child in field_node.children)

        parameters = self._extract_arrow_parameters(arrow_node, source)

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(field_node),
            line_end=self.get_line_end(field_node),
            docstring=None,
            parameters=parameters,
            return_annotation=None,
            decorators=[],
            is_async=is_async,
            is_static=is_static,
            is_classmethod=False,
            is_property=False,
        )

    def _extract_function(self, node: tree_sitter.Node, source: bytes) -> ExtractedMethod:
        """Extract a standalone function."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in node.children)

        parameters = self._extract_parameters(node, source)

        return ExtractedMethod(
            name=name,
            class_name=None,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            parameters=parameters,
            return_annotation=None,
            decorators=[],
            is_async=is_async,
            is_static=False,
            is_classmethod=False,
            is_property=False,
        )

    def _extract_arrow_function(
        self,
        decl_node: tree_sitter.Node,
        name_node: tree_sitter.Node,
        arrow_node: tree_sitter.Node,
        source: bytes,
    ) -> ExtractedMethod:
        """Extract an arrow function assigned to a variable."""
        name = self.get_node_text(name_node, source)

        is_async = any(child.type == "async" or self.get_node_text(child, source) == "async" for child in arrow_node.children)

        parameters = self._extract_arrow_parameters(arrow_node, source)

        return ExtractedMethod(
            name=name,
            class_name=None,
            line_start=self.get_line_start(decl_node),
            line_end=self.get_line_end(decl_node),
            docstring=None,
            parameters=parameters,
            return_annotation=None,
            decorators=[],
            is_async=is_async,
            is_static=False,
            is_classmethod=False,
            is_property=False,
        )

    def _extract_es6_import(self, node: tree_sitter.Node, source: bytes) -> ExtractedImport:
        """Extract ES6 import statement."""
        # Get the module/source
        source_node = self.find_child_by_field(node, "source")
        module = ""
        if source_node:
            module = self.get_node_text(source_node, source)
            # Remove quotes
            module = module.strip("'\"")

        # Get imported names
        names: list[str] = []
        alias: str | None = None

        for child in node.children:
            if child.type == "import_clause":
                for subchild in child.children:
                    if subchild.type == "identifier":
                        # Default import
                        names.append(self.get_node_text(subchild, source))
                    elif subchild.type == "named_imports":
                        for spec in subchild.children:
                            if spec.type == "import_specifier":
                                name_node = self.find_child_by_field(spec, "name")
                                if name_node:
                                    names.append(self.get_node_text(name_node, source))
                    elif subchild.type == "namespace_import":
                        # import * as X
                        alias_node = self.find_child_by_type(subchild, "identifier")
                        if alias_node:
                            alias = self.get_node_text(alias_node, source)
                            names.append("*")

        return ExtractedImport(
            module=module,
            names=names,
            alias=alias,
            line=self.get_line_start(node),
            is_from_import=True,
        )

    def _extract_require(
        self,
        decl_node: tree_sitter.Node,
        declarator: tree_sitter.Node,
        call_node: tree_sitter.Node,
        source: bytes,
    ) -> ExtractedImport | None:
        """Extract CommonJS require() call."""
        # Get module name from arguments
        args = self.find_child_by_field(call_node, "arguments")
        if not args:
            return None

        module = ""
        for child in args.children:
            if child.type == "string":
                module = self.get_node_text(child, source).strip("'\"")
                break

        # Get variable name
        name_node = self.find_child_by_field(declarator, "name")
        names: list[str] = []

        if name_node:
            if name_node.type == "identifier":
                names.append(self.get_node_text(name_node, source))
            elif name_node.type == "object_pattern":
                # Destructuring: const { a, b } = require('...')
                for child in name_node.children:
                    if child.type == "shorthand_property_identifier_pattern":
                        names.append(self.get_node_text(child, source))
                    elif child.type == "pair_pattern":
                        key = self.find_child_by_field(child, "key")
                        if key:
                            names.append(self.get_node_text(key, source))

        return ExtractedImport(
            module=module,
            names=names,
            alias=None,
            line=self.get_line_start(decl_node),
            is_from_import=False,
        )

    # =========================================================================
    # Utility helpers
    # =========================================================================

    def _get_class_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a class."""
        name_node = self.find_child_by_field(node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    def _get_bases(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get base/parent class from extends clause."""
        bases: list[str] = []

        # Look for class_heritage or extends
        for child in node.children:
            if child.type == "class_heritage":
                for subchild in child.children:
                    if subchild.type == "extends_clause":
                        for item in subchild.children:
                            if item.type == "identifier":
                                bases.append(self.get_node_text(item, source))
                            elif item.type == "member_expression":
                                bases.append(self.get_node_text(item, source))

        return bases

    def _extract_parameters(self, node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract function parameters."""
        params: list[dict[str, Any]] = []

        params_node = self.find_child_by_field(node, "parameters")
        if not params_node:
            return params

        for child in params_node.children:
            if child.type == "identifier":
                params.append(
                    {
                        "name": self.get_node_text(child, source),
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "assignment_pattern":
                # Parameter with default value
                left = self.find_child_by_field(child, "left")
                name = self.get_node_text(left, source) if left else ""
                params.append(
                    {
                        "name": name,
                        "annotation": None,
                        "has_default": True,
                    }
                )
            elif child.type == "rest_pattern":
                # ...args
                name_node = self.find_child_by_type(child, "identifier")
                name = self.get_node_text(name_node, source) if name_node else ""
                params.append(
                    {
                        "name": f"...{name}",
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "object_pattern":
                # Destructuring parameter
                params.append(
                    {
                        "name": self.get_node_text(child, source),
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "array_pattern":
                # Array destructuring parameter
                params.append(
                    {
                        "name": self.get_node_text(child, source),
                        "annotation": None,
                        "has_default": False,
                    }
                )

        return params

    def _extract_arrow_parameters(self, arrow_node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract parameters from arrow function."""
        params: list[dict[str, Any]] = []

        # Arrow function can have single identifier or formal_parameters
        param_node = self.find_child_by_field(arrow_node, "parameter")
        if param_node:
            # Single parameter without parens
            params.append(
                {
                    "name": self.get_node_text(param_node, source),
                    "annotation": None,
                    "has_default": False,
                }
            )
        else:
            params_node = self.find_child_by_field(arrow_node, "parameters")
            if params_node:
                return self._extract_parameters_from_formal(params_node, source)

        return params

    def _extract_parameters_from_formal(self, params_node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract parameters from formal_parameters node."""
        params: list[dict[str, Any]] = []

        for child in params_node.children:
            if child.type == "identifier":
                params.append(
                    {
                        "name": self.get_node_text(child, source),
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "assignment_pattern":
                left = self.find_child_by_field(child, "left")
                name = self.get_node_text(left, source) if left else ""
                params.append(
                    {
                        "name": name,
                        "annotation": None,
                        "has_default": True,
                    }
                )
            elif child.type == "rest_pattern":
                name_node = self.find_child_by_type(child, "identifier")
                name = self.get_node_text(name_node, source) if name_node else ""
                params.append(
                    {
                        "name": f"...{name}",
                        "annotation": None,
                        "has_default": False,
                    }
                )

        return params


# Register this extractor
register_extractor("javascript", JavaScriptExtractor)
