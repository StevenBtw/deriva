"""Python language extractor using tree-sitter."""

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
# Python Filter Constants
# =============================================================================

PYTHON_STDLIB = {
    "abc",
    "argparse",
    "ast",
    "asyncio",
    "atexit",
    "base64",
    "bisect",
    "builtins",
    "calendar",
    "cgi",
    "cmd",
    "codecs",
    "collections",
    "concurrent",
    "configparser",
    "contextlib",
    "copy",
    "csv",
    "ctypes",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "dis",
    "email",
    "encodings",
    "enum",
    "errno",
    "faulthandler",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "glob",
    "graphlib",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "imaplib",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "multiprocessing",
    "netrc",
    "numbers",
    "operator",
    "optparse",
    "os",
    "pathlib",
    "pdb",
    "pickle",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "smtplib",
    "socket",
    "socketserver",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "struct",
    "subprocess",
    "sys",
    "sysconfig",
    "syslog",
    "tarfile",
    "tempfile",
    "test",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "token",
    "tokenize",
    "trace",
    "traceback",
    "tracemalloc",
    "turtle",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "wsgiref",
    "xml",
    "xmlrpc",
    "zipfile",
    "zipimport",
    "zlib",
    "typing_extensions",
    "TYPE_CHECKING",
}

PYTHON_BUILTINS = {
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "breakpoint",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "compile",
    "complex",
    "delattr",
    "dict",
    "dir",
    "divmod",
    "enumerate",
    "eval",
    "exec",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "globals",
    "hasattr",
    "hash",
    "help",
    "hex",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "locals",
    "map",
    "max",
    "memoryview",
    "min",
    "next",
    "object",
    "oct",
    "open",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
    # Common exceptions
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "RuntimeError",
    "AttributeError",
    "ImportError",
    "OSError",
    "IOError",
}

PYTHON_DECORATOR_BUILTINS = {
    # Standard library
    "staticmethod",
    "classmethod",
    "property",
    "abstractmethod",
    "abstractproperty",
    "abstractclassmethod",
    "abstractstaticmethod",
    "dataclass",
    "dataclasses.dataclass",
    "functools.wraps",
    "functools.lru_cache",
    "functools.cache",
    "functools.cached_property",
    "functools.total_ordering",
    "functools.singledispatch",
    "functools.singledispatchmethod",
    "contextlib.contextmanager",
    "contextlib.asynccontextmanager",
    "typing.overload",
    "typing.override",
    "typing.final",
    "typing.no_type_check",
    "typing.runtime_checkable",
    # Common frameworks
    "app.route",
    "app.get",
    "app.post",
    "app.put",
    "app.delete",
    "app.patch",
    "pytest.fixture",
    "pytest.mark",
    "pytest.mark.parametrize",
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.mark.xfail",
    "unittest.skip",
    "unittest.skipIf",
    "unittest.expectedFailure",
    "mock.patch",
    "unittest.mock.patch",
}

PYTHON_BUILTIN_TYPES = {
    # Primitives
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "None",
    "complex",
    "object",
    # Collections (builtin)
    "list",
    "dict",
    "set",
    "tuple",
    "frozenset",
    # Typing module basics
    "Any",
    "Union",
    "Optional",
    "Callable",
    "Type",
    "ClassVar",
    "Final",
    "Literal",
    "TypeVar",
    "Generic",
    "Protocol",
    "Annotated",
    "Self",
    "Never",
    "NoReturn",
    # Collection types from typing
    "List",
    "Dict",
    "Set",
    "Tuple",
    "FrozenSet",
    "Sequence",
    "Mapping",
    "MutableMapping",
    "MutableSequence",
    "Iterable",
    "Iterator",
    "Generator",
    "Coroutine",
    "AsyncGenerator",
    "AsyncIterator",
    "AsyncIterable",
    "Awaitable",
    "ContextManager",
    "AsyncContextManager",
    "Pattern",
    "Match",
    # Common ABCs
    "ABC",
    "ABCMeta",
}

PYTHON_GENERIC_CONTAINERS = {
    "List",
    "Dict",
    "Set",
    "Tuple",
    "FrozenSet",
    "Optional",
    "Union",
    "Sequence",
    "Mapping",
    "Iterable",
    "Iterator",
    "Generator",
    "Callable",
    "Type",
    "ClassVar",
    "Final",
    "Annotated",
    "Awaitable",
    "Coroutine",
    "AsyncGenerator",
}


class PythonExtractor(LanguageExtractor):
    """Extractor for Python source code using tree-sitter-python."""

    @property
    def language_name(self) -> str:
        return "python"

    def get_filter_constants(self) -> FilterConstants:
        """Return Python-specific filter constants."""
        return FilterConstants(
            stdlib_modules=PYTHON_STDLIB,
            builtin_functions=PYTHON_BUILTINS,
            builtin_decorators=PYTHON_DECORATOR_BUILTINS,
            builtin_types=PYTHON_BUILTIN_TYPES,
            generic_containers=PYTHON_GENERIC_CONTAINERS,
        )

    def get_language(self) -> Any:
        """Return the tree-sitter Python language."""
        import tree_sitter_python

        return tree_sitter_python.language()

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        """Extract type definitions (classes, top-level functions, type aliases)."""
        types: list[ExtractedType] = []
        root = tree.root_node

        # Extract classes
        for node in self.walk_tree(root, {"class_definition"}):
            types.append(self._extract_class(node, source))

        # Extract top-level functions (not methods inside classes)
        for node in root.children:
            if node.type == "function_definition":
                types.append(self._extract_function_as_type(node, source))
            elif node.type == "decorated_definition":
                inner = self._get_decorated_inner(node)
                if inner and inner.type == "function_definition":
                    types.append(self._extract_function_as_type(node, source, inner))

        # Extract type aliases (Python 3.12+ type statement or TypeAlias annotation)
        for node in self.walk_tree(root, {"type_alias_statement"}):
            types.append(self._extract_type_alias(node, source))

        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        """Extract methods and functions."""
        methods: list[ExtractedMethod] = []
        root = tree.root_node

        # Extract methods from classes
        for class_node in self.walk_tree(root, {"class_definition"}):
            class_name = self._get_class_name(class_node, source)
            body = self.find_child_by_field(class_node, "body")
            if body:
                for item in body.children:
                    if item.type == "function_definition":
                        methods.append(self._extract_method(item, source, class_name))
                    elif item.type == "decorated_definition":
                        inner = self._get_decorated_inner(item)
                        if inner and inner.type == "function_definition":
                            methods.append(self._extract_method(item, source, class_name, inner))

        # Extract top-level functions
        for node in root.children:
            if node.type == "function_definition":
                methods.append(self._extract_method(node, source, None))
            elif node.type == "decorated_definition":
                inner = self._get_decorated_inner(node)
                if inner and inner.type == "function_definition":
                    methods.append(self._extract_method(node, source, None, inner))

        return methods

    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        """Extract import statements."""
        imports: list[ExtractedImport] = []
        root = tree.root_node

        for node in root.children:
            if node.type == "import_statement":
                imports.extend(self._extract_import(node, source))
            elif node.type == "import_from_statement":
                imports.append(self._extract_from_import(node, source))

        return imports

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        """Extract function/method calls from functions and methods."""
        calls: list[ExtractedCall] = []
        root = tree.root_node

        # Extract calls from class methods
        for class_node in self.walk_tree(root, {"class_definition"}):
            class_name = self._get_class_name(class_node, source)
            body = self.find_child_by_field(class_node, "body")
            if body:
                for item in body.children:
                    func_node = None
                    if item.type == "function_definition":
                        func_node = item
                    elif item.type == "decorated_definition":
                        func_node = self._get_decorated_inner(item)

                    if func_node and func_node.type == "function_definition":
                        func_name = self._get_function_name(func_node, source)
                        calls.extend(self._extract_calls_from_body(func_node, source, func_name, class_name))

        # Extract calls from top-level functions
        for node in root.children:
            func_node = None
            if node.type == "function_definition":
                func_node = node
            elif node.type == "decorated_definition":
                func_node = self._get_decorated_inner(node)

            if func_node and func_node.type == "function_definition":
                func_name = self._get_function_name(func_node, source)
                calls.extend(self._extract_calls_from_body(func_node, source, func_name, None))

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

        # Find all call expressions in the body
        for call_node in self.walk_tree(body, {"call"}):
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
        """Extract a single function call."""
        func = self.find_child_by_field(call_node, "function")
        if not func:
            return None

        callee_name = ""
        callee_qualifier = None
        is_method_call = False

        if func.type == "identifier":
            # Simple function call: foo()
            callee_name = self.get_node_text(func, source)
        elif func.type == "attribute":
            # Method/attribute call: obj.method() or module.func()
            is_method_call = True
            attr_node = self.find_child_by_field(func, "attribute")
            obj_node = self.find_child_by_field(func, "object")

            if attr_node:
                callee_name = self.get_node_text(attr_node, source)
            if obj_node:
                callee_qualifier = self.get_node_text(obj_node, source)
        else:
            # Complex expression (e.g., func_array[0]())
            return None

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
        """Get the name of a function."""
        name_node = self.find_child_by_field(func_node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    # =========================================================================
    # Private extraction helpers
    # =========================================================================

    def _extract_class(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a class definition."""
        name = self._get_class_name(node, source)
        bases = self._get_bases(node, source)
        decorators = self._get_decorators(node, source)
        docstring = self._get_docstring(node, source)

        return ExtractedType(
            name=name,
            kind="class",
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=docstring,
            bases=bases,
            decorators=decorators,
            is_async=False,
        )

    def _extract_function_as_type(
        self,
        node: tree_sitter.Node,
        source: bytes,
        inner_func: tree_sitter.Node | None = None,
    ) -> ExtractedType:
        """Extract a top-level function as a type definition."""
        func_node = inner_func or node
        decorators = self._get_decorators(node, source) if node.type == "decorated_definition" else []

        name_node = self.find_child_by_field(func_node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        is_async = func_node.type == "function_definition" and any(child.type == "async" for child in func_node.children)
        # Check parent for async
        if not is_async:
            for child in func_node.children:
                if self.get_node_text(child, source) == "async":
                    is_async = True
                    break

        docstring = self._get_docstring(func_node, source)

        return ExtractedType(
            name=name,
            kind="function",
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=docstring,
            bases=[],
            decorators=decorators,
            is_async=is_async,
        )

    def _extract_type_alias(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a type alias (type X = ...)."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        return ExtractedType(
            name=name,
            kind="type_alias",
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            bases=[],
            decorators=[],
            is_async=False,
        )

    def _extract_method(
        self,
        node: tree_sitter.Node,
        source: bytes,
        class_name: str | None,
        inner_func: tree_sitter.Node | None = None,
    ) -> ExtractedMethod:
        """Extract a method or function definition."""
        func_node = inner_func or node
        decorators = self._get_decorators(node, source) if node.type == "decorated_definition" else []
        if not decorators and node.type == "function_definition":
            # Check if parent is decorated_definition
            decorators = []

        name_node = self.find_child_by_field(func_node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        # Check for async
        is_async = False
        node_text = self.get_node_text(func_node, source)
        if node_text.strip().startswith("async "):
            is_async = True

        # Determine method characteristics from decorators
        decorator_names = [d.split("(")[0] for d in decorators]
        is_static = "staticmethod" in decorator_names
        is_classmethod = "classmethod" in decorator_names
        is_property = "property" in decorator_names

        # Extract parameters
        parameters = self._extract_parameters(func_node, source)

        # Extract return annotation
        return_type = self.find_child_by_field(func_node, "return_type")
        return_annotation = self.get_node_text(return_type, source) if return_type else None
        if return_annotation and return_annotation.startswith("->"):
            return_annotation = return_annotation[2:].strip()

        docstring = self._get_docstring(func_node, source)

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=docstring,
            parameters=parameters,
            return_annotation=return_annotation,
            decorators=decorators,
            is_async=is_async,
            is_static=is_static,
            is_classmethod=is_classmethod,
            is_property=is_property,
        )

    def _extract_import(self, node: tree_sitter.Node, source: bytes) -> list[ExtractedImport]:
        """Extract regular import statement (import x, y, z)."""
        imports: list[ExtractedImport] = []

        for child in node.children:
            if child.type == "dotted_name":
                module = self.get_node_text(child, source)
                imports.append(
                    ExtractedImport(
                        module=module,
                        names=[],
                        alias=None,
                        line=self.get_line_start(node),
                        is_from_import=False,
                    )
                )
            elif child.type == "aliased_import":
                name_node = self.find_child_by_type(child, "dotted_name")
                alias_node = self.find_child_by_field(child, "alias")
                module = self.get_node_text(name_node, source) if name_node else ""
                alias = self.get_node_text(alias_node, source) if alias_node else None
                imports.append(
                    ExtractedImport(
                        module=module,
                        names=[],
                        alias=alias,
                        line=self.get_line_start(node),
                        is_from_import=False,
                    )
                )

        return imports

    def _extract_from_import(self, node: tree_sitter.Node, source: bytes) -> ExtractedImport:
        """Extract from ... import statement."""
        module_node = self.find_child_by_field(node, "module_name")
        module = self.get_node_text(module_node, source) if module_node else ""

        # Handle relative imports
        prefix = ""
        for child in node.children:
            if child.type == "relative_import":
                for subchild in child.children:
                    if subchild.type == "import_prefix":
                        prefix = self.get_node_text(subchild, source)
                    elif subchild.type == "dotted_name":
                        module = self.get_node_text(subchild, source)
                break

        if prefix:
            module = prefix + module

        # Extract imported names
        names: list[str] = []
        for child in node.children:
            if child.type == "import_from_specifier" or child.type == "dotted_name":
                # Skip the module name
                if child == module_node:
                    continue
                name = self.get_node_text(child, source)
                if name and name not in ("from", "import", ","):
                    names.append(name)
            elif child.type == "wildcard_import":
                names.append("*")

        return ExtractedImport(
            module=module,
            names=names,
            alias=None,
            line=self.get_line_start(node),
            is_from_import=True,
        )

    # =========================================================================
    # Utility helpers
    # =========================================================================

    def _get_class_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a class."""
        name_node = self.find_child_by_field(node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    def _get_bases(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get base classes from class definition."""
        bases: list[str] = []
        superclass_node = self.find_child_by_field(node, "superclasses")
        if superclass_node:
            # argument_list contains the base classes
            for child in superclass_node.children:
                if child.type in ("identifier", "attribute"):
                    bases.append(self.get_node_text(child, source))
                elif child.type == "argument":
                    # Handle keyword arguments like metaclass=...
                    pass
        return bases

    def _get_decorators(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get decorators from a decorated definition or function/class."""
        decorators: list[str] = []

        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    dec_text = self.get_node_text(child, source)
                    # Remove the @ prefix
                    if dec_text.startswith("@"):
                        dec_text = dec_text[1:]
                    decorators.append(dec_text)
        return decorators

    def _get_docstring(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Extract docstring from a class or function."""
        body = self.find_child_by_field(node, "body")
        if not body:
            return None

        # First statement in body might be a docstring
        for child in body.children:
            if child.type == "expression_statement":
                for subchild in child.children:
                    if subchild.type == "string":
                        text = self.get_node_text(subchild, source)
                        # Remove quotes
                        if text.startswith('"""') and text.endswith('"""'):
                            return text[3:-3].strip()
                        elif text.startswith("'''") and text.endswith("'''"):
                            return text[3:-3].strip()
                        elif text.startswith('"') and text.endswith('"'):
                            return text[1:-1].strip()
                        elif text.startswith("'") and text.endswith("'"):
                            return text[1:-1].strip()
                break  # Only check first statement

        return None

    def _get_decorated_inner(self, node: tree_sitter.Node) -> tree_sitter.Node | None:
        """Get the inner definition from a decorated_definition."""
        if node.type != "decorated_definition":
            return None
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                return child
        return None

    def _extract_parameters(self, func_node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract function parameters with type annotations."""
        params: list[dict[str, Any]] = []

        params_node = self.find_child_by_field(func_node, "parameters")
        if not params_node:
            return params

        for child in params_node.children:
            if child.type == "identifier":
                # Simple parameter without annotation
                params.append(
                    {
                        "name": self.get_node_text(child, source),
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "typed_parameter":
                name_node = self.find_child_by_type(child, "identifier")
                type_node = self.find_child_by_field(child, "type")
                name = self.get_node_text(name_node, source) if name_node else ""
                annotation = self.get_node_text(type_node, source) if type_node else None
                params.append(
                    {
                        "name": name,
                        "annotation": annotation,
                        "has_default": False,
                    }
                )
            elif child.type == "default_parameter":
                name_node = self.find_child_by_type(child, "identifier")
                name = self.get_node_text(name_node, source) if name_node else ""
                params.append(
                    {
                        "name": name,
                        "annotation": None,
                        "has_default": True,
                    }
                )
            elif child.type == "typed_default_parameter":
                name_node = self.find_child_by_type(child, "identifier")
                type_node = self.find_child_by_field(child, "type")
                name = self.get_node_text(name_node, source) if name_node else ""
                annotation = self.get_node_text(type_node, source) if type_node else None
                params.append(
                    {
                        "name": name,
                        "annotation": annotation,
                        "has_default": True,
                    }
                )
            elif child.type == "list_splat_pattern":
                # *args
                name_node = self.find_child_by_type(child, "identifier")
                name = self.get_node_text(name_node, source) if name_node else ""
                params.append(
                    {
                        "name": f"*{name}",
                        "annotation": None,
                        "has_default": False,
                    }
                )
            elif child.type == "dictionary_splat_pattern":
                # **kwargs
                name_node = self.find_child_by_type(child, "identifier")
                name = self.get_node_text(name_node, source) if name_node else ""
                params.append(
                    {
                        "name": f"**{name}",
                        "annotation": None,
                        "has_default": False,
                    }
                )

        return params


# Register this extractor
register_extractor("python", PythonExtractor)
