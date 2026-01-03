"""Tests for adapters.graph.models module."""

from __future__ import annotations

from datetime import datetime

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

    def test_strips_leading_slash(self):
        """Should strip leading slashes."""
        result = normalize_path("/src/main.py")
        assert result == "src/main.py"

    def test_empty_path(self):
        """Should handle empty path."""
        result = normalize_path("")
        assert result == ""

    def test_with_repo_name_prefix(self):
        """Should add repo name prefix when provided."""
        result = normalize_path("src/main.py", repo_name="myrepo")
        assert result == "myrepo/src/main.py"


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
        )
        d = node.to_dict()
        assert d["repoName"] == "myproject"
        assert d["type"] == "Repository"


class TestDirectoryNode:
    """Tests for DirectoryNode dataclass."""

    def test_basic_creation(self):
        """Should create directory node."""
        node = DirectoryNode(name="src", path="src", repository_name="myrepo")
        assert node.name == "src"

    def test_generate_id(self):
        """Should generate unique ID from path."""
        node = DirectoryNode(
            name="helpers", path="src/utils/helpers", repository_name="myrepo"
        )
        assert node.generate_id() == "Directory_myrepo_src_utils_helpers"

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = DirectoryNode(name="utils", path="src/utils", repository_name="myrepo")
        d = node.to_dict()
        assert d["name"] == "utils"
        assert d["type"] == "Directory"


class TestFileNode:
    """Tests for FileNode dataclass."""

    def test_basic_creation(self):
        """Should create file node."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            file_type="source",
            subtype="python",
        )
        assert node.name == "main.py"
        assert node.file_type == "source"

    def test_generate_id(self):
        """Should generate unique ID from path."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            file_type="source",
        )
        assert node.generate_id() == "File_myrepo_src_main.py"

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = FileNode(
            name="main.py",
            path="src/main.py",
            repository_name="myrepo",
            file_type="source",
            size=1024,
        )
        d = node.to_dict()
        assert d["fileName"] == "main.py"
        assert d["fileType"] == "source"
        assert d["size"] == 1024
        assert d["type"] == "File"


class TestModuleNode:
    """Tests for ModuleNode dataclass."""

    def test_basic_creation(self):
        """Should create module node."""
        node = ModuleNode(
            name="utils", paths=["src/utils"], repository_name="myrepo"
        )
        assert node.name == "utils"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ModuleNode(name="core", paths=["src/core"], repository_name="myrepo")
        assert node.generate_id() == "Module_myrepo_core"


class TestBusinessConceptNode:
    """Tests for BusinessConceptNode dataclass."""

    def test_basic_creation(self):
        """Should create business concept node."""
        node = BusinessConceptNode(
            name="User Authentication",
            concept_type="service",
            description="Handles user login",
            origin_source="src/auth.py",
            repository_name="myrepo",
        )
        assert node.name == "User Authentication"
        assert node.concept_type == "service"

    def test_invalid_concept_type_defaults_to_other(self):
        """Should default to 'other' for invalid concept types."""
        node = BusinessConceptNode(
            name="Test",
            concept_type="invalid_type",
            description="Test",
            origin_source="test.py",
            repository_name="myrepo",
        )
        assert node.concept_type == "other"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = BusinessConceptNode(
            name="Payment",
            concept_type="service",
            description="Payments",
            origin_source="pay.py",
            repository_name="myrepo",
        )
        node_id = node.generate_id()
        assert "Payment" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = BusinessConceptNode(
            name="Payment Processing",
            concept_type="process",
            description="Handles payments",
            origin_source="payment.py",
            repository_name="myrepo",
        )
        d = node.to_dict()
        assert d["conceptName"] == "Payment Processing"
        assert d["type"] == "BusinessConcept"


class TestTechnologyNode:
    """Tests for TechnologyNode dataclass."""

    def test_basic_creation(self):
        """Should create technology node."""
        node = TechnologyNode(
            name="PostgreSQL",
            tech_category="system_software",
            repository_name="myrepo",
        )
        assert node.name == "PostgreSQL"
        assert node.tech_category == "system_software"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = TechnologyNode(
            name="FastAPI", tech_category="service", repository_name="myrepo"
        )
        node_id = node.generate_id()
        assert "FastAPI" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TechnologyNode(
            name="Redis",
            tech_category="system_software",
            repository_name="myrepo",
            version="7.0",
        )
        d = node.to_dict()
        assert d["techName"] == "Redis"
        assert d["type"] == "Technology"


class TestTypeDefinitionNode:
    """Tests for TypeDefinitionNode dataclass."""

    def test_basic_creation(self):
        """Should create type definition node."""
        node = TypeDefinitionNode(
            name="UserModel",
            type_category="class",
            file_path="src/models/user.py",
            repository_name="myrepo",
        )
        assert node.name == "UserModel"
        assert node.type_category == "class"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = TypeDefinitionNode(
            name="UserModel",
            type_category="class",
            file_path="src/user.py",
            repository_name="myrepo",
        )
        node_id = node.generate_id()
        assert "UserModel" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TypeDefinitionNode(
            name="UserModel",
            type_category="class",
            file_path="src/models/user.py",
            repository_name="myrepo",
            code_snippet="class UserModel:",
        )
        d = node.to_dict()
        assert d["typeName"] == "UserModel"
        assert d["type"] == "TypeDefinition"


class TestMethodNode:
    """Tests for MethodNode dataclass."""

    def test_basic_creation(self):
        """Should create method node."""
        node = MethodNode(
            name="get_user",
            return_type="User",
            visibility="public",
            file_path="src/api.py",
            type_name="UserService",
            repository_name="myrepo",
        )
        assert node.name == "get_user"
        assert node.return_type == "User"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = MethodNode(
            name="process_data",
            return_type="None",
            visibility="private",
            file_path="src/processor.py",
            type_name="Processor",
            repository_name="myrepo",
        )
        node_id = node.generate_id()
        assert "process_data" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = MethodNode(
            name="save",
            return_type="bool",
            visibility="public",
            file_path="src/model.py",
            type_name="UserModel",
            repository_name="myrepo",
        )
        d = node.to_dict()
        assert d["methodName"] == "save"
        assert d["type"] == "Method"


class TestTestNode:
    """Tests for TestNode dataclass."""

    def test_basic_creation(self):
        """Should create test node."""
        node = TestNode(
            name="test_user_creation",
            test_type="unit",
            file_path="tests/test_user.py",
            repository_name="myrepo",
        )
        assert node.name == "test_user_creation"
        assert node.test_type == "unit"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = TestNode(
            name="test_api",
            test_type="integration",
            file_path="tests/test_api.py",
            repository_name="myrepo",
        )
        node_id = node.generate_id()
        assert "test_api" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = TestNode(
            name="test_login",
            test_type="unit",
            file_path="tests/test_auth.py",
            repository_name="myrepo",
            tested_element="auth.login",
        )
        d = node.to_dict()
        assert d["testName"] == "test_login"
        assert d["type"] == "Test"


class TestExternalDependencyNode:
    """Tests for ExternalDependencyNode dataclass."""

    def test_basic_creation(self):
        """Should create external dependency node."""
        node = ExternalDependencyNode(
            name="requests",
            dependency_category="library",
            repository_name="myrepo",
            version="2.28.0",
        )
        assert node.name == "requests"
        assert node.version == "2.28.0"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ExternalDependencyNode(
            name="django",
            dependency_category="library",
            repository_name="myrepo",
            version="4.0",
        )
        node_id = node.generate_id()
        assert "django" in node_id.lower()

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = ExternalDependencyNode(
            name="numpy",
            dependency_category="library",
            repository_name="myrepo",
            version="1.24.0",
        )
        d = node.to_dict()
        assert d["dependencyName"] == "numpy"
        assert d["type"] == "ExternalDependency"


class TestServiceNode:
    """Tests for ServiceNode dataclass."""

    def test_basic_creation(self):
        """Should create service node."""
        node = ServiceNode(
            name="AuthService",
            description="Authentication service",
            exposure_level="internal",
            repository_name="myrepo",
        )
        assert node.name == "AuthService"
        assert node.exposure_level == "internal"

    def test_generate_id(self):
        """Should generate unique ID."""
        node = ServiceNode(
            name="PaymentService",
            description="Payments",
            exposure_level="public",
            repository_name="myrepo",
        )
        node_id = node.generate_id()
        assert "PaymentService" in node_id

    def test_to_dict(self):
        """Should convert to dictionary."""
        node = ServiceNode(
            name="EmailService",
            description="Email notifications",
            exposure_level="public",
            repository_name="myrepo",
        )
        d = node.to_dict()
        assert d["serviceName"] == "EmailService"
        assert d["type"] == "Service"
