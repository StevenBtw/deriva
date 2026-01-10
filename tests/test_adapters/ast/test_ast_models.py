"""Tests for adapters.ast.models module."""

from __future__ import annotations

from deriva.adapters.ast.models import (
    ExtractedImport,
    ExtractedMethod,
    ExtractedType,
)


class TestExtractedType:
    """Tests for ExtractedType dataclass."""

    def test_creates_with_required_fields(self):
        """Should create with required fields."""
        extracted = ExtractedType(
            name="MyClass",
            kind="class",
            line_start=10,
            line_end=50,
        )
        assert extracted.name == "MyClass"
        assert extracted.kind == "class"
        assert extracted.line_start == 10
        assert extracted.line_end == 50

    def test_has_optional_fields_with_defaults(self):
        """Should have default values for optional fields."""
        extracted = ExtractedType(
            name="Func",
            kind="function",
            line_start=1,
            line_end=5,
        )
        assert extracted.docstring is None
        assert extracted.bases == []
        assert extracted.decorators == []
        assert extracted.is_async is False

    def test_accepts_optional_fields(self):
        """Should accept optional field values."""
        extracted = ExtractedType(
            name="AsyncClass",
            kind="class",
            line_start=1,
            line_end=10,
            docstring="A class docstring",
            bases=["BaseClass"],
            decorators=["@dataclass"],
            is_async=True,
        )
        assert extracted.docstring == "A class docstring"
        assert extracted.bases == ["BaseClass"]
        assert extracted.decorators == ["@dataclass"]
        assert extracted.is_async is True


class TestExtractedMethod:
    """Tests for ExtractedMethod dataclass."""

    def test_creates_with_required_fields(self):
        """Should create with required fields."""
        method = ExtractedMethod(
            name="process",
            class_name="MyClass",
            line_start=20,
            line_end=30,
        )
        assert method.name == "process"
        assert method.class_name == "MyClass"

    def test_class_name_can_be_none(self):
        """Should allow None for top-level functions."""
        method = ExtractedMethod(
            name="standalone_func",
            class_name=None,
            line_start=1,
            line_end=10,
        )
        assert method.class_name is None

    def test_has_method_modifiers(self):
        """Should track method modifiers."""
        method = ExtractedMethod(
            name="my_property",
            class_name="MyClass",
            line_start=1,
            line_end=5,
            is_async=True,
            is_static=True,
            is_classmethod=False,
            is_property=True,
        )
        assert method.is_async is True
        assert method.is_static is True
        assert method.is_classmethod is False
        assert method.is_property is True


class TestExtractedImport:
    """Tests for ExtractedImport dataclass."""

    def test_creates_import_statement(self):
        """Should create import statement."""
        imp = ExtractedImport(
            module="os.path",
            names=["join", "exists"],
            is_from_import=True,
        )
        assert imp.module == "os.path"
        assert imp.names == ["join", "exists"]
        assert imp.is_from_import is True

    def test_creates_module_import(self):
        """Should create module import without names."""
        imp = ExtractedImport(
            module="json",
            names=[],
            is_from_import=False,
        )
        assert imp.module == "json"
        assert imp.names == []
        assert imp.is_from_import is False

    def test_tracks_alias(self):
        """Should track import alias."""
        imp = ExtractedImport(
            module="numpy",
            names=[],
            alias="np",
        )
        assert imp.alias == "np"
