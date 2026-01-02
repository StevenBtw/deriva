"""Tests for adapters.graph.models module."""

from __future__ import annotations

from datetime import datetime

import pytest

from deriva.adapters.graph.models import (
    BusinessConceptNode,
    DirectoryNode,
    ExternalDependencyNode,
    FileNode,
    MethodNode,
    ModuleNode,
    RepositoryNode,
    ServiceNode,
    TechnologyNode,
    TestNode,
    TypeDefinitionNode,
    normalize_path,
)


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_forward_slash_path(self):
        """Should preserve forward slash paths."""
        result = normalize_path("src/utils/helpers.py")

        assert result == "src/utils/helpers.py"

    def test_backslash_path_converted(self):
        """Should convert backslashes to forward slashes."""
        result = normalize_path("src\\utils\\helpers.py")

        assert result == "src/utils/helpers.py"

    def test_mixed_slashes(self):
        """Should handle mixed slashes."""
        result = normalize_path("src/utils\\helpers.py")

        assert result == "src/utils/helpers.py"

    def test_strips_leading_slash(self):
        """Should strip leading slashes."""
        result = normalize_path("/src/main.py")

        assert result == "src/main.py"

    def test_strips_trailing_slash(self):
        """Should strip trailing slashes."""
        result = normalize_path("src/utils/")

        assert result == "src/utils"

    def test_empty_path(self):
        """Should handle empty path."""
        result = normalize_path("")

        assert result == ""

    def test_dot_path(self):
        """Should handle dot path."""
        result = normalize_path(".")

        assert result == ""

    def test_with_repo_name_prefix(self):
        """Should add repo name prefix when provided."""
        result = normalize_path("src/main.py", repo_name="myrepo")

        assert result == "myrepo/src/main.py"

    def test_removes_existing_repo_prefix(self):
        """Should remove and re-add repo prefix."""
        result = normalize_path("myrepo/src/main.py", repo_name="myrepo")

        assert result == "myrepo/src/main.py"

    def test_empty_path_with_repo_name(self):
        """Should return repo name for empty path."""
        result = normalize_path("", repo_name="myrepo")

        assert result == "myrepo"


class TestRepositoryNode:
    """Tests for RepositoryNode dataclass."""

    def test_basic_creation(self):
        """Should create repository node."""
        node = RepositoryNode(
            name="myproject",
            url="https://github.com/user/myproject.git",
            created_at=datetime(2024, 1, 15),
        )

        assert node.name == "myproject"
        assert node.url == "https://github.com/user/myproject.git"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = RepositoryNode(
            name="myproject",
            url="https://example.com/repo.git",
            created_at=datetime.now(),
        )

        assert node.generate_id() == "Repository_myproject"

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = RepositoryNode(
            name="myproject",
            url="https://example.com/repo.git",
            created_at=datetime.now(),
            branch="main",
            commit="abc123",
            description="Test repo",
        )

        d = node.to_dict()

        assert d["repoName"] == "myproject"
        assert d["url"] == "https://example.com/repo.git"
        assert d["branch"] == "main"
        assert d["commit"] == "abc123"
        assert d["description"] == "Test repo"
        assert d["type"] == "Repository"
        assert d["confidence"] == 1.0

    def test_optional_fields_default(self):
        """Should have default values for optional fields."""
        node = RepositoryNode(
            name="myproject",
            url="https://example.com/repo.git",
            created_at=datetime.now(),
        )

        assert node.branch is None
        assert node.commit is None
        assert node.description is None
        assert node.confidence == 1.0


class TestDirectoryNode:
    """Tests for DirectoryNode dataclass."""

    def test_basic_creation(self):
        """Should create directory node."""
        node = DirectoryNode(
            name="src",
            path="src",
            repository_name="myrepo",
        )

        assert node.name == "src"
        assert node.path == "src"
        assert node.repository_name == "myrepo"

    def test_generate_id(self):
        """Should generate unique ID from path."""
        node = DirectoryNode(
            name="helpers",
            path="src/utils/helpers",
            repository_name="myrepo",
        )

        assert node.generate_id() == "Directory_myrepo_src_utils_helpers"

    def test_generate_id_handles_slashes(self):
        """Should replace slashes in ID."""
        node = DirectoryNode(
            name="deep",
            path="a/b/c/d",
            repository_name="repo",
        )

        node_id = node.generate_id()
        assert "/" not in node_id
        assert "\\" not in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = DirectoryNode(
            name="utils",
            path="src/utils",
            repository_name="myrepo",
            confidence=0.9,
        )

        d = node.to_dict()

        assert d["name"] == "utils"
        assert "utils" in d["path"]
        assert d["type"] == "Directory"
        assert d["confidence"] == 0.9


class TestFileNode:
    """Tests for FileNode dataclass."""

    def test_basic_creation(self):
        """Should create file node."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            extension=".py",
            file_type="source",
            subtype="python",
        )

        assert node.name == "main.py"
        assert node.extension == ".py"
        assert node.file_type == "source"
        assert node.subtype == "python"

    def test_generate_id(self):
        """Should generate unique ID from path."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            extension=".py",
            file_type="source",
            subtype="python",
        )

        assert node.generate_id() == "File_myrepo_src_main.py"

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            extension=".py",
            file_type="source",
            subtype="python",
            size_bytes=1024,
        )

        d = node.to_dict()

        assert d["name"] == "main.py"
        assert d["extension"] == ".py"
        assert d["fileType"] == "source"
        assert d["subtype"] == "python"
        assert d["sizeBytes"] == 1024
        assert d["type"] == "File"


class TestModuleNode:
    """Tests for ModuleNode dataclass."""

    def test_basic_creation(self):
        """Should create module node."""
        node = ModuleNode(
            name="utils",
            paths=["src/utils", "src/helpers"],
            repository_name="myrepo",
        )

        assert node.name == "utils"
        assert len(node.paths) == 2

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ModuleNode(
            name="core",
            paths=["src/core"],
            repository_name="myrepo",
        )

        assert node.generate_id() == "Module_myrepo_core"

    def test_to_dict(self):
        """Should convert to dictionary with normalized paths."""
        node = ModuleNode(
            name="utils",
            paths=["src\\utils", "src/helpers"],
            repository_name="myrepo",
            description="Utility modules",
        )

        d = node.to_dict()

        assert d["name"] == "utils"
        assert d["description"] == "Utility modules"
        assert d["type"] == "Module"


class TestBusinessConceptNode:
    """Tests for BusinessConceptNode dataclass."""

    def test_basic_creation(self):
        """Should create business concept node."""
        node = BusinessConceptNode(
            name="User Authentication",
            description="Handles user login and authentication",
            repository_name="myrepo",
        )

        assert node.name == "User Authentication"
        assert node.description == "Handles user login and authentication"

    def test_generate_id(self):
        """Should generate safe ID from name."""
        node = BusinessConceptNode(
            name="User Auth",
            description="Auth",
            repository_name="myrepo",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "User" in node_id or "user" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = BusinessConceptNode(
            name="Payment Processing",
            description="Handles payments",
            repository_name="myrepo",
            source_files=["payment.py"],
        )

        d = node.to_dict()

        assert d["name"] == "Payment Processing"
        assert d["description"] == "Handles payments"
        assert d["type"] == "BusinessConcept"


class TestTechnologyNode:
    """Tests for TechnologyNode dataclass."""

    def test_basic_creation(self):
        """Should create technology node."""
        node = TechnologyNode(
            name="Python",
            category="language",
            repository_name="myrepo",
        )

        assert node.name == "Python"
        assert node.category == "language"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = TechnologyNode(
            name="FastAPI",
            category="framework",
            repository_name="myrepo",
        )

        assert "myrepo" in node.generate_id()
        assert "FastAPI" in node.generate_id()

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TechnologyNode(
            name="PostgreSQL",
            category="database",
            repository_name="myrepo",
            version="14",
        )

        d = node.to_dict()

        assert d["name"] == "PostgreSQL"
        assert d["category"] == "database"
        assert d["version"] == "14"
        assert d["type"] == "Technology"


class TestTypeDefinitionNode:
    """Tests for TypeDefinitionNode dataclass."""

    def test_basic_creation(self):
        """Should create type definition node."""
        node = TypeDefinitionNode(
            name="UserModel",
            kind="class",
            repository_name="myrepo",
            file_path="src/models/user.py",
        )

        assert node.name == "UserModel"
        assert node.kind == "class"

    def test_generate_id(self):
        """Should generate unique ID from path and name."""
        node = TypeDefinitionNode(
            name="UserModel",
            kind="class",
            repository_name="myrepo",
            file_path="src/models/user.py",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "UserModel" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TypeDefinitionNode(
            name="UserModel",
            kind="class",
            repository_name="myrepo",
            file_path="src/models/user.py",
            code_snippet="class UserModel:",
        )

        d = node.to_dict()

        assert d["name"] == "UserModel"
        assert d["kind"] == "class"
        assert d["codeSnippet"] == "class UserModel:"
        assert d["type"] == "TypeDefinition"


class TestMethodNode:
    """Tests for MethodNode dataclass."""

    def test_basic_creation(self):
        """Should create method node."""
        node = MethodNode(
            name="get_user",
            repository_name="myrepo",
            file_path="src/api.py",
        )

        assert node.name == "get_user"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = MethodNode(
            name="process_data",
            repository_name="myrepo",
            file_path="src/processor.py",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "process_data" in node_id

    def test_to_dict_with_parent(self):
        """Should include parent class in dictionary."""
        node = MethodNode(
            name="save",
            repository_name="myrepo",
            file_path="src/model.py",
            parent_class="UserModel",
        )

        d = node.to_dict()

        assert d["name"] == "save"
        assert d["parentClass"] == "UserModel"
        assert d["type"] == "Method"


class TestTestNode:
    """Tests for TestNode dataclass."""

    def test_basic_creation(self):
        """Should create test node."""
        node = TestNode(
            name="test_user_creation",
            test_type="unit",
            repository_name="myrepo",
            file_path="tests/test_user.py",
        )

        assert node.name == "test_user_creation"
        assert node.test_type == "unit"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = TestNode(
            name="test_api",
            test_type="integration",
            repository_name="myrepo",
            file_path="tests/test_api.py",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "test_api" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TestNode(
            name="test_login",
            test_type="unit",
            repository_name="myrepo",
            file_path="tests/test_auth.py",
            tested_component="auth.login",
        )

        d = node.to_dict()

        assert d["name"] == "test_login"
        assert d["testType"] == "unit"
        assert d["testedComponent"] == "auth.login"
        assert d["type"] == "Test"


class TestExternalDependencyNode:
    """Tests for ExternalDependencyNode dataclass."""

    def test_basic_creation(self):
        """Should create external dependency node."""
        node = ExternalDependencyNode(
            name="requests",
            version="2.28.0",
            repository_name="myrepo",
        )

        assert node.name == "requests"
        assert node.version == "2.28.0"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ExternalDependencyNode(
            name="django",
            version="4.0",
            repository_name="myrepo",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "django" in node_id.lower()

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = ExternalDependencyNode(
            name="numpy",
            version="1.24.0",
            repository_name="myrepo",
            source="requirements.txt",
        )

        d = node.to_dict()

        assert d["name"] == "numpy"
        assert d["version"] == "1.24.0"
        assert d["source"] == "requirements.txt"
        assert d["type"] == "ExternalDependency"


class TestServiceNode:
    """Tests for ServiceNode dataclass."""

    def test_basic_creation(self):
        """Should create service node."""
        node = ServiceNode(
            name="AuthService",
            service_type="internal",
            repository_name="myrepo",
        )

        assert node.name == "AuthService"
        assert node.service_type == "internal"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ServiceNode(
            name="PaymentService",
            service_type="external",
            repository_name="myrepo",
        )

        node_id = node.generate_id()
        assert "myrepo" in node_id
        assert "PaymentService" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = ServiceNode(
            name="EmailService",
            service_type="external",
            repository_name="myrepo",
            endpoints=["send", "verify"],
        )

        d = node.to_dict()

        assert d["name"] == "EmailService"
        assert d["serviceType"] == "external"
        assert d["endpoints"] == ["send", "verify"]
        assert d["type"] == "Service"
