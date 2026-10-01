"""
Directory Classification extraction - LLM-based classification of directories.

This module classifies Graph:Directory nodes into:
- BusinessConcept: Domain-level concepts (customers, orders, invoicing)
- Technology: Technical components (kafka, redis, api)
- Skip: Structural/utility directories (utils, helpers, common)

This provides stable seed concepts for downstream extraction steps.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from deriva.common.naming import name_key
from deriva.modules.derivation.base import name_from_source

from .base import (
    create_empty_llm_details,
    current_timestamp,
    parse_json_response,
    sample_llm,
    sample_usage,
)
from .business_concept import concept_node_id
from .technology_candidates import technology_node_id

# JSON schema for LLM structured output
DIRECTORY_CLASSIFICATION_SCHEMA = {
    "name": "directory_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "directoryName": {
                            "type": "string",
                            "description": "Original directory name",
                        },
                        "classification": {
                            "type": "string",
                            "enum": ["business", "technology", "skip"],
                            "description": "Classification type",
                        },
                        "conceptType": {
                            "type": "string",
                            "enum": ["entity", "process", "actor", "capability", "infrastructure", "framework", "none"],
                            "description": "Business: entity, process, actor or capability; technology: infrastructure or framework; skip: none",
                        },
                    },
                    "required": [
                        "directoryName",
                        "classification",
                        "conceptType",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["classifications"],
        "additionalProperties": False,
    },
}


def build_classification_prompt(
    directories: list[dict[str, Any]],
    instruction: str,
    example: str,
) -> str:
    """
    Build the LLM prompt for directory classification.

    Args:
        directories: List of directory info dicts with 'name', 'path', and optional file stats
        instruction: Classification instruction from config (contains all rules)
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    import json

    # Format directory list with file context if available
    formatted_dirs = []
    for d in directories:
        dir_info: dict[str, Any] = {"name": d.get("name", d.get("dirName", ""))}
        # A name entry lists every directory with that name (see group_directories_by_name)
        if "paths" in d:
            dir_info["paths"] = d["paths"]
        else:
            dir_info["path"] = d.get("path", d.get("dirPath", ""))
        # Include file stats if available (from graph query enrichment)
        file_count = d.get("file_count", 0)
        if file_count and file_count > 0:
            file_stats = []
            if d.get("source_count", 0) > 0:
                file_stats.append(f"source:{d['source_count']}")
            if d.get("config_count", 0) > 0:
                file_stats.append(f"config:{d['config_count']}")
            if d.get("docs_count", 0) > 0:
                file_stats.append(f"docs:{d['docs_count']}")
            if d.get("test_count", 0) > 0:
                file_stats.append(f"test:{d['test_count']}")
            dir_info["files"] = f"{file_count} ({', '.join(file_stats)})" if file_stats else str(file_count)

            # Include subtypes (languages) if available, sorted (not in storage order)
            subtypes = d.get("subtypes", [])
            if subtypes and len(subtypes) > 0:
                # Filter out None values
                valid_subtypes = sorted(s for s in subtypes if s)
                if valid_subtypes:
                    dir_info["languages"] = valid_subtypes

        formatted_dirs.append(dir_info)

    dir_list = json.dumps(formatted_dirs, indent=2)

    prompt = f"""{instruction}

## Directories to Classify
```json
{dir_list}
```

## Example Output
{example}

Return JSON with classifications for each directory.
"""
    return prompt


def build_business_concept_node(
    classification: dict[str, Any],
    source_dir_id: str,
    repo_name: str,
    confidence: float,
) -> dict[str, Any]:
    """Build a BusinessConcept node from classification result.

    The name comes from the directory itself (``claims_handling`` ->
    ``ClaimsHandling``); the LLM only classified the directory. The confidence
    is the step's configured value for directory concepts, not an LLM guess.
    """
    concept_name = name_from_source(classification["directoryName"]).replace(" ", "")
    node_id = concept_node_id(repo_name, concept_name)

    return {
        "id": node_id,
        "labels": ["Graph", "Graph:BusinessConcept"],
        "properties": {
            "conceptName": concept_name,
            "conceptType": classification.get("conceptType", "entity"),
            "description": "",
            "originSource": f"directory:{classification['directoryName']}/",
            "confidence": confidence,
            "repositoryName": repo_name,
            "active": True,
            "extracted_at": current_timestamp(),
        },
    }


def build_technology_node(
    classification: dict[str, Any],
    source_dir_id: str,
    repo_name: str,
    confidence: float,
) -> dict[str, Any]:
    """Build a Technology node from classification result (name from the directory, confidence from the config)."""
    concept_name = name_from_source(classification["directoryName"])
    node_id = technology_node_id(repo_name, concept_name)

    return {
        "id": node_id,
        "labels": ["Graph", "Graph:Technology"],
        "properties": {
            "technologyName": concept_name,
            "technologyType": classification.get("conceptType", "infrastructure"),
            "description": "",
            "originSource": f"directory:{classification['directoryName']}/",
            "confidence": confidence,
            "repositoryName": repo_name,
            "active": True,
            "extracted_at": current_timestamp(),
        },
    }


# File counts summed over the directories of one name
_FILE_COUNTS = ("file_count", "source_count", "config_count", "docs_count", "test_count")


def group_directories_by_name(directories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per name (canonical name key), with its paths, ids, summed file counts and languages.

    A concept's identity is its name key, so all directories with that name are one
    decision. Grouped before batching, copies never land in different prompts or get
    different answers. A group keeps its first directory's name, in order of first appearance.
    """
    groups: dict[str, dict[str, Any]] = {}
    for d in directories:
        name = str(d.get("name", d.get("dirName", "")))
        group = groups.setdefault(name_key(name), {"name": name, "paths": [], "ids": [], "subtypes": [], **dict.fromkeys(_FILE_COUNTS, 0)})
        group["paths"].append(d.get("path", d.get("dirPath", "")))
        group["ids"].append(d.get("id", ""))
        for count in _FILE_COUNTS:
            group[count] += d.get(count) or 0
        group["subtypes"] = sorted(set(group["subtypes"]) | {s for s in d.get("subtypes") or [] if s})
    return list(groups.values())


def structural_skip(directories: list[dict[str, Any]], params: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split off the directories the structure already decides as skip, before any LLM call.

    Configured in the step's params (versioned): ``skip_names`` skips a directory
    whose own name matches (by canonical name key), ``skip_trees`` also everything
    inside such a directory, and ``skip_pass_through`` skips path steps: directories
    without files and with a single subdirectory (a package prefix, for example).

    Args:
        directories: Directory rows with ``name``, ``path``, ``file_count`` and ``subdir_count``
        params: The step's params

    Returns:
        (directories to classify, skipped directories), each in the given order
    """
    names = {name_key(n) for n in params.get("skip_names", [])}
    trees = {name_key(n) for n in params.get("skip_trees", [])}
    pass_through = bool(params.get("skip_pass_through", False))
    keep: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for d in directories:
        segments = [name_key(s) for s in str(d.get("path", "")).split("/")]
        own = name_key(str(d.get("name", "")))
        is_step = pass_through and not d.get("file_count") and d.get("subdir_count") == 1
        skip = own in names or own in trees or any(s in trees for s in segments[:-1]) or is_step
        (skipped if skip else keep).append(d)
    return keep, skipped


def vote_directory_classifications(samples: list[list[dict[str, Any]]], min_votes: int) -> list[dict[str, Any]]:
    """Per directory, the (classification, type) given by at least ``min_votes`` samples.

    Samples are answers to the same prompt. The winner has the most votes (ties
    broken by name); directories without such a majority are left out, which
    means skipped.
    """
    votes: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for classifications in samples:
        seen: set[str] = set()
        for c in classifications:
            directory = str(c.get("directoryName", ""))
            if not directory or directory in seen:
                continue
            seen.add(directory)
            key = (
                str(c.get("classification", "skip")),
                str(c.get("conceptType", "")).lower(),
            )
            votes.setdefault(directory, {}).setdefault(key, []).append(c)

    winners: list[dict[str, Any]] = []
    for directory in sorted(votes):
        options = votes[directory]
        key = min(options, key=lambda k: (-len(options[k]), k))
        if len(options[key]) < min_votes:
            continue
        winners.append({"directoryName": directory, "classification": key[0], "conceptType": key[1]})
    return winners


def classify_directories(
    directories: list[dict[str, Any]],
    repo_name: str,
    llm_query_fn: Callable,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Classify directories into BusinessConcept, Technology, or skip.

    Args:
        directories: List of directory info dicts from graph query
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config with 'instruction' and 'example' keys

    Returns:
        Dictionary with:
            - success: bool
            - data: Dict with 'nodes' and 'edges' lists
            - errors: List[str]
            - stats: Dict
            - llm_details: Dict
    """
    llm_details = create_empty_llm_details()

    if not directories:
        return {
            "success": True,
            "data": {"nodes": [], "edges": []},
            "errors": [],
            "stats": {"total_nodes": 0, "skipped": 0},
            "llm_details": llm_details,
        }

    try:
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_classification_prompt(
            directories=directories,
            instruction=instruction,
            example=example,
        )
        llm_details["prompt"] = prompt

        # Call LLM: k answers to the same prompt, combined by majority (params.samples / min_votes)
        params = config.get("params") or {}
        responses = sample_llm(
            llm_query_fn,
            prompt,
            DIRECTORY_CLASSIFICATION_SCHEMA,
            int(params.get("samples", 1)),
        )
        min_votes = int(params.get("min_votes", 1))
        response = next((r for r in responses if r is not None and not getattr(r, "error", None)), None)
        if response is None:
            first_error = next((r.error for r in responses if r is not None and getattr(r, "error", None)), "every sample failed")
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"LLM error: {first_error}"],
                "stats": {},
                "llm_details": llm_details,
            }

        # Extract LLM details from response
        if hasattr(response, "content"):
            llm_details["response"] = response.content
        llm_details["tokens_in"], llm_details["tokens_out"] = sample_usage(responses)
        if hasattr(response, "response_type"):
            llm_details["cache_used"] = str(response.response_type) == "ResponseType.CACHED"

        # Parse every sample, then take the per-directory majority
        parsed_samples = []
        parse_errors: list[str] = []
        for sample in responses:
            if sample is None or getattr(sample, "error", None):
                continue
            sample_result = parse_json_response(sample.content, "classifications")
            if sample_result["success"]:
                parsed_samples.append(sample_result["data"])
            else:
                parse_errors.extend(sample_result.get("errors", []))
        if not parsed_samples:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": parse_errors or ["Failed to parse LLM response"],
                "stats": {},
                "llm_details": llm_details,
            }

        parsed = {"classifications": vote_directory_classifications(parsed_samples, min_votes)}

        # Build nodes from classifications
        nodes = []
        edges = []
        stats = {
            "business_concepts": 0,
            "technologies": 0,
            "skipped": 0,
        }

        # Source directory IDs per name key: the answer names directories by name (in any
        # spelling), so every directory with that name gets the classification (and its edge)
        dir_ids: dict[str, list[str]] = {}
        dir_names: dict[str, str] = {}
        for d in directories:
            name = d.get("name", d.get("dirName", ""))
            dir_ids.setdefault(name_key(name), []).extend(d.get("ids") or [d.get("id", "")])
            dir_names.setdefault(name_key(name), name)

        # Directories without a (majority) classification get no node: skipped
        classified = {name_key(c.get("directoryName", "")) for c in parsed.get("classifications", [])}
        stats["skipped"] += sum(len(ids) for key, ids in dir_ids.items() if key not in classified)

        # The answer holds decisions only; nodes and edges get the configured confidence
        confidence = float(params.get("confidence", 0.8))
        for classification in parsed.get("classifications", []):
            key = name_key(classification.get("directoryName", ""))
            # The node takes the directory's name, not the answer's spelling of it
            classification = {**classification, "directoryName": dir_names.get(key, classification.get("directoryName", ""))}
            class_type = classification.get("classification", "skip")
            source_ids = [i for i in dir_ids.get(key, []) if i]
            source_dir_id = source_ids[0] if source_ids else ""

            if class_type == "skip":
                stats["skipped"] += 1
                continue

            if class_type == "business":
                node = build_business_concept_node(classification, source_dir_id, repo_name, confidence)
                nodes.append(node)
                stats["business_concepts"] += 1

                # Create edges from the Directories to the BusinessConcept
                for dir_id in source_ids:
                    edges.append(
                        {
                            "source": dir_id,
                            "target": node["id"],
                            "relationship_type": "REPRESENTS",
                            "properties": {
                                "created_at": current_timestamp(),
                                "confidence": confidence,
                            },
                        }
                    )

            elif class_type == "technology":
                node = build_technology_node(classification, source_dir_id, repo_name, confidence)
                nodes.append(node)
                stats["technologies"] += 1

                # Create edges from the Directories to the Technology
                for dir_id in source_ids:
                    edges.append(
                        {
                            "source": dir_id,
                            "target": node["id"],
                            "relationship_type": "REPRESENTS",
                            "properties": {
                                "created_at": current_timestamp(),
                                "confidence": confidence,
                            },
                        }
                    )

        stats["total_nodes"] = len(nodes)

        return {
            "success": True,
            "data": {"nodes": nodes, "edges": edges},
            "errors": [],
            "stats": stats,
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [str(e)],
            "stats": {},
            "llm_details": llm_details,
        }
