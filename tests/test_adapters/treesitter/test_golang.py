"""The Go tree-sitter extractor: types (struct, interface, alias, defined types), functions and methods (the receiver's
type is the class), imports (path and alias) and calls, read from the syntax tree."""

from __future__ import annotations

import pytest
import tree_sitter

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.golang import GoExtractor

SOURCE = """package shop

import (
    "context"
    pb "example.com/shop/genproto"
    "net/http"
)

// Cart holds the items of one user.
type Cart struct {
    Base
    *Logger
    ID    string
    Items []Item
}

type Store interface {
    Reader
    Get(ctx context.Context, id string) (*Cart, error)
}

type ID = string

type Handler func(w http.ResponseWriter, r *http.Request)

type (
    total int
)

// Add puts an item in the cart.
func (c *Cart) Add(item Item) error {
    c.Items = append(c.Items, item)
    return validate(item)
}

func (s store[T]) find(id string) {}

func NewCart[T any](id string, names ...string) *Cart {
    pb.Register(id)
    return &Cart{ID: id}
}
"""


@pytest.fixture
def extractor():
    return GoExtractor()


@pytest.fixture
def tree(extractor):
    raw_language: object = extractor.get_language()
    parser = tree_sitter.Parser(tree_sitter.Language(raw_language))
    return parser.parse(SOURCE.encode("utf-8"))


def test_the_extractor_is_registered_as_golang_the_subtype_go_files_carry():
    assert isinstance(get_extractor("golang"), GoExtractor)
    assert GoExtractor().language_name == "golang"


def test_types_are_structs_interfaces_aliases_and_defined_types_with_embedded_types_as_bases(extractor, tree):
    types = {t.name: t for t in extractor.extract_types(tree, SOURCE.encode("utf-8"))}

    assert sorted(types) == ["Cart", "Handler", "ID", "Store", "total"]
    assert (types["Cart"].kind, types["Store"].kind, types["ID"].kind, types["Handler"].kind) == ("struct", "interface", "type_alias", "type")
    assert types["Cart"].bases == ["Base", "Logger"] and types["Store"].bases == ["Reader"]
    assert types["Cart"].docstring == "Cart holds the items of one user."
    assert (types["Cart"].visibility, types["total"].visibility) == ("public", "private")
    assert (types["Cart"].line_start, types["Cart"].line_end) == (10, 15)


def test_methods_name_their_receiver_type_and_functions_have_none(extractor, tree):
    methods = {m.name: m for m in extractor.extract_methods(tree, SOURCE.encode("utf-8"))}

    assert sorted(methods) == ["Add", "NewCart", "find"]
    assert (methods["Add"].class_name, methods["find"].class_name, methods["NewCart"].class_name) == ("Cart", "store", None)
    assert methods["Add"].docstring == "Add puts an item in the cart." and methods["Add"].return_annotation == "error"
    assert methods["NewCart"].parameters == [{"name": "id", "annotation": "string", "has_default": False}, {"name": "...names", "annotation": "string", "has_default": False}]
    assert (methods["NewCart"].visibility, methods["find"].visibility) == ("public", "private")


def test_imports_keep_their_path_and_alias(extractor, tree):
    imports = extractor.extract_imports(tree, SOURCE.encode("utf-8"))

    assert [(i.module, i.alias) for i in imports] == [("context", None), ("example.com/shop/genproto", "pb"), ("net/http", None)]
    assert all(i.line > 0 for i in imports)


def test_calls_name_the_caller_and_the_qualifier(extractor, tree):
    calls = {(c.caller_name, c.callee_name): c for c in extractor.extract_calls(tree, SOURCE.encode("utf-8"))}

    assert set(calls) == {("Add", "append"), ("Add", "validate"), ("NewCart", "Register")}
    assert calls[("NewCart", "Register")].callee_qualifier == "pb" and calls[("NewCart", "Register")].is_method_call
    assert calls[("Add", "validate")].caller_class == "Cart" and not calls[("Add", "validate")].is_method_call


def test_the_standard_library_and_builtins_are_filter_constants(extractor):
    constants = extractor.get_filter_constants()

    assert {"context", "net/http", "fmt"} <= constants.stdlib_modules
    assert {"append", "len", "make"} <= constants.builtin_functions
    assert {"string", "error", "int"} <= constants.builtin_types


def test_the_manager_reads_a_go_file_by_its_extension():
    manager = TreeSitterManager()

    assert "golang" in manager.get_supported_languages()
    assert sorted(t.name for t in manager.extract_types(SOURCE, file_path="shop/cart.go")) == ["Cart", "Handler", "ID", "Store", "total"]


GENERICS = """package p

type Number interface { int | float64 }
type Approx interface { ~int }
type RW interface { Reader[T]; io.Writer; Closer }
type Box[T any] struct { Base[T]; *Other }

func f() {} // trailing
func g() {
	handlers[0]()
	makeThing[int]()
	pkg.Make[int]()
}
"""


def _parse(extractor: GoExtractor, text: str) -> tree_sitter.Tree:
    raw_language: object = extractor.get_language()
    return tree_sitter.Parser(tree_sitter.Language(raw_language)).parse(text.encode("utf-8"))


def test_a_constraint_s_terms_are_no_bases_and_a_generic_base_is_named_without_its_arguments(extractor):
    types = {t.name: t for t in extractor.extract_types(_parse(extractor, GENERICS), GENERICS.encode("utf-8"))}

    assert (types["Number"].bases, types["Approx"].bases) == ([], [])
    assert types["RW"].bases == ["Reader", "io.Writer", "Closer"]
    assert types["Box"].bases == ["Base", "Other"]


def test_a_comment_that_ends_the_line_before_is_no_doc_comment(extractor):
    methods = {m.name: m for m in extractor.extract_methods(_parse(extractor, GENERICS), GENERICS.encode("utf-8"))}

    assert methods["g"].docstring is None


def test_a_call_through_an_index_or_with_type_arguments_names_its_function(extractor):
    calls = [(c.callee_name, c.callee_qualifier) for c in extractor.extract_calls(_parse(extractor, GENERICS), GENERICS.encode("utf-8")) if c.caller_name == "g"]

    assert calls == [("handlers", None), ("makeThing", None), ("Make", "pkg")]
