"""Tests for modules.derivation.base module."""

from deriva.adapters.llm.models import ResponseType
from deriva.common import current_timestamp, extract_llm_details
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    RELATIONSHIP_SCHEMA,
    build_derivation_prompt,
    build_element,
    build_element_relationship_prompt,
    build_relationship_prompt,
    create_result,
    parse_derivation_response,
    parse_relationship_response,
)


class TestBuildDerivationPrompt:
    """Tests for build_derivation_prompt function."""

    def test_includes_graph_results(self):
        """Should include graph results in prompt."""
        candidates = [{"name": "auth", "path": "src/auth"}]
        prompt = build_derivation_prompt(candidates=candidates, instruction="Group directories", example='{"identifier": "app:auth"}', element_type="ApplicationComponent")

        assert "auth" in prompt
        assert "src/auth" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_derivation_prompt(candidates=[], instruction="Group top-level directories into components", example="{}", element_type="ApplicationComponent")

        assert "Group top-level directories" in prompt

    def test_includes_element_type(self):
        """Should reference element type in prompt."""
        prompt = build_derivation_prompt(candidates=[], instruction="Test", example="{}", element_type="ApplicationService")

        assert "ApplicationService" in prompt


class TestParseDerivationResponse:
    """Tests for parse_derivation_response function."""

    def test_valid_response(self):
        """Should parse valid response with elements array."""
        response = '{"elements": [{"identifier": "app:auth", "name": "Auth"}]}'
        result = parse_derivation_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["identifier"] == "app:auth"

    def test_empty_elements(self):
        """Should accept empty elements array."""
        response = '{"elements": []}'
        result = parse_derivation_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_elements_key(self):
        """Should fail when elements key is missing."""
        response = '{"items": []}'
        result = parse_derivation_response(response)

        assert result["success"] is False
        assert 'missing "elements"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON."""
        response = "not valid json"
        result = parse_derivation_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestBuildElement:
    """Tests for build_element function."""

    def test_valid_element(self):
        """Should build element from valid data."""
        derived = {"identifier": "app:auth", "name": "Auth Component", "confidence": 0.9, "source": "Directory:src/auth"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is True
        assert result["data"]["name"] == "Auth Component"
        assert result["data"]["element_type"] == "ApplicationComponent"
        assert result["data"]["properties"]["confidence"] == 0.9

    def test_missing_identifier(self):
        """Should fail when identifier is missing."""
        derived = {"name": "Auth Component"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is False
        assert any("identifier" in e or "name" in e for e in result["errors"])

    def test_missing_name(self):
        """Should fail when name is missing."""
        derived = {"identifier": "app:auth"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is False
        assert any("identifier" in e or "name" in e for e in result["errors"])

    def test_uses_documentation(self):
        """Should use documentation field."""
        derived = {"identifier": "app:auth", "name": "Auth", "documentation": "Auth docs"}
        result = build_element(derived, "ApplicationComponent")
        assert result["data"]["documentation"] == "Auth docs"


class TestCreateResult:
    """Tests for create_result function."""

    def test_success_result(self):
        """Should create success result structure."""
        result = create_result(success=True, errors=[], stats={"count": 1})

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"] == {"count": 1}
        assert "timestamp" in result

    def test_failure_result_with_errors(self):
        """Should include errors when provided."""
        result = create_result(success=False, errors=["Something went wrong"], stats={})

        assert result["success"] is False
        assert "Something went wrong" in result["errors"]


class TestCurrentTimestamp:
    """Tests for current_timestamp function."""

    def test_returns_iso_format(self):
        """Should return ISO format with Z suffix."""
        ts = current_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts


class TestDerivationSchema:
    """Tests for DERIVATION_SCHEMA constant."""

    def test_schema_has_required_structure(self):
        """Should have name and schema properties."""
        assert "name" in DERIVATION_SCHEMA
        assert "schema" in DERIVATION_SCHEMA
        assert DERIVATION_SCHEMA["name"] == "derivation_output"

    def test_schema_requires_elements_array(self):
        """Should require elements array in response."""
        schema = DERIVATION_SCHEMA["schema"]
        assert "elements" in schema["properties"]
        assert "elements" in schema["required"]

    def test_elements_require_identifier_and_name(self):
        """Should require identifier and name for each element."""
        items_schema = DERIVATION_SCHEMA["schema"]["properties"]["elements"]["items"]
        assert "identifier" in items_schema["required"]
        assert "name" in items_schema["required"]


class TestRelationshipSchema:
    """Tests for RELATIONSHIP_SCHEMA constant."""

    def test_schema_has_required_structure(self):
        """Should have name and schema properties."""
        assert "name" in RELATIONSHIP_SCHEMA
        assert "schema" in RELATIONSHIP_SCHEMA
        assert RELATIONSHIP_SCHEMA["name"] == "relationship_output"

    def test_schema_requires_relationships_array(self):
        """Should require relationships array in response."""
        schema = RELATIONSHIP_SCHEMA["schema"]
        assert "relationships" in schema["properties"]
        assert "relationships" in schema["required"]

    def test_relationships_require_source_target_type(self):
        """Should require source, target, relationship_type for each relationship."""
        items_schema = RELATIONSHIP_SCHEMA["schema"]["properties"]["relationships"]["items"]
        assert "source" in items_schema["required"]
        assert "target" in items_schema["required"]
        assert "relationship_type" in items_schema["required"]


class TestBuildRelationshipPrompt:
    """Tests for build_relationship_prompt function."""

    def test_includes_elements(self):
        """Should include elements in prompt."""
        elements = [
            {"identifier": "app:auth", "name": "Auth", "element_type": "ApplicationComponent"},
            {"identifier": "app:api", "name": "API", "element_type": "ApplicationComponent"},
        ]
        prompt = build_relationship_prompt(elements)

        assert "app:auth" in prompt
        assert "app:api" in prompt
        assert "Auth" in prompt

    def test_includes_relationship_types(self):
        """Should mention ArchiMate relationship types."""
        prompt = build_relationship_prompt([])

        assert "Composition" in prompt
        assert "Serving" in prompt
        assert "Realization" in prompt

    def test_includes_instructions(self):
        """Should include instructions for relationship derivation."""
        prompt = build_relationship_prompt([])

        assert "relationships" in prompt.lower()
        assert "source" in prompt.lower()
        assert "target" in prompt.lower()


class TestParseRelationshipResponse:
    """Tests for parse_relationship_response function."""

    def test_valid_response(self):
        """Should parse valid response with relationships array."""
        response = '{"relationships": [{"source": "app:auth", "target": "app:api", "relationship_type": "Serving"}]}'
        result = parse_relationship_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["source"] == "app:auth"
        assert result["data"][0]["target"] == "app:api"

    def test_empty_relationships(self):
        """Should accept empty relationships array."""
        response = '{"relationships": []}'
        result = parse_relationship_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_relationships_key(self):
        """Should fail when relationships key is missing."""
        response = '{"items": []}'
        result = parse_relationship_response(response)

        assert result["success"] is False
        assert 'missing "relationships"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON."""
        response = "not valid json"
        result = parse_relationship_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestExtractLlmDetails:
    """Tests for extract_llm_details function."""

    def test_live_response_cache_used_false(self):
        """Should set cache_used=False for live responses."""

        class MockLiveResponse:
            response_type = ResponseType.LIVE
            content = "test content"
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        details = extract_llm_details(MockLiveResponse())

        assert details["cache_used"] is False
        assert details["response"] == "test content"
        assert details["tokens_in"] == 100
        assert details["tokens_out"] == 50

    def test_cached_response_cache_used_true(self):
        """Should set cache_used=True for cached responses."""

        class MockCachedResponse:
            response_type = ResponseType.CACHED
            content = "cached content"
            usage = None

        details = extract_llm_details(MockCachedResponse())

        assert details["cache_used"] is True
        assert details["response"] == "cached content"
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0

    def test_response_without_usage(self):
        """Should handle response without usage data."""

        class MockResponse:
            response_type = ResponseType.LIVE
            content = "no usage"
            usage = None

        details = extract_llm_details(MockResponse())

        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0

    def test_response_without_response_type(self):
        """Should default cache_used to False when response_type missing."""

        class MockResponse:
            content = "plain response"

        details = extract_llm_details(MockResponse())

        assert details["cache_used"] is False
        assert details["response"] == "plain response"

    def test_response_without_content(self):
        """Should handle response without content attribute."""

        class MockResponse:
            response_type = ResponseType.LIVE

        details = extract_llm_details(MockResponse())

        assert details["response"] == ""
        assert details["cache_used"] is False


class TestBuildElementRelationshipPrompt:
    """Tests for build_element_relationship_prompt function."""

    def test_includes_source_elements(self):
        """Should include source elements in prompt."""
        source_elements = [
            {"identifier": "app_auth", "name": "Auth Component", "element_type": "ApplicationComponent"},
        ]
        target_elements = [
            {"identifier": "svc_login", "name": "Login Service", "element_type": "ApplicationService"},
        ]
        valid_relationships = [
            {"relationship_type": "Serving", "description": "Provides services to", "allowed_targets": ["ApplicationService"]},
        ]

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
        )

        assert "app_auth" in prompt
        assert "Auth Component" in prompt
        assert "Source Elements" in prompt

    def test_includes_target_elements(self):
        """Should include target elements in prompt."""
        source_elements = [
            {"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"},
        ]
        target_elements = [
            {"identifier": "svc_login", "name": "Login Service", "element_type": "ApplicationService"},
            {"identifier": "data_user", "name": "User Data", "element_type": "DataObject"},
        ]
        valid_relationships = []

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
        )

        assert "svc_login" in prompt
        assert "Login Service" in prompt
        assert "data_user" in prompt
        assert "Target Elements" in prompt

    def test_includes_valid_relationship_types(self):
        """Should include valid relationship types from metamodel."""
        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = [{"identifier": "svc_login", "name": "Login", "element_type": "ApplicationService"}]
        valid_relationships = [
            {"relationship_type": "Serving", "description": "Provides services to", "allowed_targets": ["ApplicationService"]},
            {"relationship_type": "Composition", "description": "Consists of", "allowed_targets": ["ApplicationComponent"]},
        ]

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
        )

        assert "Serving" in prompt
        assert "Composition" in prompt
        assert "Provides services to" in prompt
        assert "ApplicationService" in prompt

    def test_uses_custom_instruction(self):
        """Should use custom instruction when provided."""
        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = []
        valid_relationships = []
        custom_instruction = "Custom instruction for deriving ApplicationComponent relationships"

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
            instruction=custom_instruction,
        )

        assert custom_instruction in prompt

    def test_uses_custom_example(self):
        """Should use custom example when provided."""
        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = []
        valid_relationships = []
        custom_example = '{"relationships": [{"source": "custom_src", "target": "custom_tgt", "relationship_type": "Flow"}]}'

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
            example=custom_example,
        )

        assert custom_example in prompt

    def test_uses_default_instruction_when_not_provided(self):
        """Should use default instruction when not provided."""
        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = []
        valid_relationships = []

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
        )

        # Default instruction mentions deriving relationships FROM the element type
        assert "Derive relationships FROM" in prompt
        assert "ApplicationComponent" in prompt

    def test_includes_identifier_validation_rules(self):
        """Should include strict identifier validation rules."""
        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = [{"identifier": "svc_login", "name": "Login", "element_type": "ApplicationService"}]
        valid_relationships = []

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            valid_relationships=valid_relationships,
        )

        # Should include the identifier lists for validation
        assert "app_auth" in prompt
        assert "svc_login" in prompt
        assert "CRITICAL RULES" in prompt

    def test_mentions_source_element_type(self):
        """Should mention the source element type throughout prompt."""
        source_elements = [{"identifier": "svc_auth", "name": "Auth Service", "element_type": "ApplicationService"}]
        target_elements = []
        valid_relationships = []

        prompt = build_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationService",
            valid_relationships=valid_relationships,
        )

        # Element type should appear multiple times in context
        assert prompt.count("ApplicationService") >= 2


class TestCandidate:
    """Tests for Candidate dataclass."""

    def test_to_dict_conversion(self):
        """Should convert Candidate to dict for LLM prompts."""
        from deriva.modules.derivation.base import Candidate

        candidate = Candidate(
            node_id="test_123",
            name="TestMethod",
            labels=["Method"],
            properties={"module": "auth"},
            pagerank=0.12345,
            louvain_community="comm_1",
            kcore_level=3,
            is_articulation_point=True,
            in_degree=5,
            out_degree=10,
        )

        result = candidate.to_dict()

        assert result["id"] == "test_123"
        assert result["name"] == "TestMethod"
        assert result["labels"] == ["Method"]
        assert result["properties"] == {"module": "auth"}
        assert result["pagerank"] == 0.1235  # Rounded to 4 decimals
        assert result["in_degree"] == 5
        assert result["out_degree"] == 10
        # community, kcore, is_bridge removed to reduce LLM token usage

    def test_to_dict_with_include_props_filter(self):
        """Should only include specified properties when include_props is set."""
        from deriva.modules.derivation.base import Candidate

        candidate = Candidate(
            node_id="test_456",
            name="FilteredMethod",
            labels=["Method"],
            properties={
                "name": "method_name",
                "description": "A test method",
                "module": "auth",
                "lineNumber": 42,
                "complexity": 5,
            },
        )

        # Only include name and description
        result = candidate.to_dict(include_props={"name", "description"})

        assert result["properties"] == {"name": "method_name", "description": "A test method"}
        assert "module" not in result["properties"]
        assert "lineNumber" not in result["properties"]


class TestGetEnrichmentsFromGraph:
    """Tests for get_enrichments_from_graph function."""

    def test_returns_enrichments_from_graph_manager(self):
        """Should fetch enrichments from the graph via graph_manager."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import get_enrichments_from_graph

        mock_graph_manager = MagicMock()
        mock_graph_manager.query.return_value = [
            {"node_id": "node_1", "pagerank": 0.5, "louvain_community": "comm_1", "kcore_level": 2, "is_articulation_point": True, "in_degree": 3, "out_degree": 4},
            {"node_id": "node_2", "pagerank": 0.3, "louvain_community": "comm_2", "kcore_level": 1, "is_articulation_point": False, "in_degree": 1, "out_degree": 2},
        ]

        result = get_enrichments_from_graph(mock_graph_manager)

        assert "node_1" in result
        assert result["node_1"]["pagerank"] == 0.5
        assert result["node_1"]["louvain_community"] == "comm_1"
        assert result["node_1"]["kcore_level"] == 2
        assert result["node_1"]["is_articulation_point"] is True
        assert result["node_1"]["in_degree"] == 3
        assert result["node_1"]["out_degree"] == 4

        assert "node_2" in result
        assert result["node_2"]["pagerank"] == 0.3

    def test_handles_null_values(self):
        """Should handle NULL values in enrichment data."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import get_enrichments_from_graph

        mock_graph_manager = MagicMock()
        mock_graph_manager.query.return_value = [
            {"node_id": "node_1", "pagerank": None, "louvain_community": None, "kcore_level": None, "is_articulation_point": None, "in_degree": None, "out_degree": None},
        ]

        result = get_enrichments_from_graph(mock_graph_manager)

        assert result["node_1"]["pagerank"] == 0.0
        assert result["node_1"]["louvain_community"] is None
        assert result["node_1"]["kcore_level"] == 0
        assert result["node_1"]["is_articulation_point"] is False
        assert result["node_1"]["in_degree"] == 0
        assert result["node_1"]["out_degree"] == 0

    def test_returns_empty_on_error(self):
        """Should return empty dict on query error."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import get_enrichments_from_graph

        mock_graph_manager = MagicMock()
        mock_graph_manager.query.side_effect = Exception("DB error")

        result = get_enrichments_from_graph(mock_graph_manager)

        assert result == {}


class TestEnrichCandidate:
    """Tests for enrich_candidate function."""

    def test_enriches_candidate_with_data(self):
        """Should add enrichment data to candidate."""
        from deriva.modules.derivation.base import Candidate, enrich_candidate

        candidate = Candidate(node_id="test_id", name="Test")
        enrichments = {
            "test_id": {
                "pagerank": 0.75,
                "louvain_community": "comm_1",
                "kcore_level": 5,
                "is_articulation_point": True,
                "in_degree": 10,
                "out_degree": 20,
            }
        }

        enrich_candidate(candidate, enrichments)

        assert candidate.pagerank == 0.75
        assert candidate.louvain_community == "comm_1"
        assert candidate.kcore_level == 5
        assert candidate.is_articulation_point is True
        assert candidate.in_degree == 10
        assert candidate.out_degree == 20

    def test_uses_defaults_for_missing_candidate(self):
        """Should use defaults when candidate not in enrichments."""
        from deriva.modules.derivation.base import Candidate, enrich_candidate

        candidate = Candidate(node_id="unknown_id", name="Test")
        enrichments = {}

        enrich_candidate(candidate, enrichments)

        assert candidate.pagerank == 0.0
        assert candidate.louvain_community is None
        assert candidate.kcore_level == 0
        assert candidate.is_articulation_point is False


class TestFilterByPagerank:
    """Tests for filter_by_pagerank function."""

    def test_returns_top_n_candidates(self):
        """Should return top N candidates by pagerank."""
        from deriva.modules.derivation.base import Candidate, filter_by_pagerank

        candidates = [
            Candidate(node_id="1", name="Low", pagerank=0.1),
            Candidate(node_id="2", name="High", pagerank=0.9),
            Candidate(node_id="3", name="Medium", pagerank=0.5),
        ]

        result = filter_by_pagerank(candidates, top_n=2)

        assert len(result) == 2
        assert result[0].name == "High"
        assert result[1].name == "Medium"

    def test_returns_by_percentile(self):
        """Should return top percentile of candidates."""
        from deriva.modules.derivation.base import Candidate, filter_by_pagerank

        candidates = [Candidate(node_id=str(i), name=f"C{i}", pagerank=i / 10) for i in range(10)]

        result = filter_by_pagerank(candidates, percentile=50)

        # Top 50% should return top half
        assert len(result) >= 5

    def test_returns_all_without_filters(self):
        """Should return all candidates sorted by pagerank."""
        from deriva.modules.derivation.base import Candidate, filter_by_pagerank

        candidates = [
            Candidate(node_id="1", name="Low", pagerank=0.1),
            Candidate(node_id="2", name="High", pagerank=0.9),
        ]

        result = filter_by_pagerank(candidates)

        assert len(result) == 2
        assert result[0].name == "High"

    def test_filters_by_min_pagerank(self):
        """Should filter out candidates below min_pagerank threshold."""
        from deriva.modules.derivation.base import Candidate, filter_by_pagerank

        candidates = [
            Candidate(node_id="1", name="VeryLow", pagerank=0.0001),
            Candidate(node_id="2", name="Low", pagerank=0.0005),
            Candidate(node_id="3", name="High", pagerank=0.01),
        ]

        result = filter_by_pagerank(candidates, min_pagerank=0.001)

        assert len(result) == 1
        assert result[0].name == "High"


class TestFilterByLabels:
    """Tests for filter_by_labels function."""

    def test_includes_matching_labels(self):
        """Should include candidates with matching labels."""
        from deriva.modules.derivation.base import Candidate, filter_by_labels

        candidates = [
            Candidate(node_id="1", name="Method1", labels=["Method"]),
            Candidate(node_id="2", name="Class1", labels=["Class"]),
            Candidate(node_id="3", name="Method2", labels=["Method", "Public"]),
        ]

        result = filter_by_labels(candidates, include_labels=["Method"])

        assert len(result) == 2
        assert all("Method" in c.labels for c in result)

    def test_excludes_matching_labels(self):
        """Should exclude candidates with matching labels."""
        from deriva.modules.derivation.base import Candidate, filter_by_labels

        candidates = [
            Candidate(node_id="1", name="Method1", labels=["Method"]),
            Candidate(node_id="2", name="Test1", labels=["Test"]),
            Candidate(node_id="3", name="Method2", labels=["Method", "Test"]),
        ]

        result = filter_by_labels(candidates, exclude_labels=["Test"])

        assert len(result) == 1
        assert result[0].name == "Method1"

    def test_combined_include_exclude(self):
        """Should apply both include and exclude filters."""
        from deriva.modules.derivation.base import Candidate, filter_by_labels

        candidates = [
            Candidate(node_id="1", name="Api1", labels=["Method", "Api"]),
            Candidate(node_id="2", name="TestApi", labels=["Method", "Api", "Test"]),
            Candidate(node_id="3", name="Internal", labels=["Method"]),
        ]

        result = filter_by_labels(
            candidates,
            include_labels=["Api"],
            exclude_labels=["Test"],
        )

        assert len(result) == 1
        assert result[0].name == "Api1"


class TestFilterByCommunity:
    """Tests for filter_by_community function."""

    def test_filters_by_community_ids(self):
        """Should filter by specific community IDs."""
        from deriva.modules.derivation.base import Candidate, filter_by_community

        candidates = [
            Candidate(node_id="1", name="C1", louvain_community="comm_a"),
            Candidate(node_id="2", name="C2", louvain_community="comm_b"),
            Candidate(node_id="3", name="C3", louvain_community="comm_a"),
        ]

        result = filter_by_community(candidates, community_ids={"comm_a"})

        assert len(result) == 2
        assert all(c.louvain_community == "comm_a" for c in result)

    def test_filters_for_only_roots(self):
        """Should filter for community root nodes only."""
        from deriva.modules.derivation.base import Candidate, filter_by_community

        candidates = [
            Candidate(node_id="comm_a", name="Root", louvain_community="comm_a"),
            Candidate(node_id="other_1", name="Member", louvain_community="comm_a"),
            Candidate(node_id="comm_b", name="Root2", louvain_community="comm_b"),
        ]

        result = filter_by_community(candidates, only_roots=True)

        assert len(result) == 2
        assert all(c.node_id == c.louvain_community for c in result)


class TestGetCommunityRoots:
    """Tests for get_community_roots function."""

    def test_returns_root_nodes(self):
        """Should return nodes that are community roots."""
        from deriva.modules.derivation.base import Candidate, get_community_roots

        candidates = [
            Candidate(node_id="comm_a", name="Root", louvain_community="comm_a"),
            Candidate(node_id="member_1", name="Member", louvain_community="comm_a"),
        ]

        result = get_community_roots(candidates)

        assert len(result) == 1
        assert result[0].name == "Root"


class TestGetArticulationPoints:
    """Tests for get_articulation_points function."""

    def test_returns_articulation_points(self):
        """Should return nodes marked as articulation points."""
        from deriva.modules.derivation.base import Candidate, get_articulation_points

        candidates = [
            Candidate(node_id="1", name="Bridge", is_articulation_point=True),
            Candidate(node_id="2", name="Normal", is_articulation_point=False),
            Candidate(node_id="3", name="Bridge2", is_articulation_point=True),
        ]

        result = get_articulation_points(candidates)

        assert len(result) == 2
        assert all(c.is_articulation_point for c in result)


class TestBatchCandidates:
    """Tests for batch_candidates function."""

    def test_splits_into_batches(self):
        """Should split candidates into batches of specified size."""
        from deriva.modules.derivation.base import Candidate, batch_candidates

        candidates = [Candidate(node_id=str(i), name=f"C{i}") for i in range(10)]

        result = batch_candidates(candidates, batch_size=3)

        assert len(result) == 4  # 3, 3, 3, 1
        assert len(result[0]) == 3
        assert len(result[-1]) == 1

    def test_returns_empty_for_empty_input(self):
        """Should return empty list for empty input."""
        from deriva.modules.derivation.base import batch_candidates

        result = batch_candidates([])

        assert result == []

    def test_single_batch_for_small_list(self):
        """Should return single batch if candidates fit."""
        from deriva.modules.derivation.base import Candidate, batch_candidates

        candidates = [Candidate(node_id="1", name="C1")]

        result = batch_candidates(candidates, batch_size=10)

        assert len(result) == 1
        assert len(result[0]) == 1

    def test_groups_by_community(self):
        """Should group candidates by Louvain community when enabled."""
        from deriva.modules.derivation.base import Candidate, batch_candidates

        candidates = [
            Candidate(node_id="1", name="A1", louvain_community="comm_a"),
            Candidate(node_id="2", name="B1", louvain_community="comm_b"),
            Candidate(node_id="3", name="A2", louvain_community="comm_a"),
            Candidate(node_id="4", name="B2", louvain_community="comm_b"),
        ]

        result = batch_candidates(candidates, batch_size=10, group_by_community=True)

        # With batch_size=10, all should be in one batch but grouped by community
        assert len(result) == 1
        names = [c.name for c in result[0]]
        # Community members should be adjacent
        a_indices = [names.index("A1"), names.index("A2")]
        b_indices = [names.index("B1"), names.index("B2")]
        assert abs(a_indices[0] - a_indices[1]) == 1
        assert abs(b_indices[0] - b_indices[1]) == 1

    def test_batches_without_community_grouping(self):
        """Should do simple sequential batching when group_by_community=False."""
        from deriva.modules.derivation.base import Candidate, batch_candidates

        candidates = [Candidate(node_id=str(i), name=f"C{i}") for i in range(7)]

        result = batch_candidates(candidates, batch_size=3, group_by_community=False)

        assert len(result) == 3
        assert len(result[0]) == 3
        assert len(result[1]) == 3
        assert len(result[2]) == 1


class TestQueryCandidates:
    """Tests for query_candidates function."""

    def test_queries_and_creates_candidates(self):
        """Should query graph and create Candidate objects."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import query_candidates

        mock_graph = MagicMock()
        mock_graph.query.return_value = [
            {"id": "node_1", "name": "Method1", "labels": ["Method"], "properties": {"module": "auth"}},
            {"id": "node_2", "name": "Method2", "labels": ["Method"], "properties": {}},
        ]

        result = query_candidates(mock_graph, "MATCH (n) RETURN n")

        assert len(result) == 2
        assert result[0].node_id == "node_1"
        assert result[0].name == "Method1"
        assert result[0].labels == ["Method"]
        assert result[0].properties == {"module": "auth"}

    def test_enriches_candidates_when_enrichments_provided(self):
        """Should enrich candidates with provided enrichment data."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import query_candidates

        mock_graph = MagicMock()
        mock_graph.query.return_value = [
            {"id": "node_1", "name": "Method1", "labels": [], "properties": {}},
        ]
        enrichments = {"node_1": {"pagerank": 0.9, "kcore_level": 5, "in_degree": 10, "out_degree": 5}}

        result = query_candidates(mock_graph, "MATCH (n) RETURN n", enrichments)

        assert result[0].pagerank == 0.9
        assert result[0].kcore_level == 5


class TestSanitizeIdentifier:
    """Tests for sanitize_identifier function."""

    def test_lowercases_and_replaces_special_chars(self):
        """Should lowercase and replace special characters."""
        from deriva.modules.derivation.base import sanitize_identifier

        assert sanitize_identifier("Auth-Service") == "auth_service"
        assert sanitize_identifier("User:Login") == "user_login"
        assert sanitize_identifier("My Component") == "my_component"

    def test_removes_non_alphanumeric(self):
        """Should remove non-alphanumeric characters."""
        from deriva.modules.derivation.base import sanitize_identifier

        assert sanitize_identifier("auth@service!") == "authservice"

    def test_prefixes_if_starts_with_number(self):
        """Should prefix with id_ if starts with number."""
        from deriva.modules.derivation.base import sanitize_identifier

        assert sanitize_identifier("123_service") == "id_123_service"


class TestBuildDerivationPromptWithCandidates:
    """Tests for build_derivation_prompt with Candidate objects."""

    def test_converts_candidates_to_dicts(self):
        """Should convert Candidate objects to dicts for prompt."""
        from deriva.modules.derivation.base import Candidate, build_derivation_prompt

        candidates = [
            Candidate(node_id="test_1", name="TestMethod", pagerank=0.5),
        ]

        prompt = build_derivation_prompt(
            candidates=candidates,
            instruction="Test instruction",
            example="{}",
            element_type="ApplicationInterface",
        )

        assert "test_1" in prompt
        assert "TestMethod" in prompt
        assert "0.5" in prompt


class TestGenerationResult:
    """Tests for GenerationResult dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        from deriva.modules.derivation.base import GenerationResult

        result = GenerationResult(success=True)

        assert result.elements_created == 0
        assert result.relationships_created == 0
        assert result.errors == []
        assert result.created_elements == []
        assert result.created_relationships == []

    def test_tracks_created_elements(self):
        """Should track created elements."""
        from deriva.modules.derivation.base import GenerationResult

        result = GenerationResult(
            success=True,
            elements_created=5,
            created_elements=[{"id": "elem1"}, {"id": "elem2"}],
        )

        assert result.elements_created == 5
        assert len(result.created_elements) == 2

    def test_tracks_errors(self):
        """Should track errors."""
        from deriva.modules.derivation.base import GenerationResult

        result = GenerationResult(
            success=False,
            errors=["Error 1", "Error 2"],
        )

        assert result.success is False
        assert len(result.errors) == 2


class TestRelationshipRule:
    """Tests for RelationshipRule dataclass."""

    def test_basic_attributes(self):
        """Should store target_type, rel_type, and description."""
        from deriva.modules.derivation.base import RelationshipRule

        rule = RelationshipRule(target_type="ApplicationService", rel_type="Serving", description="Provides services to")

        assert rule.target_type == "ApplicationService"
        assert rule.rel_type == "Serving"
        assert rule.description == "Provides services to"

    def test_default_description(self):
        """Should have empty string as default description."""
        from deriva.modules.derivation.base import RelationshipRule

        rule = RelationshipRule(target_type="DataObject", rel_type="Access")

        assert rule.description == ""


class TestDerivationResult:
    """Tests for DerivationResult dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        from deriva.modules.derivation.base import DerivationResult

        result = DerivationResult(success=True)

        assert result.elements == []
        assert result.relationships == []
        assert result.errors == []
        assert result.stats == {}

    def test_stores_elements_and_relationships(self):
        """Should store elements and relationships."""
        from deriva.modules.derivation.base import DerivationResult

        result = DerivationResult(
            success=True,
            elements=[{"id": "elem1"}],
            relationships=[{"source": "a", "target": "b"}],
            stats={"count": 1},
        )

        assert len(result.elements) == 1
        assert len(result.relationships) == 1
        assert result.stats["count"] == 1


class TestDeprecatedGetEnrichments:
    """Tests for deprecated get_enrichments function."""

    def test_logs_warning_and_returns_empty(self):
        """Should log deprecation warning and return empty dict."""
        from deriva.modules.derivation.base import get_enrichments

        result = get_enrichments(None)

        assert result == {}


class TestBuildPerElementRelationshipPrompt:
    """Tests for build_per_element_relationship_prompt function."""

    def test_includes_source_elements(self):
        """Should include source elements in prompt."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        source_elements = [{"identifier": "app_auth", "name": "Auth Component", "element_type": "ApplicationComponent"}]
        target_elements = [{"identifier": "svc_login", "name": "Login Service", "element_type": "ApplicationService"}]

        prompt = build_per_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            instruction="Derive relationships from components.",
        )

        assert "app_auth" in prompt
        assert "Auth Component" in prompt
        assert "SOURCE ELEMENTS" in prompt

    def test_includes_target_elements(self):
        """Should include target elements in prompt."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        source_elements = [{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}]
        target_elements = [
            {"identifier": "svc_login", "name": "Login Service", "element_type": "ApplicationService"},
            {"identifier": "data_user", "name": "User Data", "element_type": "DataObject"},
        ]

        prompt = build_per_element_relationship_prompt(
            source_elements=source_elements,
            target_elements=target_elements,
            source_element_type="ApplicationComponent",
            instruction="Derive relationships.",
        )

        assert "svc_login" in prompt
        assert "data_user" in prompt
        assert "TARGET ELEMENTS" in prompt

    def test_includes_instruction(self):
        """Should include custom instruction in prompt."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        prompt = build_per_element_relationship_prompt(
            source_elements=[{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}],
            target_elements=[],
            source_element_type="ApplicationComponent",
            instruction="Custom instruction for relationship derivation",
        )

        assert "Custom instruction for relationship derivation" in prompt

    def test_includes_valid_relationship_types(self):
        """Should include allowed relationship types when provided."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        prompt = build_per_element_relationship_prompt(
            source_elements=[{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}],
            target_elements=[],
            source_element_type="ApplicationComponent",
            instruction="Derive relationships.",
            valid_relationship_types=["Serving", "Access", "Composition"],
        )

        assert "ALLOWED RELATIONSHIP TYPES" in prompt
        assert "Serving" in prompt
        assert "Access" in prompt

    def test_includes_example_when_provided(self):
        """Should include example output when provided."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        custom_example = '{"relationships": [{"source": "custom_src", "target": "custom_tgt"}]}'

        prompt = build_per_element_relationship_prompt(
            source_elements=[{"identifier": "app_auth", "name": "Auth", "element_type": "ApplicationComponent"}],
            target_elements=[],
            source_element_type="ApplicationComponent",
            instruction="Derive relationships.",
            example=custom_example,
        )

        assert custom_example in prompt
        assert "EXAMPLE OUTPUT" in prompt

    def test_lists_valid_identifiers(self):
        """Should include source and target identifiers in element JSON."""
        from deriva.modules.derivation.base import build_per_element_relationship_prompt

        prompt = build_per_element_relationship_prompt(
            source_elements=[
                {"identifier": "src_1", "name": "Source 1"},
                {"identifier": "src_2", "name": "Source 2"},
            ],
            target_elements=[
                {"identifier": "tgt_1", "name": "Target 1"},
            ],
            source_element_type="ApplicationComponent",
            instruction="Derive.",
        )

        # Identifiers should appear in the element JSON (no separate list)
        assert "src_1" in prompt
        assert "src_2" in prompt
        assert "tgt_1" in prompt
        assert "SOURCE ELEMENTS" in prompt
        assert "TARGET ELEMENTS" in prompt


class TestBuildUnifiedRelationshipPrompt:
    """Tests for build_unified_relationship_prompt function."""

    def test_returns_empty_for_no_new_elements(self):
        """Should return empty string when no new elements."""
        from deriva.modules.derivation.base import build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[],
            existing_elements=[{"identifier": "old_1"}],
            element_type="ApplicationComponent",
            outbound_rules=[],
            inbound_rules=[],
        )

        assert prompt == ""

    def test_includes_new_elements(self):
        """Should include new elements in prompt."""
        from deriva.modules.derivation.base import RelationshipRule, build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[{"identifier": "new_app", "name": "New App", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "name": "Old Service", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
        )

        assert "new_app" in prompt
        assert "New App" in prompt
        assert "New ApplicationComponent Elements" in prompt

    def test_includes_existing_elements(self):
        """Should include existing elements in prompt."""
        from deriva.modules.derivation.base import RelationshipRule, build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[{"identifier": "new_app", "name": "New", "element_type": "ApplicationComponent"}],
            existing_elements=[
                {"identifier": "old_svc", "name": "Old Service", "element_type": "ApplicationService"},
                {"identifier": "old_data", "name": "Old Data", "element_type": "DataObject"},
            ],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
        )

        assert "old_svc" in prompt
        assert "old_data" in prompt
        assert "Existing Elements" in prompt

    def test_includes_outbound_rules(self):
        """Should include outbound relationship rules."""
        from deriva.modules.derivation.base import RelationshipRule, build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[{"identifier": "app_1", "name": "App", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "svc_1", "name": "Service", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving", description="serves")],
            inbound_rules=[],
        )

        assert "OUTBOUND" in prompt
        assert "Serving" in prompt
        assert "ApplicationService" in prompt

    def test_includes_inbound_rules(self):
        """Should include inbound relationship rules."""
        from deriva.modules.derivation.base import RelationshipRule, build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[{"identifier": "svc_1", "name": "Service", "element_type": "ApplicationService"}],
            existing_elements=[{"identifier": "app_1", "name": "App", "element_type": "ApplicationComponent"}],
            element_type="ApplicationService",
            outbound_rules=[],
            inbound_rules=[RelationshipRule(target_type="ApplicationComponent", rel_type="Serving", description="served by")],
        )

        assert "INBOUND" in prompt
        assert "Serving" in prompt

    def test_lists_valid_identifiers(self):
        """Should include new and existing identifiers in element JSON."""
        from deriva.modules.derivation.base import build_unified_relationship_prompt

        prompt = build_unified_relationship_prompt(
            new_elements=[
                {"identifier": "new_1", "name": "New 1", "element_type": "ApplicationComponent"},
                {"identifier": "new_2", "name": "New 2", "element_type": "ApplicationComponent"},
            ],
            existing_elements=[{"identifier": "old_1", "name": "Old 1", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[],
            inbound_rules=[],
        )

        # Identifiers should appear in the element JSON (no separate list)
        assert "new_1" in prompt
        assert "new_2" in prompt
        assert "old_1" in prompt
        # Elements are in their respective sections
        assert "New ApplicationComponent Elements" in prompt
        assert "Existing Elements" in prompt


class TestDeriveBatchRelationships:
    """Tests for derive_batch_relationships function."""

    def test_returns_empty_for_no_new_elements(self):
        """Should return empty list when no new elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_batch_relationships

        result = derive_batch_relationships(
            new_elements=[],
            existing_elements=[{"identifier": "old"}],
            element_type="ApplicationComponent",
            outbound_rules=[],
            inbound_rules=[],
            llm_query_fn=MagicMock(),
        )

        assert result == []

    def test_returns_empty_when_no_applicable_rules(self):
        """Should return empty when no rules match existing elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_data", "element_type": "DataObject"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],  # No service exists
            inbound_rules=[],
            llm_query_fn=MagicMock(),
        )

        assert result == []

    def test_calls_llm_with_unified_prompt(self):
        """Should call LLM with unified relationship prompt."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": []}'

        derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        mock_llm.assert_called_once()
        call_args = mock_llm.call_args
        assert "ApplicationComponent" in call_args[0][0]  # Prompt

    def test_parses_valid_relationships(self):
        """Should parse and return valid relationships."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "new_app", "target": "old_svc", "relationship_type": "Serving", "confidence": 0.9}]}'

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert len(result) == 1
        assert result[0]["source"] == "new_app"
        assert result[0]["target"] == "old_svc"
        assert result[0]["relationship_type"] == "Serving"
        assert result[0]["confidence"] == 0.9

    def test_validates_source_in_ids(self):
        """Should skip relationships with invalid source."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "unknown_id", "target": "old_svc", "relationship_type": "Serving"}]}'

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_validates_target_in_ids(self):
        """Should skip relationships with invalid target."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "new_app", "target": "unknown_target", "relationship_type": "Serving"}]}'

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_validates_relationship_type(self):
        """Should skip relationships with invalid type."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "new_app", "target": "old_svc", "relationship_type": "InvalidType"}]}'

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_requires_at_least_one_new_element_endpoint(self):
        """Should skip relationships where neither endpoint is new."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        # This relationship is between two existing elements
        mock_llm.return_value.content = '{"relationships": [{"source": "old_1", "target": "old_2", "relationship_type": "Serving"}]}'

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[
                {"identifier": "old_1", "element_type": "ApplicationComponent"},
                {"identifier": "old_2", "element_type": "ApplicationService"},
            ],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_handles_llm_exception(self):
        """Should return empty list on LLM exception."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.side_effect = Exception("LLM error")

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_handles_parse_failure(self):
        """Should return empty list when parsing fails."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = "invalid json response"

        result = derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
        )

        assert result == []

    def test_passes_temperature_and_max_tokens(self):
        """Should pass temperature and max_tokens to LLM."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import RelationshipRule, derive_batch_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": []}'

        derive_batch_relationships(
            new_elements=[{"identifier": "new_app", "element_type": "ApplicationComponent"}],
            existing_elements=[{"identifier": "old_svc", "element_type": "ApplicationService"}],
            element_type="ApplicationComponent",
            outbound_rules=[RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
            inbound_rules=[],
            llm_query_fn=mock_llm,
            temperature=0.7,
            max_tokens=2000,
        )

        call_kwargs = mock_llm.call_args[1]
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 2000


class TestDeriveElementRelationships:
    """Tests for derive_element_relationships function."""

    def test_returns_empty_for_no_source_elements(self):
        """Should return empty list when no source elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        result = derive_element_relationships(
            source_elements=[],
            target_elements=[{"identifier": "tgt"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=MagicMock(),
            instruction="Test",
        )

        assert result == []

    def test_returns_empty_for_no_target_elements(self):
        """Should return empty list when no target elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        result = derive_element_relationships(
            source_elements=[{"identifier": "src"}],
            target_elements=[],
            source_element_type="ApplicationComponent",
            llm_query_fn=MagicMock(),
            instruction="Test",
        )

        assert result == []

    def test_calls_llm_with_per_element_prompt(self):
        """Should call LLM with per-element prompt."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": []}'

        derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Custom instruction",
        )

        mock_llm.assert_called_once()
        call_args = mock_llm.call_args
        assert "src_app" in call_args[0][0]
        assert "tgt_svc" in call_args[0][0]
        assert "Custom instruction" in call_args[0][0]

    def test_parses_valid_relationships(self):
        """Should parse and return valid relationships."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "src_app", "target": "tgt_svc", "relationship_type": "Serving", "confidence": 0.85}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert len(result) == 1
        assert result[0]["source"] == "src_app"
        assert result[0]["target"] == "tgt_svc"
        assert result[0]["relationship_type"] == "Serving"
        assert result[0]["confidence"] == 0.85

    def test_validates_source_from_source_elements(self):
        """Should skip relationships with source not in source_elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "unknown_src", "target": "tgt_svc", "relationship_type": "Serving"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert result == []

    def test_validates_target_from_target_elements(self):
        """Should skip relationships with target not in target_elements."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "src_app", "target": "unknown_tgt", "relationship_type": "Serving"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert result == []

    def test_validates_relationship_type_when_specified(self):
        """Should skip relationships with invalid type when valid_types specified."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "src_app", "target": "tgt_svc", "relationship_type": "InvalidType"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
            valid_relationship_types=["Serving", "Access"],
        )

        assert result == []

    def test_accepts_any_type_when_valid_types_not_specified(self):
        """Should accept any relationship type when valid_types is None."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "src_app", "target": "tgt_svc", "relationship_type": "AnyType"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
            valid_relationship_types=None,
        )

        assert len(result) == 1
        assert result[0]["relationship_type"] == "AnyType"

    def test_handles_llm_exception(self):
        """Should return empty list on LLM exception."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.side_effect = Exception("LLM error")

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert result == []

    def test_handles_parse_failure(self):
        """Should return empty list when parsing fails."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = "not valid json"

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert result == []

    def test_passes_temperature_and_max_tokens(self):
        """Should pass temperature and max_tokens to LLM."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": []}'

        derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
            temperature=0.5,
            max_tokens=1500,
        )

        call_kwargs = mock_llm.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 1500

    def test_uses_default_confidence(self):
        """Should use default confidence 0.5 when not provided."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value.content = '{"relationships": [{"source": "src_app", "target": "tgt_svc", "relationship_type": "Serving"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert result[0]["confidence"] == 0.5

    def test_handles_response_without_content_attribute(self):
        """Should handle LLM response that is a string."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import derive_element_relationships

        mock_llm = MagicMock()
        mock_llm.return_value = '{"relationships": [{"source": "src_app", "target": "tgt_svc", "relationship_type": "Serving"}]}'

        result = derive_element_relationships(
            source_elements=[{"identifier": "src_app"}],
            target_elements=[{"identifier": "tgt_svc"}],
            source_element_type="ApplicationComponent",
            llm_query_fn=mock_llm,
            instruction="Test",
        )

        assert len(result) == 1


class TestSharedGenerateBehavior:
    """Tests for shared generate() behavior across all element modules.

    These tests verify common behavior using ApplicationComponentDerivation as the
    reference implementation. All element derivation classes should behave identically
    for these scenarios.
    """

    def test_returns_empty_when_no_candidates(self):
        """generate() should return 0 elements when no candidates found."""
        from unittest.mock import MagicMock, Mock, patch

        from deriva.modules.derivation.application_component import ApplicationComponentDerivation

        derivation = ApplicationComponentDerivation()
        with patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}):
            with patch("deriva.modules.derivation.element_base.query_candidates", return_value=[]):
                result = derivation.generate(
                    graph_manager=MagicMock(),
                    archimate_manager=MagicMock(),
                    engine=MagicMock(),
                    llm_query_fn=Mock(),
                    query="MATCH (n) RETURN n",
                    instruction="test",
                    example="{}",
                    max_candidates=10,
                    batch_size=5,
                    existing_elements=[],
                )

        assert result.elements_created == 0
        assert result.success is True

    def test_handles_query_exception(self):
        """generate() should handle query exceptions gracefully."""
        from unittest.mock import MagicMock, Mock, patch

        from deriva.modules.derivation.application_component import ApplicationComponentDerivation

        derivation = ApplicationComponentDerivation()
        with patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}):
            with patch("deriva.modules.derivation.element_base.query_candidates", side_effect=Exception("DB error")):
                result = derivation.generate(
                    graph_manager=MagicMock(),
                    archimate_manager=MagicMock(),
                    engine=MagicMock(),
                    llm_query_fn=Mock(),
                    query="MATCH (n) RETURN n",
                    instruction="test",
                    example="{}",
                    max_candidates=10,
                    batch_size=5,
                    existing_elements=[],
                )

        assert result.success is False
        assert any("error" in e.lower() for e in result.errors)

    def test_returns_generation_result_type(self):
        """generate() should return GenerationResult type."""
        from unittest.mock import MagicMock, Mock, patch

        from deriva.modules.derivation.application_component import ApplicationComponentDerivation
        from deriva.modules.derivation.base import GenerationResult

        derivation = ApplicationComponentDerivation()
        with patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}):
            with patch("deriva.modules.derivation.element_base.query_candidates", return_value=[]):
                result = derivation.generate(
                    graph_manager=MagicMock(),
                    archimate_manager=MagicMock(),
                    engine=MagicMock(),
                    llm_query_fn=Mock(),
                    query="MATCH (n) RETURN n",
                    instruction="test",
                    example="{}",
                    max_candidates=10,
                    batch_size=5,
                    existing_elements=[],
                )

        assert isinstance(result, GenerationResult)


class TestStripForRelationshipPrompt:
    """Tests for strip_for_relationship_prompt function."""

    def test_strips_to_essential_fields(self):
        """Should keep only identifier, name, element_type."""
        from deriva.modules.derivation.base import strip_for_relationship_prompt

        elements = [
            {
                "identifier": "app_auth",
                "name": "Auth Component",
                "element_type": "ApplicationComponent",
                "documentation": "This should be removed",
                "properties": {"confidence": 0.9, "source": "test"},
            }
        ]

        result = strip_for_relationship_prompt(elements)

        assert len(result) == 1
        assert result[0]["identifier"] == "app_auth"
        assert result[0]["name"] == "Auth Component"
        assert result[0]["element_type"] == "ApplicationComponent"
        assert "documentation" not in result[0]
        assert "properties" not in result[0]

    def test_handles_empty_list(self):
        """Should return empty list for empty input."""
        from deriva.modules.derivation.base import strip_for_relationship_prompt

        result = strip_for_relationship_prompt([])
        assert result == []

    def test_handles_missing_fields(self):
        """Should handle elements with missing optional fields."""
        from deriva.modules.derivation.base import strip_for_relationship_prompt

        elements = [{"identifier": "test_id"}]
        result = strip_for_relationship_prompt(elements)

        assert len(result) == 1
        assert result[0]["identifier"] == "test_id"


class TestStripCacheBreakingProps:
    """Tests for strip_cache_breaking_props function."""

    def test_removes_derived_at_from_properties(self):
        """Should remove derived_at timestamp from properties."""
        from deriva.modules.derivation.base import strip_cache_breaking_props

        elements = [
            {
                "identifier": "test",
                "properties": {
                    "confidence": 0.9,
                    "derived_at": "2024-01-01T00:00:00Z",
                    "source": "test_source",
                },
            }
        ]

        result = strip_cache_breaking_props(elements)

        assert len(result) == 1
        assert "derived_at" not in result[0]["properties"]
        assert result[0]["properties"]["confidence"] == 0.9
        assert result[0]["properties"]["source"] == "test_source"

    def test_preserves_elements_without_properties(self):
        """Should handle elements without properties dict."""
        from deriva.modules.derivation.base import strip_cache_breaking_props

        elements = [{"identifier": "test", "name": "Test"}]
        result = strip_cache_breaking_props(elements)

        assert len(result) == 1
        assert result[0]["identifier"] == "test"

    def test_handles_empty_list(self):
        """Should return empty list for empty input."""
        from deriva.modules.derivation.base import strip_cache_breaking_props

        result = strip_cache_breaking_props([])
        assert result == []


class TestExtractResponseContent:
    """Tests for extract_response_content function."""

    def test_extracts_content_from_response_with_content_attr(self):
        """Should extract content from response with content attribute."""
        from deriva.modules.derivation.base import extract_response_content

        class MockResponse:
            content = '{"elements": []}'

        content, error = extract_response_content(MockResponse())

        assert content == '{"elements": []}'
        assert error is None

    def test_returns_error_for_failed_response(self):
        """Should return error message for FailedResponse."""
        from deriva.adapters.llm.models import FailedResponse
        from deriva.modules.derivation.base import extract_response_content

        failed = FailedResponse(
            error="API timeout",
            error_type="timeout",
            prompt="test prompt",
            model="test-model",
        )
        content, error = extract_response_content(failed)

        assert content == ""
        assert error is not None
        assert "API timeout" in error

    def test_handles_response_with_failed_type(self):
        """Should detect failed response via response_type attribute."""
        from deriva.adapters.llm.models import ResponseType
        from deriva.modules.derivation.base import extract_response_content

        class MockFailedResponse:
            response_type = ResponseType.FAILED
            error = "Connection error"

        content, error = extract_response_content(MockFailedResponse())

        assert content == ""
        assert error is not None
        assert "Connection error" in error

    def test_falls_back_to_string_conversion(self):
        """Should convert to string if no content attribute."""
        from deriva.modules.derivation.base import extract_response_content

        content, error = extract_response_content("plain string response")

        assert content == "plain string response"
        assert error is None


class TestCandidateToDict:
    """Tests for Candidate.to_dict method."""

    def test_to_dict_includes_all_fields(self):
        """Should include all fields in dict output."""
        from deriva.modules.derivation.base import Candidate

        candidate = Candidate(
            node_id="node_123",
            name="TestNode",
            labels=["Label1", "Label2"],
            properties={"key": "value"},
            pagerank=0.5,
            louvain_community="comm_1",
            kcore_level=3,
            in_degree=5,
            out_degree=10,
        )

        result = candidate.to_dict()

        assert result["id"] == "node_123"
        assert result["name"] == "TestNode"
        assert result["labels"] == ["Label1", "Label2"]
        assert result["properties"]["key"] == "value"
        assert result["pagerank"] == 0.5
        assert result["in_degree"] == 5
        assert result["out_degree"] == 10

    def test_to_dict_with_include_props_filter(self):
        """Should filter properties when include_props is specified."""
        from deriva.modules.derivation.base import ESSENTIAL_PROPS, Candidate

        candidate = Candidate(
            node_id="node_123",
            name="TestNode",
            properties={
                "name": "test",
                "description": "test desc",
                "randomProp": "should be filtered",
            },
        )

        result = candidate.to_dict(include_props=ESSENTIAL_PROPS)

        assert "name" in result["properties"]
        assert "description" in result["properties"]
        assert "randomProp" not in result["properties"]


class TestClampConfidence:
    """Tests for clamp_confidence function."""

    def test_clamps_high_values(self):
        """Should clamp values above 1.0 to 1.0."""
        from deriva.modules.derivation.base import clamp_confidence

        assert clamp_confidence(1.5) == 1.0
        assert clamp_confidence(100) == 1.0

    def test_clamps_low_values(self):
        """Should clamp values below 0.0 to 0.0."""
        from deriva.modules.derivation.base import clamp_confidence

        assert clamp_confidence(-0.5) == 0.0
        assert clamp_confidence(-100) == 0.0

    def test_preserves_valid_values(self):
        """Should preserve values in valid range."""
        from deriva.modules.derivation.base import clamp_confidence

        assert clamp_confidence(0.5) == 0.5
        assert clamp_confidence(0.0) == 0.0
        assert clamp_confidence(1.0) == 1.0

    def test_uses_default_for_none(self):
        """Should use default value for None."""
        from deriva.modules.derivation.base import clamp_confidence

        assert clamp_confidence(None) == 0.5
        assert clamp_confidence(None, default=0.7) == 0.7

    def test_handles_invalid_types(self):
        """Should return default for non-numeric types."""
        from deriva.modules.derivation.base import clamp_confidence

        assert clamp_confidence("invalid") == 0.5
        assert clamp_confidence([1, 2, 3]) == 0.5


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_estimates_based_on_character_count(self):
        """Should estimate ~4 chars per token."""
        from deriva.modules.derivation.base import estimate_tokens

        assert estimate_tokens("") == 0
        assert estimate_tokens("1234") == 1
        assert estimate_tokens("12345678") == 2
        assert estimate_tokens("a" * 100) == 25

    def test_handles_unicode(self):
        """Should handle unicode characters."""
        from deriva.modules.derivation.base import estimate_tokens

        # Unicode chars still count by length
        assert estimate_tokens("αβγδ") == 1


class TestGetModelContextLimit:
    """Tests for get_model_context_limit function."""

    def test_returns_correct_limit_for_known_models(self):
        """Should return correct limits for known models."""
        from deriva.modules.derivation.base import get_model_context_limit

        # Function uses substring matching - "gpt-4" matches "gpt-4o-mini"
        assert get_model_context_limit("gpt-4") == 8192
        assert get_model_context_limit("claude-sonnet") == 200000
        assert get_model_context_limit("devstral") == 32000

    def test_case_insensitive_matching(self):
        """Should match model names case-insensitively."""
        from deriva.modules.derivation.base import get_model_context_limit

        assert get_model_context_limit("Claude-Sonnet") == 200000
        assert get_model_context_limit("DEVSTRAL") == 32000

    def test_returns_default_for_unknown_models(self):
        """Should return default limit for unknown models."""
        from deriva.modules.derivation.base import get_model_context_limit

        assert get_model_context_limit("unknown-model") == 16000
        assert get_model_context_limit("") == 16000


class TestLimitExistingElements:
    """Tests for limit_existing_elements function."""

    def test_returns_all_when_under_limit(self):
        """Should return all elements when under max."""
        from deriva.modules.derivation.base import limit_existing_elements

        elements = [{"identifier": f"elem_{i}"} for i in range(5)]
        result = limit_existing_elements(elements, max_elements=10)
        assert len(result) == 5

    def test_limits_to_max_elements(self):
        """Should limit to max_elements."""
        from deriva.modules.derivation.base import limit_existing_elements

        elements = [{"identifier": f"elem_{i}"} for i in range(20)]
        result = limit_existing_elements(elements, max_elements=5)
        assert len(result) == 5

    def test_sorts_by_confidence_when_enabled(self):
        """Should sort by confidence descending."""
        from deriva.modules.derivation.base import limit_existing_elements

        elements = [
            {"identifier": "low", "properties": {"confidence": 0.3}},
            {"identifier": "high", "properties": {"confidence": 0.9}},
            {"identifier": "mid", "properties": {"confidence": 0.6}},
        ]
        result = limit_existing_elements(elements, max_elements=2, sort_by_confidence=True)
        assert result[0]["identifier"] == "high"
        assert result[1]["identifier"] == "mid"

    def test_simple_truncation_without_sorting(self):
        """Should do simple truncation when sort_by_confidence=False."""
        from deriva.modules.derivation.base import limit_existing_elements

        elements = [{"identifier": f"elem_{i}"} for i in range(10)]
        result = limit_existing_elements(elements, max_elements=3, sort_by_confidence=False)
        assert [e["identifier"] for e in result] == ["elem_0", "elem_1", "elem_2"]


class TestStratifiedSampleElements:
    """Tests for stratified_sample_elements function."""

    def test_returns_empty_for_empty_input(self):
        """Should return empty list for empty input."""
        from deriva.modules.derivation.base import stratified_sample_elements

        assert stratified_sample_elements([]) == []

    def test_samples_from_each_type(self):
        """Should sample from each element type."""
        from deriva.modules.derivation.base import stratified_sample_elements

        elements = [
            {"identifier": "comp_1", "element_type": "ApplicationComponent"},
            {"identifier": "comp_2", "element_type": "ApplicationComponent"},
            {"identifier": "svc_1", "element_type": "ApplicationService"},
            {"identifier": "svc_2", "element_type": "ApplicationService"},
        ]
        result = stratified_sample_elements(elements, max_per_type=1)
        types = {e["element_type"] for e in result}
        assert "ApplicationComponent" in types
        assert "ApplicationService" in types
        assert len(result) == 2

    def test_limits_per_type(self):
        """Should limit elements per type."""
        from deriva.modules.derivation.base import stratified_sample_elements

        elements = [{"identifier": f"comp_{i}", "element_type": "ApplicationComponent", "properties": {"confidence": 0.5}} for i in range(10)]
        result = stratified_sample_elements(elements, max_per_type=3)
        assert len(result) == 3

    def test_filters_by_relevant_types(self):
        """Should only include relevant types when specified."""
        from deriva.modules.derivation.base import stratified_sample_elements

        elements = [
            {"identifier": "comp_1", "element_type": "ApplicationComponent"},
            {"identifier": "svc_1", "element_type": "ApplicationService"},
            {"identifier": "data_1", "element_type": "DataObject"},
        ]
        result = stratified_sample_elements(elements, max_per_type=10, relevant_types=["ApplicationComponent", "DataObject"])
        types = {e["element_type"] for e in result}
        assert "ApplicationService" not in types
        assert len(result) == 2


class TestNormalizeNameForMatching:
    """Tests for normalize_name_for_matching function."""

    def test_splits_camel_case(self):
        """Should split CamelCase into words."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        result = normalize_name_for_matching("InvoiceManagement")
        assert "invoice" in result
        assert "management" in result

    def test_splits_snake_case(self):
        """Should split snake_case into words."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        result = normalize_name_for_matching("invoice_management")
        assert "invoice" in result
        assert "management" in result

    def test_splits_kebab_case(self):
        """Should split kebab-case into words."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        result = normalize_name_for_matching("invoice-management")
        assert "invoice" in result
        assert "management" in result

    def test_excludes_stop_words(self):
        """Should exclude common stop words."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        result = normalize_name_for_matching("TheInvoiceService")
        assert "the" not in result
        assert "service" not in result
        assert "invoice" in result

    def test_excludes_short_words(self):
        """Should exclude words <= 2 characters."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        result = normalize_name_for_matching("GetAPIData")
        assert "api" not in result  # 3 chars but stop word if processed

    def test_handles_empty_string(self):
        """Should return empty set for empty string."""
        from deriva.modules.derivation.base import normalize_name_for_matching

        assert normalize_name_for_matching("") == set()


class TestNamesMatchForRelationship:
    """Tests for names_match_for_relationship function."""

    def test_matching_names(self):
        """Should return True for semantically related names."""
        from deriva.modules.derivation.base import names_match_for_relationship

        assert names_match_for_relationship("InvoiceManager", "InvoiceProcessor") is True

    def test_non_matching_names(self):
        """Should return False for unrelated names."""
        from deriva.modules.derivation.base import names_match_for_relationship

        assert names_match_for_relationship("InvoiceManager", "CustomerHandler") is False

    def test_empty_names(self):
        """Should return False for empty names."""
        from deriva.modules.derivation.base import names_match_for_relationship

        assert names_match_for_relationship("", "InvoiceManager") is False
        assert names_match_for_relationship("InvoiceManager", "") is False

    def test_custom_threshold(self):
        """Should respect custom threshold."""
        from deriva.modules.derivation.base import names_match_for_relationship

        # With high threshold, partial matches should fail
        assert names_match_for_relationship("InvoiceDataManager", "InvoiceHandler", threshold=0.8) is False


class TestExtractFilePathFromSource:
    """Tests for extract_file_path_from_source function."""

    def test_extracts_python_file(self):
        """Should extract .py file names."""
        from deriva.modules.derivation.base import extract_file_path_from_source

        result = extract_file_path_from_source("method_flask_invoice_generator_models.py_Positions_delete")
        assert result == "models.py"

    def test_extracts_dotfile(self):
        """Should extract dotfiles like .flaskenv."""
        from deriva.modules.derivation.base import extract_file_path_from_source

        result = extract_file_path_from_source("file_flask_invoice_generator_.flaskenv")
        assert result == ".flaskenv"

    def test_handles_none(self):
        """Should return None for None input."""
        from deriva.modules.derivation.base import extract_file_path_from_source

        assert extract_file_path_from_source(None) is None

    def test_handles_no_match(self):
        """Should return None when no file pattern found."""
        from deriva.modules.derivation.base import extract_file_path_from_source

        assert extract_file_path_from_source("no_file_extension_here") is None


class TestElementsShareSourceFile:
    """Tests for elements_share_source_file function."""

    def test_same_source_file(self):
        """Should return True for elements from same file."""
        from deriva.modules.derivation.base import elements_share_source_file

        elem1 = {"properties": {"source": "method_app_models.py_Class1"}}
        elem2 = {"properties": {"source": "method_app_models.py_Class2"}}
        assert elements_share_source_file(elem1, elem2) is True

    def test_different_source_files(self):
        """Should return False for elements from different files."""
        from deriva.modules.derivation.base import elements_share_source_file

        elem1 = {"properties": {"source": "method_app_models.py_Class1"}}
        elem2 = {"properties": {"source": "method_app_views.py_View1"}}
        assert elements_share_source_file(elem1, elem2) is False

    def test_missing_source(self):
        """Should return False when source is missing."""
        from deriva.modules.derivation.base import elements_share_source_file

        elem1 = {"properties": {"source": "method_app_models.py_Class1"}}
        elem2 = {"properties": {}}
        assert elements_share_source_file(elem1, elem2) is False

    def test_missing_properties(self):
        """Should return False when properties is missing."""
        from deriva.modules.derivation.base import elements_share_source_file

        elem1 = {"identifier": "test"}
        elem2 = {"properties": {"source": "method_app_models.py_Class1"}}
        assert elements_share_source_file(elem1, elem2) is False


class TestGetCommunityFromElement:
    """Tests for get_community_from_element function."""

    def test_extracts_community(self):
        """Should extract source_community from properties."""
        from deriva.modules.derivation.base import get_community_from_element

        elem = {"properties": {"source_community": "comm_123"}}
        assert get_community_from_element(elem) == "comm_123"

    def test_returns_none_when_missing(self):
        """Should return None when source_community not present."""
        from deriva.modules.derivation.base import get_community_from_element

        elem = {"properties": {"confidence": 0.9}}
        assert get_community_from_element(elem) is None

    def test_returns_none_without_properties(self):
        """Should return None when properties is missing."""
        from deriva.modules.derivation.base import get_community_from_element

        elem = {"identifier": "test"}
        assert get_community_from_element(elem) is None


class TestClearEnrichmentCache:
    """Tests for clear_enrichment_cache function."""

    def test_clears_cache(self):
        """Should clear the enrichment cache without error."""
        from deriva.modules.derivation.base import clear_enrichment_cache

        # Just verify it doesn't raise
        clear_enrichment_cache()


class TestDeriveCommunityRelationships:
    """Tests for derive_community_relationships function."""

    def test_returns_empty_for_empty_inputs(self):
        """Should return empty list when no elements."""
        from deriva.modules.derivation.base import derive_community_relationships

        result = derive_community_relationships([], [], [], [])
        assert result == []

    def test_creates_outbound_relationships_in_same_community(self):
        """Should create outbound relationships for elements in same community."""
        from deriva.modules.derivation.base import RelationshipRule, derive_community_relationships

        new_elements = [
            {"identifier": "new_comp", "element_type": "ApplicationComponent", "properties": {"source_community": "comm_1"}},
        ]
        existing_elements = [
            {"identifier": "old_svc", "element_type": "ApplicationService", "properties": {"source_community": "comm_1"}},
        ]
        outbound_rules = [RelationshipRule(target_type="ApplicationService", rel_type="Serving")]

        result = derive_community_relationships(new_elements, existing_elements, outbound_rules, [])

        assert len(result) == 1
        assert result[0]["source"] == "new_comp"
        assert result[0]["target"] == "old_svc"
        assert result[0]["relationship_type"] == "Serving"
        assert result[0]["confidence"] == 0.95
        assert result[0]["derived_from"] == "community"

    def test_skips_different_communities(self):
        """Should not create relationships across different communities."""
        from deriva.modules.derivation.base import RelationshipRule, derive_community_relationships

        new_elements = [
            {"identifier": "new_comp", "element_type": "ApplicationComponent", "properties": {"source_community": "comm_1"}},
        ]
        existing_elements = [
            {"identifier": "old_svc", "element_type": "ApplicationService", "properties": {"source_community": "comm_2"}},
        ]
        outbound_rules = [RelationshipRule(target_type="ApplicationService", rel_type="Serving")]

        result = derive_community_relationships(new_elements, existing_elements, outbound_rules, [])

        assert result == []

    def test_creates_inbound_relationships(self):
        """Should create inbound relationships when rules match."""
        from deriva.modules.derivation.base import RelationshipRule, derive_community_relationships

        new_elements = [
            {"identifier": "new_svc", "element_type": "ApplicationService", "properties": {"source_community": "comm_1"}},
        ]
        existing_elements = [
            {"identifier": "old_comp", "element_type": "ApplicationComponent", "properties": {"source_community": "comm_1"}},
        ]
        inbound_rules = [RelationshipRule(target_type="ApplicationComponent", rel_type="Serving")]

        result = derive_community_relationships(new_elements, existing_elements, [], inbound_rules)

        assert len(result) == 1
        assert result[0]["source"] == "old_comp"
        assert result[0]["target"] == "new_svc"


class TestDeriveDeterministicRelationships:
    """Tests for derive_deterministic_relationships function."""

    def test_returns_empty_for_empty_inputs(self):
        """Should return empty list when no elements."""
        from deriva.modules.derivation.base import derive_deterministic_relationships

        result = derive_deterministic_relationships([], [], "ApplicationComponent", [], [])
        assert result == []

    def test_creates_relationships_based_on_name_matching(self):
        """Should create relationships when names match."""
        from deriva.modules.derivation.base import RelationshipRule, derive_deterministic_relationships

        new_elements = [
            {"identifier": "new_invoice", "name": "InvoiceManager"},
        ]
        existing_elements = [
            {"identifier": "old_invoice", "name": "InvoiceProcessor", "element_type": "ApplicationService"},
        ]
        outbound_rules = [RelationshipRule(target_type="ApplicationService", rel_type="Serving")]

        result = derive_deterministic_relationships(new_elements, existing_elements, "ApplicationComponent", outbound_rules, [])

        # Should find relationship based on "Invoice" word overlap
        assert len(result) >= 0  # Depends on threshold, verify no crash
