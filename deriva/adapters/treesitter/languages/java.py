"""Java language extractor using tree-sitter."""

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
# Java Filter Constants
# =============================================================================

# Java standard library packages (java.*, javax.*, sun.*, com.sun.*, etc.)
JAVA_STDLIB = {
    # Core Java
    "java.lang",
    "java.util",
    "java.io",
    "java.nio",
    "java.net",
    "java.math",
    "java.text",
    "java.time",
    "java.sql",
    "java.security",
    "java.awt",
    "java.beans",
    "java.applet",
    "java.rmi",
    "java.lang.annotation",
    "java.lang.instrument",
    "java.lang.invoke",
    "java.lang.management",
    "java.lang.ref",
    "java.lang.reflect",
    "java.util.concurrent",
    "java.util.concurrent.atomic",
    "java.util.concurrent.locks",
    "java.util.function",
    "java.util.jar",
    "java.util.logging",
    "java.util.prefs",
    "java.util.regex",
    "java.util.stream",
    "java.util.zip",
    # JavaX
    "javax.swing",
    "javax.xml",
    "javax.net",
    "javax.crypto",
    "javax.sql",
    "javax.naming",
    "javax.sound",
    "javax.imageio",
    "javax.print",
    "javax.management",
    "javax.annotation",
    "javax.servlet",
    "javax.persistence",
    "javax.validation",
    "javax.inject",
    "javax.ws",
    "javax.json",
    # Jakarta (successor to javax for EE)
    "jakarta.servlet",
    "jakarta.persistence",
    "jakarta.validation",
    "jakarta.inject",
    "jakarta.ws",
    "jakarta.json",
    "jakarta.annotation",
}

# Java built-in methods and common methods to skip
JAVA_BUILTINS = {
    # Object methods
    "toString",
    "hashCode",
    "equals",
    "clone",
    "getClass",
    "notify",
    "notifyAll",
    "wait",
    "finalize",
    # Common methods
    "get",
    "set",
    "add",
    "remove",
    "contains",
    "size",
    "isEmpty",
    "clear",
    "put",
    "containsKey",
    "containsValue",
    "keySet",
    "values",
    "entrySet",
    "iterator",
    "hasNext",
    "next",
    "forEach",
    # String methods
    "length",
    "charAt",
    "substring",
    "indexOf",
    "lastIndexOf",
    "startsWith",
    "endsWith",
    "trim",
    "toLowerCase",
    "toUpperCase",
    "split",
    "replace",
    "replaceAll",
    "matches",
    "concat",
    "compareTo",
    "format",
    "valueOf",
    # Collection methods
    "stream",
    "collect",
    "filter",
    "map",
    "reduce",
    "flatMap",
    "sorted",
    "distinct",
    "limit",
    "skip",
    "findFirst",
    "findAny",
    "anyMatch",
    "allMatch",
    "noneMatch",
    "count",
    "toList",
    "toSet",
    "toArray",
    # IO methods
    "read",
    "write",
    "close",
    "flush",
    "print",
    "println",
    "printf",
    # Common static methods
    "main",
    "getInstance",
    "newInstance",
    "of",
    "ofNullable",
    "empty",
    "orElse",
    "orElseGet",
    "orElseThrow",
    "isPresent",
    "ifPresent",
    # Logging
    "log",
    "debug",
    "info",
    "warn",
    "error",
    "trace",
}

# Java annotations (decorators)
JAVA_DECORATOR_BUILTINS = {
    # Core Java
    "Override",
    "Deprecated",
    "SuppressWarnings",
    "SafeVarargs",
    "FunctionalInterface",
    "Native",
    "Repeatable",
    "Retention",
    "Target",
    "Documented",
    "Inherited",
    # Testing
    "Test",
    "Before",
    "After",
    "BeforeAll",
    "AfterAll",
    "BeforeEach",
    "AfterEach",
    "Disabled",
    "DisplayName",
    "Tag",
    "Nested",
    "ParameterizedTest",
    "ValueSource",
    "EnumSource",
    "MethodSource",
    "CsvSource",
    "Mock",
    "InjectMocks",
    "Spy",
    "Captor",
    "RunWith",
    "ExtendWith",
    # Spring Framework
    "Component",
    "Service",
    "Repository",
    "Controller",
    "RestController",
    "Configuration",
    "Bean",
    "Autowired",
    "Qualifier",
    "Value",
    "Primary",
    "Scope",
    "Lazy",
    "PostConstruct",
    "PreDestroy",
    "Profile",
    "RequestMapping",
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "DeleteMapping",
    "PatchMapping",
    "PathVariable",
    "RequestParam",
    "RequestBody",
    "ResponseBody",
    "ResponseStatus",
    "ExceptionHandler",
    "ControllerAdvice",
    "CrossOrigin",
    "Transactional",
    "Cacheable",
    "CacheEvict",
    "Scheduled",
    "Async",
    "EnableAutoConfiguration",
    "SpringBootApplication",
    "EnableWebMvc",
    # JPA/Hibernate
    "Entity",
    "Table",
    "Id",
    "GeneratedValue",
    "Column",
    "Temporal",
    "OneToOne",
    "OneToMany",
    "ManyToOne",
    "ManyToMany",
    "JoinColumn",
    "JoinTable",
    "Embeddable",
    "Embedded",
    "MappedSuperclass",
    "Inheritance",
    "DiscriminatorColumn",
    "DiscriminatorValue",
    "NamedQuery",
    "NamedQueries",
    # Lombok
    "Data",
    "Getter",
    "Setter",
    "NoArgsConstructor",
    "AllArgsConstructor",
    "RequiredArgsConstructor",
    "Builder",
    "ToString",
    "EqualsAndHashCode",
    "Slf4j",
    "Log",
    "Log4j",
    "Log4j2",
    # Validation
    "NotNull",
    "NotEmpty",
    "NotBlank",
    "Size",
    "Min",
    "Max",
    "Email",
    "Pattern",
    "Past",
    "Future",
    "Valid",
    "Validated",
}

# Java built-in types
JAVA_BUILTIN_TYPES = {
    # Primitives
    "int",
    "long",
    "short",
    "byte",
    "float",
    "double",
    "boolean",
    "char",
    "void",
    # Wrapper classes
    "Integer",
    "Long",
    "Short",
    "Byte",
    "Float",
    "Double",
    "Boolean",
    "Character",
    "String",
    "Object",
    "Class",
    "Void",
    "Number",
    # Collections
    "List",
    "Set",
    "Map",
    "Collection",
    "Queue",
    "Deque",
    "Stack",
    "ArrayList",
    "LinkedList",
    "HashSet",
    "TreeSet",
    "LinkedHashSet",
    "HashMap",
    "TreeMap",
    "LinkedHashMap",
    "Hashtable",
    "ConcurrentHashMap",
    "Vector",
    "PriorityQueue",
    "ArrayDeque",
    # Utility types
    "Optional",
    "Stream",
    "Collector",
    "Collectors",
    "Comparator",
    "Iterator",
    "Iterable",
    "Enumeration",
    "Arrays",
    "Collections",
    # Time types
    "Date",
    "Calendar",
    "LocalDate",
    "LocalTime",
    "LocalDateTime",
    "ZonedDateTime",
    "Instant",
    "Duration",
    "Period",
    "DateTimeFormatter",
    # IO types
    "File",
    "Path",
    "InputStream",
    "OutputStream",
    "Reader",
    "Writer",
    "BufferedReader",
    "BufferedWriter",
    "FileReader",
    "FileWriter",
    # Exceptions
    "Exception",
    "RuntimeException",
    "Error",
    "Throwable",
    "NullPointerException",
    "IllegalArgumentException",
    "IllegalStateException",
    "IOException",
    "SQLException",
    "ClassNotFoundException",
    # Functional interfaces
    "Function",
    "Supplier",
    "Consumer",
    "Predicate",
    "BiFunction",
    "BiConsumer",
    "BiPredicate",
    "UnaryOperator",
    "BinaryOperator",
    "Runnable",
    "Callable",
    "Future",
    "CompletableFuture",
    # Concurrency
    "Thread",
    "Executor",
    "ExecutorService",
    "ThreadPoolExecutor",
    "Semaphore",
    "CountDownLatch",
    "CyclicBarrier",
    "Lock",
    "ReentrantLock",
    # Generics
    "T",
    "E",
    "K",
    "V",
    "R",
    "U",
}

JAVA_GENERIC_CONTAINERS = {
    "List",
    "Set",
    "Map",
    "Collection",
    "Queue",
    "Deque",
    "ArrayList",
    "LinkedList",
    "HashSet",
    "TreeSet",
    "HashMap",
    "TreeMap",
    "Optional",
    "Stream",
    "Future",
    "CompletableFuture",
    "Function",
    "Supplier",
    "Consumer",
    "Predicate",
    "Comparable",
    "Comparator",
    "Iterable",
    "Iterator",
}


class JavaExtractor(LanguageExtractor):
    """Extractor for Java source code using tree-sitter-java."""

    @property
    def language_name(self) -> str:
        return "java"

    def get_filter_constants(self) -> FilterConstants:
        """Return Java-specific filter constants."""
        return FilterConstants(
            stdlib_modules=JAVA_STDLIB,
            builtin_functions=JAVA_BUILTINS,
            builtin_decorators=JAVA_DECORATOR_BUILTINS,
            builtin_types=JAVA_BUILTIN_TYPES,
            generic_containers=JAVA_GENERIC_CONTAINERS,
        )

    def get_language(self) -> Any:
        """Return the tree-sitter Java language."""
        import tree_sitter_java

        return tree_sitter_java.language()

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        """Extract type definitions (classes, interfaces, enums, records)."""
        types: list[ExtractedType] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "annotation_type_declaration",
        }

        for node in self.walk_tree(root, type_nodes):
            types.append(self._extract_type(node, source))

        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        """Extract methods and constructors."""
        methods: list[ExtractedMethod] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        }

        for type_node in self.walk_tree(root, type_nodes):
            class_name = self._get_type_name(type_node, source)
            body = self.find_child_by_field(type_node, "body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        methods.append(self._extract_method(child, source, class_name))
                    elif child.type == "constructor_declaration":
                        methods.append(self._extract_constructor(child, source, class_name))

        return methods

    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        """Extract import declarations."""
        imports: list[ExtractedImport] = []
        root = tree.root_node

        for node in root.children:
            if node.type == "import_declaration":
                imports.append(self._extract_import(node, source))

        return imports

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        """Extract method and constructor calls from Java source code."""
        calls: list[ExtractedCall] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        }

        # Extract calls from methods in type definitions
        for type_node in self.walk_tree(root, type_nodes):
            class_name = self._get_type_name(type_node, source)
            body = self.find_child_by_field(type_node, "body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        method_name = self._get_method_name(child, source)
                        calls.extend(self._extract_calls_from_body(child, source, method_name, class_name))
                    elif child.type == "constructor_declaration":
                        name_node = self.find_child_by_field(child, "name")
                        constructor_name = self.get_node_text(name_node, source) if name_node else class_name
                        calls.extend(self._extract_calls_from_body(child, source, constructor_name, class_name))

        return calls

    def _extract_calls_from_body(
        self,
        method_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str,
    ) -> list[ExtractedCall]:
        """Extract all method calls from a method body."""
        calls: list[ExtractedCall] = []
        body = self.find_child_by_field(method_node, "body")
        if not body:
            return calls

        # Find all method invocations and object creations in the body
        call_types = {"method_invocation", "object_creation_expression"}
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
        caller_class: str,
    ) -> ExtractedCall | None:
        """Extract a single method call or constructor invocation."""
        callee_name = ""
        callee_qualifier = None
        is_method_call = False

        if call_node.type == "method_invocation":
            # Handle method invocation: obj.method() or method()
            is_method_call = True

            # Get method name
            name_node = self.find_child_by_field(call_node, "name")
            if name_node:
                callee_name = self.get_node_text(name_node, source)

            # Get object/qualifier (if present)
            obj_node = self.find_child_by_field(call_node, "object")
            if obj_node:
                callee_qualifier = self.get_node_text(obj_node, source)

        elif call_node.type == "object_creation_expression":
            # Handle constructor call: new ClassName()
            type_node = self.find_child_by_field(call_node, "type")
            if type_node:
                # Get the type name (may be simple or qualified)
                type_text = self.get_node_text(type_node, source)
                # Strip generic parameters for the callee name
                if "<" in type_text:
                    type_text = type_text.split("<")[0]
                callee_name = type_text
                # For constructor calls, we use "<init>" convention or just the class name
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

    def _get_method_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a method declaration."""
        name_node = self.find_child_by_field(node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    # =========================================================================
    # Private extraction helpers
    # =========================================================================

    def _extract_type(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a type definition (class, interface, enum, record)."""
        name = self._get_type_name(node, source)
        kind = self._get_type_kind(node)
        bases = self._get_bases(node, source)
        decorators = self._get_annotations(node, source)
        visibility = self._get_visibility(node, source)
        docstring = self._get_javadoc(node, source)

        return ExtractedType(
            name=name,
            kind=kind,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=docstring,
            bases=bases,
            decorators=decorators,
            is_async=False,
            visibility=visibility,
        )

    def _extract_method(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        """Extract a method declaration."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        decorators = self._get_annotations(node, source)
        visibility = self._get_visibility(node, source)
        parameters = self._extract_parameters(node, source)

        # Get return type
        return_type_node = self.find_child_by_field(node, "type")
        return_annotation = self.get_node_text(return_type_node, source) if return_type_node else None

        # Check modifiers
        is_static = self._has_modifier(node, source, "static")
        is_async = False  # Java doesn't have async in the same way

        docstring = self._get_javadoc(node, source)

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
            is_classmethod=False,
            is_property=False,
            visibility=visibility,
        )

    def _extract_constructor(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        """Extract a constructor declaration."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else class_name

        decorators = self._get_annotations(node, source)
        visibility = self._get_visibility(node, source)
        parameters = self._extract_parameters(node, source)
        docstring = self._get_javadoc(node, source)

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=docstring,
            parameters=parameters,
            return_annotation=None,  # Constructors don't have return types
            decorators=decorators,
            is_async=False,
            is_static=False,
            is_classmethod=False,
            is_property=False,
            visibility=visibility,
        )

    def _extract_import(self, node: tree_sitter.Node, source: bytes) -> ExtractedImport:
        """Extract an import declaration."""
        # Check for static import
        is_static = any(self.get_node_text(child, source) == "static" for child in node.children)

        # Get the full import path
        path_node = self.find_child_by_type(node, "scoped_identifier")
        if not path_node:
            path_node = self.find_child_by_type(node, "identifier")

        full_path = self.get_node_text(path_node, source) if path_node else ""

        # Check for wildcard
        is_wildcard = any(child.type == "asterisk" or self.get_node_text(child, source) == "*" for child in node.children)

        # Split into module and imported name
        if "." in full_path:
            parts = full_path.rsplit(".", 1)
            module = parts[0]
            names = [parts[1]] if not is_wildcard else ["*"]
        else:
            module = full_path
            names = ["*"] if is_wildcard else []

        return ExtractedImport(
            module=module,
            names=names,
            alias=None,
            line=self.get_line_start(node),
            is_from_import=is_static,
        )

    # =========================================================================
    # Utility helpers
    # =========================================================================

    def _get_type_name(self, node: tree_sitter.Node, source: bytes) -> str:
        """Get the name of a type declaration."""
        name_node = self.find_child_by_field(node, "name")
        return self.get_node_text(name_node, source) if name_node else ""

    def _get_type_kind(self, node: tree_sitter.Node) -> str:
        """Get the kind of type declaration."""
        kind_map = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "record",
            "annotation_type_declaration": "annotation",
        }
        return kind_map.get(node.type, "class")

    def _get_bases(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get extended/implemented types."""
        bases: list[str] = []

        # Handle extends
        superclass = self.find_child_by_field(node, "superclass")
        if superclass:
            for child in superclass.children:
                if child.type == "type_identifier":
                    bases.append(self.get_node_text(child, source))
                elif child.type == "generic_type":
                    bases.append(self.get_node_text(child, source))

        # Handle implements
        interfaces = self.find_child_by_field(node, "interfaces")
        if interfaces:
            for child in interfaces.children:
                if child.type == "type_identifier":
                    bases.append(self.get_node_text(child, source))
                elif child.type == "generic_type":
                    bases.append(self.get_node_text(child, source))
                elif child.type == "type_list":
                    for item in child.children:
                        if item.type in ("type_identifier", "generic_type"):
                            bases.append(self.get_node_text(item, source))

        return bases

    def _get_annotations(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get annotations from a declaration."""
        annotations: list[str] = []

        # Check for modifiers node which may contain annotations
        modifiers = self.find_child_by_type(node, "modifiers")
        if modifiers:
            for child in modifiers.children:
                if child.type in ("annotation", "marker_annotation"):
                    ann_text = self.get_node_text(child, source)
                    if ann_text.startswith("@"):
                        ann_text = ann_text[1:]
                    annotations.append(ann_text)

        # Also check direct children for annotations
        for child in node.children:
            if child.type in ("annotation", "marker_annotation"):
                ann_text = self.get_node_text(child, source)
                if ann_text.startswith("@"):
                    ann_text = ann_text[1:]
                annotations.append(ann_text)

        return annotations

    def _get_visibility(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Get visibility modifier (public, private, protected)."""
        modifiers = self.find_child_by_type(node, "modifiers")
        if modifiers:
            for child in modifiers.children:
                text = self.get_node_text(child, source)
                if text in ("public", "private", "protected"):
                    return text
        return None

    def _has_modifier(self, node: tree_sitter.Node, source: bytes, modifier: str) -> bool:
        """Check if a node has a specific modifier."""
        modifiers = self.find_child_by_type(node, "modifiers")
        if modifiers:
            for child in modifiers.children:
                if self.get_node_text(child, source) == modifier:
                    return True
        return False

    def _get_javadoc(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Extract Javadoc comment if present before the node."""
        # Look at previous siblings or parent's previous children
        # Tree-sitter typically puts comments as separate nodes
        # This is a simplified approach
        return None  # TODO: Implement Javadoc extraction if needed

    def _extract_parameters(self, node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract method parameters."""
        params: list[dict[str, Any]] = []

        params_node = self.find_child_by_field(node, "parameters")
        if not params_node:
            return params

        for child in params_node.children:
            if child.type == "formal_parameter":
                type_node = self.find_child_by_field(child, "type")
                name_node = self.find_child_by_field(child, "name")

                type_str = self.get_node_text(type_node, source) if type_node else None
                name = self.get_node_text(name_node, source) if name_node else ""

                # Check for varargs (...)
                dimensions = self.find_child_by_field(child, "dimensions")
                if dimensions:
                    type_str = f"{type_str}[]" if type_str else "[]"

                params.append(
                    {
                        "name": name,
                        "annotation": type_str,
                        "has_default": False,
                    }
                )
            elif child.type == "spread_parameter":
                # Varargs: Type... name
                type_node = self.find_child_by_field(child, "type")
                name_node = self.find_child_by_field(child, "name")

                type_str = self.get_node_text(type_node, source) if type_node else None
                name = self.get_node_text(name_node, source) if name_node else ""

                params.append(
                    {
                        "name": f"...{name}",
                        "annotation": type_str,
                        "has_default": False,
                    }
                )

        return params


# Register this extractor
register_extractor("java", JavaExtractor)
