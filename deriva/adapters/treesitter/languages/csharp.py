"""C# language extractor using tree-sitter."""

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
# C# Filter Constants
# =============================================================================

# .NET standard library namespaces
CSHARP_STDLIB = {
    # Core System namespaces
    "System",
    "System.Collections",
    "System.Collections.Generic",
    "System.Collections.Concurrent",
    "System.Collections.Specialized",
    "System.ComponentModel",
    "System.Configuration",
    "System.Data",
    "System.Diagnostics",
    "System.Drawing",
    "System.Dynamic",
    "System.Globalization",
    "System.IO",
    "System.Linq",
    "System.Net",
    "System.Net.Http",
    "System.Numerics",
    "System.Reflection",
    "System.Resources",
    "System.Runtime",
    "System.Runtime.CompilerServices",
    "System.Runtime.InteropServices",
    "System.Security",
    "System.Text",
    "System.Text.Json",
    "System.Text.RegularExpressions",
    "System.Threading",
    "System.Threading.Tasks",
    "System.Timers",
    "System.Xml",
    # Microsoft namespaces
    "Microsoft.Extensions",
    "Microsoft.Extensions.Configuration",
    "Microsoft.Extensions.DependencyInjection",
    "Microsoft.Extensions.Logging",
    "Microsoft.Extensions.Options",
    "Microsoft.AspNetCore",
    "Microsoft.EntityFrameworkCore",
    "Microsoft.CSharp",
    # Common third-party (often treated as standard)
    "Newtonsoft.Json",
}

# C# built-in methods and common methods to skip
CSHARP_BUILTINS = {
    # Object methods
    "ToString",
    "GetHashCode",
    "Equals",
    "GetType",
    "MemberwiseClone",
    "ReferenceEquals",
    # Common methods
    "Add",
    "Remove",
    "Contains",
    "Clear",
    "Count",
    "IndexOf",
    "Insert",
    "RemoveAt",
    "ToList",
    "ToArray",
    "ToDictionary",
    "ToHashSet",
    # String methods
    "Length",
    "Substring",
    "IndexOf",
    "LastIndexOf",
    "StartsWith",
    "EndsWith",
    "Trim",
    "TrimStart",
    "TrimEnd",
    "ToLower",
    "ToUpper",
    "Split",
    "Join",
    "Replace",
    "Contains",
    "IsNullOrEmpty",
    "IsNullOrWhiteSpace",
    "Format",
    "Concat",
    "Compare",
    "CompareTo",
    "PadLeft",
    "PadRight",
    # LINQ methods
    "Where",
    "Select",
    "SelectMany",
    "OrderBy",
    "OrderByDescending",
    "ThenBy",
    "ThenByDescending",
    "GroupBy",
    "Join",
    "GroupJoin",
    "First",
    "FirstOrDefault",
    "Last",
    "LastOrDefault",
    "Single",
    "SingleOrDefault",
    "Any",
    "All",
    "Count",
    "Sum",
    "Average",
    "Min",
    "Max",
    "Take",
    "Skip",
    "TakeWhile",
    "SkipWhile",
    "Distinct",
    "Union",
    "Intersect",
    "Except",
    "Concat",
    "Aggregate",
    "Zip",
    "ToLookup",
    # Async methods
    "GetAwaiter",
    "GetResult",
    "ConfigureAwait",
    "ContinueWith",
    "WhenAll",
    "WhenAny",
    "Run",
    "FromResult",
    "Delay",
    # IDisposable
    "Dispose",
    "Close",
    # Events
    "Invoke",
    "BeginInvoke",
    "EndInvoke",
    # Common static methods
    "Parse",
    "TryParse",
    "Create",
    "CreateInstance",
    "GetInstance",
    "Empty",
    "Default",
    # Console/Debug
    "WriteLine",
    "Write",
    "ReadLine",
    "Read",
    "Log",
    "Debug",
    "Trace",
}

# C# attributes (decorators)
CSHARP_DECORATOR_BUILTINS = {
    # Core attributes
    "Serializable",
    "NonSerialized",
    "Obsolete",
    "Conditional",
    "AttributeUsage",
    "Flags",
    "CLSCompliant",
    "ComVisible",
    # Compiler attributes
    "CallerMemberName",
    "CallerFilePath",
    "CallerLineNumber",
    "MethodImpl",
    "CompilerGenerated",
    "DebuggerStepThrough",
    "DebuggerDisplay",
    "DebuggerBrowsable",
    "DebuggerHidden",
    # Data annotations
    "Required",
    "StringLength",
    "MaxLength",
    "MinLength",
    "Range",
    "RegularExpression",
    "Compare",
    "EmailAddress",
    "Phone",
    "Url",
    "CreditCard",
    "DataType",
    "Display",
    "DisplayName",
    "DisplayFormat",
    "Key",
    "Editable",
    "ScaffoldColumn",
    "UIHint",
    # Entity Framework
    "Table",
    "Column",
    "Key",
    "ForeignKey",
    "InverseProperty",
    "NotMapped",
    "DatabaseGenerated",
    "Index",
    "MaxLength",
    "Required",
    "ConcurrencyCheck",
    "Timestamp",
    # ASP.NET Core
    "Route",
    "HttpGet",
    "HttpPost",
    "HttpPut",
    "HttpDelete",
    "HttpPatch",
    "FromBody",
    "FromQuery",
    "FromRoute",
    "FromHeader",
    "FromForm",
    "ApiController",
    "Controller",
    "Area",
    "Authorize",
    "AllowAnonymous",
    "ValidateAntiForgeryToken",
    "Produces",
    "Consumes",
    "ProducesResponseType",
    # Dependency Injection
    "Inject",
    "Service",
    "Singleton",
    "Scoped",
    "Transient",
    # Testing
    "TestClass",
    "TestMethod",
    "TestInitialize",
    "TestCleanup",
    "Fact",
    "Theory",
    "InlineData",
    "ClassData",
    "MemberData",
    "SetUp",
    "TearDown",
    "Test",
    "TestCase",
    "TestFixture",
    # JSON
    "JsonProperty",
    "JsonIgnore",
    "JsonConverter",
    "JsonPropertyName",
    "JsonInclude",
    "JsonExtensionData",
    # XML
    "XmlRoot",
    "XmlElement",
    "XmlAttribute",
    "XmlIgnore",
    "XmlArray",
}

# C# built-in types
CSHARP_BUILTIN_TYPES = {
    # Value types
    "int",
    "long",
    "short",
    "byte",
    "sbyte",
    "uint",
    "ulong",
    "ushort",
    "float",
    "double",
    "decimal",
    "bool",
    "char",
    "void",
    # Reference types
    "string",
    "object",
    "dynamic",
    # Nullable
    "Nullable",
    # System types
    "Int32",
    "Int64",
    "Int16",
    "Byte",
    "SByte",
    "UInt32",
    "UInt64",
    "UInt16",
    "Single",
    "Double",
    "Decimal",
    "Boolean",
    "Char",
    "String",
    "Object",
    "Void",
    "Guid",
    "DateTime",
    "DateTimeOffset",
    "TimeSpan",
    "DateOnly",
    "TimeOnly",
    # Collections
    "List",
    "Dictionary",
    "HashSet",
    "Queue",
    "Stack",
    "LinkedList",
    "SortedList",
    "SortedDictionary",
    "SortedSet",
    "ConcurrentDictionary",
    "ConcurrentQueue",
    "ConcurrentStack",
    "ConcurrentBag",
    "IEnumerable",
    "ICollection",
    "IList",
    "IDictionary",
    "ISet",
    "IReadOnlyList",
    "IReadOnlyCollection",
    "IReadOnlyDictionary",
    "Collection",
    "ReadOnlyCollection",
    "ObservableCollection",
    # Arrays
    "Array",
    # Task types
    "Task",
    "ValueTask",
    "IAsyncEnumerable",
    "IAsyncEnumerator",
    # Func/Action
    "Func",
    "Action",
    "Predicate",
    "Comparison",
    "Converter",
    "EventHandler",
    "Delegate",
    # Exceptions
    "Exception",
    "ArgumentException",
    "ArgumentNullException",
    "ArgumentOutOfRangeException",
    "InvalidOperationException",
    "NotImplementedException",
    "NotSupportedException",
    "NullReferenceException",
    "IndexOutOfRangeException",
    "KeyNotFoundException",
    "FormatException",
    # IO types
    "Stream",
    "MemoryStream",
    "FileStream",
    "StreamReader",
    "StreamWriter",
    "TextReader",
    "TextWriter",
    "BinaryReader",
    "BinaryWriter",
    # Others
    "StringBuilder",
    "Regex",
    "Match",
    "Group",
    "Capture",
    "Type",
    "Attribute",
    "Enum",
    # Generics
    "T",
    "TKey",
    "TValue",
    "TResult",
    "TSource",
    "TElement",
}

CSHARP_GENERIC_CONTAINERS = {
    "List",
    "Dictionary",
    "HashSet",
    "Queue",
    "Stack",
    "LinkedList",
    "SortedList",
    "SortedDictionary",
    "SortedSet",
    "IEnumerable",
    "ICollection",
    "IList",
    "IDictionary",
    "ISet",
    "IReadOnlyList",
    "IReadOnlyCollection",
    "IReadOnlyDictionary",
    "Task",
    "ValueTask",
    "Nullable",
    "Func",
    "Action",
    "Predicate",
    "Lazy",
    "IAsyncEnumerable",
    "IAsyncEnumerator",
}


class CSharpExtractor(LanguageExtractor):
    """Extractor for C# source code using tree-sitter-c-sharp."""

    @property
    def language_name(self) -> str:
        return "csharp"

    def get_filter_constants(self) -> FilterConstants:
        """Return C#-specific filter constants."""
        return FilterConstants(
            stdlib_modules=CSHARP_STDLIB,
            builtin_functions=CSHARP_BUILTINS,
            builtin_decorators=CSHARP_DECORATOR_BUILTINS,
            builtin_types=CSHARP_BUILTIN_TYPES,
            generic_containers=CSHARP_GENERIC_CONTAINERS,
        )

    def get_language(self) -> Any:
        """Return the tree-sitter C# language."""
        import tree_sitter_c_sharp

        return tree_sitter_c_sharp.language()

    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        """Extract type definitions (classes, interfaces, structs, enums, records)."""
        types: list[ExtractedType] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "enum_declaration",
            "record_declaration",
            "record_struct_declaration",
        }

        for node in self.walk_tree(root, type_nodes):
            types.append(self._extract_type(node, source))

        return types

    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        """Extract methods, constructors, and properties."""
        methods: list[ExtractedMethod] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "record_declaration",
            "record_struct_declaration",
        }

        for type_node in self.walk_tree(root, type_nodes):
            class_name = self._get_type_name(type_node, source)
            body = self.find_child_by_field(type_node, "body")
            if not body:
                # Records may have a different structure
                body = self.find_child_by_type(type_node, "declaration_list")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        methods.append(self._extract_method(child, source, class_name))
                    elif child.type == "constructor_declaration":
                        methods.append(self._extract_constructor(child, source, class_name))
                    elif child.type == "property_declaration":
                        methods.append(self._extract_property(child, source, class_name))

        return methods

    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        """Extract using directives."""
        imports: list[ExtractedImport] = []
        root = tree.root_node

        for node in self.walk_tree(root, {"using_directive"}):
            imports.append(self._extract_using(node, source))

        return imports

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        """Extract method and constructor calls from C# source code.

        Walks through all type declarations (class, interface, struct, record)
        and extracts calls made from methods and constructors.

        Returns:
            List of ExtractedCall objects representing method/constructor invocations.
        """
        calls: list[ExtractedCall] = []
        root = tree.root_node

        type_nodes = {
            "class_declaration",
            "interface_declaration",
            "struct_declaration",
            "record_declaration",
            "record_struct_declaration",
        }

        for type_node in self.walk_tree(root, type_nodes):
            class_name = self._get_type_name(type_node, source)
            body = self.find_child_by_field(type_node, "body")
            if not body:
                body = self.find_child_by_type(type_node, "declaration_list")

            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        name_node = self.find_child_by_field(child, "name")
                        method_name = self.get_node_text(name_node, source) if name_node else ""
                        calls.extend(self._extract_calls_from_body(child, source, method_name, class_name))
                    elif child.type == "constructor_declaration":
                        calls.extend(self._extract_calls_from_body(child, source, class_name, class_name))

        return calls

    def _extract_calls_from_body(
        self,
        method_node: tree_sitter.Node,
        source: bytes,
        caller_name: str,
        caller_class: str | None,
    ) -> list[ExtractedCall]:
        """Extract all calls from a method or constructor body."""
        calls: list[ExtractedCall] = []

        # Find the method body block
        body = self.find_child_by_field(method_node, "body")
        if not body:
            return calls

        # Walk the body looking for call expressions
        call_types = {"invocation_expression", "object_creation_expression"}

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
        """Extract a single call from an invocation or object creation expression."""
        if call_node.type == "invocation_expression":
            # Method call: obj.Method() or Method()
            callee_name = self._get_invocation_name(call_node, source)
            if not callee_name:
                return None

            # Try to determine the target class from member access
            callee_class = self._get_invocation_target_class(call_node, source)

            # Determine if this is a method call on an object
            is_method_call = callee_class is not None

            return ExtractedCall(
                caller_name=caller_name,
                caller_class=caller_class,
                callee_name=callee_name,
                callee_qualifier=callee_class,  # Object/class qualifier
                line=self.get_line_start(call_node),
                is_method_call=is_method_call,
            )

        elif call_node.type == "object_creation_expression":
            # Constructor call: new ClassName()
            type_node = self.find_child_by_field(call_node, "type")
            if not type_node:
                return None

            type_name = self._get_type_name_from_node(type_node, source)
            if not type_name:
                return None

            return ExtractedCall(
                caller_name=caller_name,
                caller_class=caller_class,
                callee_name=type_name,
                callee_qualifier=type_name,  # Constructor call uses type as qualifier
                line=self.get_line_start(call_node),
                is_method_call=True,  # Constructor calls are like method calls
            )

        return None

    def _get_invocation_name(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Get the method name from an invocation expression.

        Handles:
        - Simple calls: Method()
        - Member access: obj.Method()
        - Chained calls: obj.Method1().Method2()
        """
        func_node = self.find_child_by_field(node, "function")
        if not func_node:
            # Try first child
            if node.children:
                func_node = node.children[0]
            else:
                return None

        if func_node.type == "member_access_expression":
            # Get the method name (rightmost identifier)
            name_node = self.find_child_by_field(func_node, "name")
            if name_node:
                return self.get_node_text(name_node, source)
        elif func_node.type == "identifier":
            return self.get_node_text(func_node, source)
        elif func_node.type == "generic_name":
            # Generic method: Method<T>()
            name_node = self.find_child_by_type(func_node, "identifier")
            if name_node:
                return self.get_node_text(name_node, source)

        return None

    def _get_invocation_target_class(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Try to determine the target class from an invocation.

        For member access like `obj.Method()`, returns the object/type name.
        Returns None if it's a simple function call.
        """
        func_node = self.find_child_by_field(node, "function")
        if not func_node:
            return None

        if func_node.type == "member_access_expression":
            expr_node = self.find_child_by_field(func_node, "expression")
            if expr_node:
                if expr_node.type == "identifier":
                    # Could be object name or class name (for static calls)
                    return self.get_node_text(expr_node, source)
                elif expr_node.type == "this_expression":
                    return None  # Call on self
                elif expr_node.type == "base_expression":
                    return None  # Call on base class

        return None

    def _get_type_name_from_node(self, type_node: tree_sitter.Node, source: bytes) -> str | None:
        """Extract type name from a type node (for object creation)."""
        if type_node.type == "identifier":
            return self.get_node_text(type_node, source)
        elif type_node.type == "qualified_name":
            # Full namespace path - get the last part
            parts = self.get_node_text(type_node, source).split(".")
            return parts[-1] if parts else None
        elif type_node.type == "generic_name":
            # Generic type: List<T> - get base name
            name_node = self.find_child_by_type(type_node, "identifier")
            if name_node:
                return self.get_node_text(name_node, source)

        return None

    # =========================================================================
    # Private extraction helpers
    # =========================================================================

    def _extract_type(self, node: tree_sitter.Node, source: bytes) -> ExtractedType:
        """Extract a type definition."""
        name = self._get_type_name(node, source)
        kind = self._get_type_kind(node)
        bases = self._get_bases(node, source)
        decorators = self._get_attributes(node, source)
        visibility = self._get_visibility(node, source)

        return ExtractedType(
            name=name,
            kind=kind,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            bases=bases,
            decorators=decorators,
            is_async=False,
            visibility=visibility,
        )

    def _extract_method(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        """Extract a method declaration."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        decorators = self._get_attributes(node, source)
        visibility = self._get_visibility(node, source)
        parameters = self._extract_parameters(node, source)

        # Get return type
        return_type_node = self.find_child_by_field(node, "type")
        return_annotation = self.get_node_text(return_type_node, source) if return_type_node else None

        # Check modifiers
        is_static = self._has_modifier(node, source, "static")
        is_async = self._has_modifier(node, source, "async")

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
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

        decorators = self._get_attributes(node, source)
        visibility = self._get_visibility(node, source)
        parameters = self._extract_parameters(node, source)

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            parameters=parameters,
            return_annotation=None,
            decorators=decorators,
            is_async=False,
            is_static=False,
            is_classmethod=False,
            is_property=False,
            visibility=visibility,
        )

    def _extract_property(self, node: tree_sitter.Node, source: bytes, class_name: str) -> ExtractedMethod:
        """Extract a property declaration."""
        name_node = self.find_child_by_field(node, "name")
        name = self.get_node_text(name_node, source) if name_node else ""

        decorators = self._get_attributes(node, source)
        visibility = self._get_visibility(node, source)

        # Get property type
        type_node = self.find_child_by_field(node, "type")
        return_annotation = self.get_node_text(type_node, source) if type_node else None

        is_static = self._has_modifier(node, source, "static")

        return ExtractedMethod(
            name=name,
            class_name=class_name,
            line_start=self.get_line_start(node),
            line_end=self.get_line_end(node),
            docstring=None,
            parameters=[],
            return_annotation=return_annotation,
            decorators=decorators,
            is_async=False,
            is_static=is_static,
            is_classmethod=False,
            is_property=True,
            visibility=visibility,
        )

    def _extract_using(self, node: tree_sitter.Node, source: bytes) -> ExtractedImport:
        """Extract a using directive."""
        # Check for alias
        alias_node = self.find_child_by_field(node, "alias")
        alias = self.get_node_text(alias_node, source) if alias_node else None

        # Get namespace
        name_node = self.find_child_by_field(node, "name")
        if not name_node:
            # Try qualified_name or identifier
            name_node = self.find_child_by_type(node, "qualified_name")
            if not name_node:
                name_node = self.find_child_by_type(node, "identifier")

        module = self.get_node_text(name_node, source) if name_node else ""

        # Check for static using
        is_static = any(self.get_node_text(child, source) == "static" for child in node.children)

        return ExtractedImport(
            module=module,
            names=[],
            alias=alias,
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
            "struct_declaration": "struct",
            "enum_declaration": "enum",
            "record_declaration": "record",
            "record_struct_declaration": "record",
        }
        return kind_map.get(node.type, "class")

    def _get_bases(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get base types from base_list."""
        bases: list[str] = []

        base_list = self.find_child_by_field(node, "bases")
        if not base_list:
            base_list = self.find_child_by_type(node, "base_list")

        if base_list:
            for child in base_list.children:
                if child.type in (
                    "identifier",
                    "qualified_name",
                    "generic_name",
                    "simple_base_type",
                ):
                    bases.append(self.get_node_text(child, source))

        return bases

    def _get_attributes(self, node: tree_sitter.Node, source: bytes) -> list[str]:
        """Get attributes from a declaration."""
        attributes: list[str] = []

        for child in node.children:
            if child.type == "attribute_list":
                for attr in child.children:
                    if attr.type == "attribute":
                        attr_text = self.get_node_text(attr, source)
                        attributes.append(attr_text)

        return attributes

    def _get_visibility(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Get visibility modifier."""
        visibility_keywords = {"public", "private", "protected", "internal"}

        for child in node.children:
            if child.type == "modifier":
                text = self.get_node_text(child, source)
                if text in visibility_keywords:
                    return text

        return None

    def _has_modifier(self, node: tree_sitter.Node, source: bytes, modifier: str) -> bool:
        """Check if a node has a specific modifier."""
        for child in node.children:
            if child.type == "modifier":
                if self.get_node_text(child, source) == modifier:
                    return True
        return False

    def _extract_parameters(self, node: tree_sitter.Node, source: bytes) -> list[dict[str, Any]]:
        """Extract method parameters."""
        params: list[dict[str, Any]] = []

        params_node = self.find_child_by_field(node, "parameters")
        if not params_node:
            params_node = self.find_child_by_type(node, "parameter_list")

        if not params_node:
            return params

        for child in params_node.children:
            if child.type == "parameter":
                type_node = self.find_child_by_field(child, "type")
                name_node = self.find_child_by_field(child, "name")

                type_str = self.get_node_text(type_node, source) if type_node else None
                name = self.get_node_text(name_node, source) if name_node else ""

                # Check for default value
                default_node = self.find_child_by_field(child, "default")
                has_default = default_node is not None

                # Check for params keyword (varargs)
                is_params = any(self.get_node_text(c, source) == "params" for c in child.children)
                if is_params:
                    name = f"params {name}"

                # Check for ref/out/in
                for modifier in ("ref", "out", "in"):
                    if any(self.get_node_text(c, source) == modifier for c in child.children):
                        name = f"{modifier} {name}"
                        break

                params.append(
                    {
                        "name": name,
                        "annotation": type_str,
                        "has_default": has_default,
                    }
                )

        return params


# Register this extractor
register_extractor("csharp", CSharpExtractor)
