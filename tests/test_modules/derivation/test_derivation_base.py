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
        assert result["community"] == "comm_1"
        assert result["kcore"] == 3
        assert result["is_bridge"] is True
        assert result["in_degree"] == 5
        assert result["out_degree"] == 10


class TestGetEnrichments:
    """Tests for get_enrichments function."""

    def test_returns_enrichments_from_engine(self):
        """Should fetch enrichments from DuckDB engine."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import get_enrichments

        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchall.return_value = [
            ("node_1", 0.5, "comm_1", 2, True, 3, 4),
            ("node_2", 0.3, "comm_2", 1, False, 1, 2),
        ]

        result = get_enrichments(mock_engine)

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

        from deriva.modules.derivation.base import get_enrichments

        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchall.return_value = [
            ("node_1", None, None, None, None, None, None),
        ]

        result = get_enrichments(mock_engine)

        assert result["node_1"]["pagerank"] == 0.0
        assert result["node_1"]["louvain_community"] is None
        assert result["node_1"]["kcore_level"] == 0
        assert result["node_1"]["is_articulation_point"] is False
        assert result["node_1"]["in_degree"] == 0
        assert result["node_1"]["out_degree"] == 0

    def test_returns_empty_on_error(self):
        """Should return empty dict on database error."""
        from unittest.mock import MagicMock

        from deriva.modules.derivation.base import get_enrichments

        mock_engine = MagicMock()
        mock_engine.execute.side_effect = Exception("DB error")

        result = get_enrichments(mock_engine)

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
