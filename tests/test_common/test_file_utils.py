"""Tests for common.file_utils module."""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deriva.common.file_utils import (
    create_pipeline_result,
    read_file_with_encoding,
)
from deriva.common.types import LLMDetails


class TestReadFileWithEncoding:
    """Tests for read_file_with_encoding function."""

    def test_reads_utf8_file(self):
        """Should read UTF-8 encoded file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello, World!")
            f.flush()
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == "Hello, World!"
        finally:
            path.unlink()

    def test_reads_utf8_with_bom(self):
        """Should read UTF-8 file with BOM and strip the BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write UTF-8 BOM followed by content
            f.write(b"\xef\xbb\xbfHello, World!")
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == "Hello, World!"
            assert not content.startswith("\ufeff")  # BOM should be stripped
        finally:
            path.unlink()

    def test_reads_utf16_le_with_bom(self):
        """Should read UTF-16 LE file with BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write UTF-16 LE BOM followed by content
            content_bytes = "Hello, World!".encode("utf-16-le")
            f.write(b"\xff\xfe" + content_bytes)
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == "Hello, World!"
        finally:
            path.unlink()

    def test_reads_utf16_be_with_bom(self):
        """Should read UTF-16 BE file with BOM."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write UTF-16 BE BOM followed by content
            content_bytes = "Hello, World!".encode("utf-16-be")
            f.write(b"\xfe\xff" + content_bytes)
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == "Hello, World!"
        finally:
            path.unlink()

    def test_reads_latin1_fallback(self):
        """Should fall back to Latin-1 for non-UTF-8 bytes."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write bytes that are valid Latin-1 but not UTF-8
            f.write(b"Hello \xe9")  # \xe9 is 'é' in Latin-1
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content is not None
            assert "Hello" in content
        finally:
            path.unlink()

    def test_returns_none_for_nonexistent_file(self):
        """Should return None for nonexistent file."""
        path = Path("/nonexistent/path/that/does/not/exist.txt")

        content = read_file_with_encoding(path)

        assert content is None

    def test_reads_empty_file(self):
        """Should read empty file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == ""
        finally:
            path.unlink()

    def test_reads_multiline_content(self):
        """Should read multiline content correctly."""
        expected = "Line 1\nLine 2\nLine 3"
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            # Write in binary mode to preserve exact line endings
            f.write(expected.encode("utf-8"))
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == expected
        finally:
            path.unlink()

    def test_reads_unicode_characters(self):
        """Should read files with various Unicode characters."""
        expected = "Hello, 世界! 🌍 Привет мир"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(expected)
            path = Path(f.name)

        try:
            content = read_file_with_encoding(path)
            assert content == expected
        finally:
            path.unlink()


class TestCreatePipelineResult:
    """Tests for create_pipeline_result function."""

    def test_creates_basic_result(self):
        """Should create basic pipeline result with required fields."""
        result = create_pipeline_result(stage="extraction")

        assert result["success"] is True
        assert result["stage"] == "extraction"
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["stats"] == {}
        assert result["elements"] == []
        assert result["relationships"] == []
        assert "timestamp" in result
        assert "duration_ms" in result

    def test_creates_failure_result(self):
        """Should create failure result with errors."""
        errors = ["Error 1", "Error 2"]
        result = create_pipeline_result(stage="extraction", success=False, errors=errors)

        assert result["success"] is False
        assert result["errors"] == errors

    def test_includes_elements_and_relationships(self):
        """Should include elements and relationships."""
        elements = [{"id": "elem1"}, {"id": "elem2"}]
        relationships = [{"source": "elem1", "target": "elem2"}]

        result = create_pipeline_result(
            stage="derivation",
            elements=elements,
            relationships=relationships,
        )

        assert result["elements"] == elements
        assert result["relationships"] == relationships

    def test_includes_warnings(self):
        """Should include warnings."""
        warnings = ["Warning 1", "Warning 2"]
        result = create_pipeline_result(stage="validation", warnings=warnings)

        assert result["warnings"] == warnings

    def test_includes_stats(self):
        """Should include statistics."""
        stats = {"nodes_created": 10, "edges_created": 5}
        result = create_pipeline_result(stage="extraction", stats=stats)

        assert result["stats"] == stats

    def test_includes_llm_details(self):
        """Should include LLM details when provided."""
        llm_details: LLMDetails = {"tokens_in": 100, "tokens_out": 50}
        result = create_pipeline_result(stage="extraction", llm_details=llm_details)

        assert "llm_details" in result
        assert result["llm_details"] == llm_details

    def test_excludes_llm_details_when_not_provided(self):
        """Should not include llm_details key when not provided."""
        result = create_pipeline_result(stage="extraction")

        assert "llm_details" not in result

    def test_includes_issues(self):
        """Should include issues when provided."""
        issues = [{"type": "warning", "message": "Something is wrong"}]
        result = create_pipeline_result(stage="validation", issues=issues)

        assert "issues" in result
        assert result["issues"] == issues

    def test_excludes_issues_when_not_provided(self):
        """Should not include issues key when not provided."""
        result = create_pipeline_result(stage="extraction")

        assert "issues" not in result

    def test_calculates_duration(self):
        """Should calculate duration from start_time."""
        import time

        start = datetime.now(UTC)
        time.sleep(0.01)  # Small delay
        result = create_pipeline_result(stage="extraction", start_time=start)

        assert result["duration_ms"] >= 10

    def test_duration_zero_without_start_time(self):
        """Should have zero duration without start_time."""
        result = create_pipeline_result(stage="extraction")

        assert result["duration_ms"] == 0

    def test_timestamp_is_iso_format(self):
        """Should have ISO format timestamp."""
        result = create_pipeline_result(stage="extraction")

        # Should be ISO format with Z suffix
        assert result["timestamp"].endswith("Z")
        assert "T" in result["timestamp"]

    def test_different_stages(self):
        """Should accept different stage values."""
        extraction = create_pipeline_result(stage="extraction")
        derivation = create_pipeline_result(stage="derivation")
        validation = create_pipeline_result(stage="validation")

        assert extraction["stage"] == "extraction"
        assert derivation["stage"] == "derivation"
        assert validation["stage"] == "validation"


class TestLongPath:
    """Windows opens a path over 260 characters only in its extended form when long paths are off in the registry."""

    @pytest.mark.skipif(sys.platform != "win32", reason="the extended form is Windows only")
    def test_a_windows_path_gets_the_extended_form_once(self):
        from deriva.common.file_utils import long_path

        local = long_path(Path("C:/work/repo"))
        unc = long_path(Path("//server/share/repo"))

        assert str(local) == r"\\?\C:\work\repo"
        assert str(unc) == r"\\?\UNC\server\share\repo"
        assert long_path(local) == local

    @pytest.mark.skipif(sys.platform == "win32", reason="other systems have no such limit")
    def test_other_systems_keep_the_path(self):
        from deriva.common.file_utils import long_path

        assert long_path(Path("/work/repo")) == Path("/work/repo")

    def test_a_file_deeper_than_260_characters_is_read(self, tmp_path):
        from deriva.common.file_utils import long_path

        folder = tmp_path.joinpath(*["nested-folder-name"] * 16)
        long_path(folder).mkdir(parents=True)
        file = folder / "schema.xsd"
        long_path(file).write_text("<schema/>", encoding="utf-8")

        assert len(str(file)) > 260
        assert read_file_with_encoding(file) == "<schema/>"

    def test_a_walk_from_the_extended_root_lists_the_same_relative_paths(self, tmp_path):
        from deriva.common.file_utils import long_path
        from deriva.modules.extraction.directory import extract_directories
        from deriva.modules.extraction.file import extract_files
        from deriva.services.extraction import list_repo_files

        (tmp_path / "src" / "pkg").mkdir(parents=True)
        (tmp_path / "src" / "pkg" / "app.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "README.md").write_text("# r", encoding="utf-8")
        root = long_path(tmp_path)

        def stable(data):
            """Ids, labels and properties, without the time each was written."""
            drop = {"extracted_at", "created_at"}
            return {kind: [{**row, "properties": {k: v for k, v in row["properties"].items() if k not in drop}} for row in rows] for kind, rows in data.items()}

        assert list_repo_files(root, []) == list_repo_files(tmp_path, [])
        for extract in (extract_directories, extract_files):
            plain, extended = extract(str(tmp_path), "repo", excluded_dirs=[]), extract(str(root), "repo", excluded_dirs=[])
            assert stable(extended["data"]) == stable(plain["data"]) and plain["data"]["nodes"]


class TestDescribeOsError:
    """An OS error without its file name: messages name the repository-relative path themselves."""

    def test_errno_and_reason_without_the_path(self):
        from deriva.common.file_utils import describe_os_error

        assert describe_os_error(PermissionError(13, "Permission denied", "C:/work/repo/a.py")) == "[Errno 13] Permission denied"

    def test_an_error_without_a_code_keeps_its_text(self):
        from deriva.common.file_utils import describe_os_error

        assert describe_os_error(ValueError("bad bytes")) == "bad bytes"
