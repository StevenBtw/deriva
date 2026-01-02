# Repository Adapter

Git repository operations and metadata extraction.

## Purpose

The Repository adapter handles cloning Git repositories, listing cloned repos, extracting metadata, and managing repository state. Cloned repositories are stored in `workspace/repositories/`.

## Key Exports

```python
from deriva.adapters.repository import (
    RepoManager,            # Main service class
    RepositoryInfo,         # Repository metadata dataclass
    RepositoryMetadata,     # Extended metadata with stats
    FileNode,               # File tree node
    # Convenience functions
    validate_repo,
    clone_repo,
    list_repos,
    delete_repo,
    extract_repo_metadata,
    # Exceptions
    RepositoryError,
    ValidationError,
    CloneError,
)
```

## Basic Usage

```python
from deriva.adapters.repository import RepoManager

repo_manager = RepoManager()

# Clone a repository
repo_manager.clone_repository(
    url="https://github.com/user/project.git",
    repo_name="project"  # Optional, derived from URL if not provided
)

# List cloned repositories
repos = repo_manager.list_repositories()
for repo in repos:
    print(f"{repo.name}: {repo.branch}")

# Get repository info
info = repo_manager.get_repository_info("project")
print(f"Size: {info.size_mb} MB, Dirty: {info.is_dirty}")

# Extract metadata
metadata = repo_manager.extract_metadata("project")
print(f"Files: {metadata.total_files}, Languages: {metadata.languages}")

# Delete repository
repo_manager.delete_repository("project")
```

## Convenience Functions

For quick operations without creating a manager:

```python
from deriva.adapters.repository import clone_repo, list_repos

# Clone
clone_repo("https://github.com/user/project.git")

# List all
repos = list_repos()
```

## Data Classes

**RepositoryInfo**:

- `name`, `path`, `url`, `branch`, `last_commit`
- `is_dirty`, `size_mb`, `cloned_at`

**RepositoryMetadata**:

- `total_files`, `total_directories`, `total_size_mb`
- `languages` - dict of language name to file count
- `default_branch`, `created_at`, `last_updated`

## RepoManager Methods

| Method | Description |
|--------|-------------|
| `validate_repository(url)` | Validate Git URL |
| `clone_repository(url, name)` | Clone repo to workspace |
| `list_repositories()` | List all cloned repos |
| `get_repository_info(name)` | Get repo metadata |
| `delete_repository(name)` | Remove cloned repo |
| `extract_metadata(name)` | Extract structure metadata |

## Storage

- Repositories cloned to: `workspace/repositories/{repo_name}/`
- State persisted in YAML for tracking cloned repos

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
