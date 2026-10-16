"""Cooperation between deployable units, from structure (no LLM): which unit uses which (CONSUMES, with the
channel and the evidence) and which sends messages to which (SENDS_TO)."""

from __future__ import annotations

from deriva.modules.extraction.cooperation import CooperationRules, detect_links

RULES = CooperationRules(
    send_markers=("convertAndSend", ".publish("),
    listen_markers=("@JmsListener", ".subscribe("),
)


def _unit(name, path=None, members=()):
    return {"id": f"unit::r::{name}", "path": path or f"r/{name}", "name": name, "members": list(members)}


def _links(files, units, services=(), code_edges=(), rules=RULES):
    return sorted(
        (link.relation, link.source.split("::")[-1], link.target.split("::")[-1], link.channel, link.evidence)
        for link in detect_links(files, units, list(services), rules, list(code_edges))
    )


def test_an_endpoint_url_names_the_provider_by_service_name_or_port():
    units = [_unit("core"), _unit("billing"), _unit("web")]
    files = {
        "r/core/src/main/resources/application.properties": "server.port = 8110\n",
        "r/billing/src/main/resources/application.properties": "core.baseURL=http://localhost:8110\n",
        # Tests are left out
        "r/billing/src/test/resources/application-test.properties": "other.url=http://localhost:9999\n",
        "r/web/.env": "API=http://localhost:7000\nSELF=http://localhost:7001\n",  # no unit listens on 7000
    }
    services = [
        {"name": "core", "unit": "unit::r::core", "environment": {}, "ports": [8110]},
        {"name": "web", "unit": "unit::r::web", "environment": {"CORE_URL": "http://core:8110"}, "ports": [7001]},
    ]

    assert _links(files, units, services) == [("CONSUMES", "billing", "core", "rest", "endpoint"), ("CONSUMES", "web", "core", "rest", "endpoint")]


def test_a_destination_shared_by_a_sender_and_a_listener_is_a_message_flow():
    units = [_unit("quotes"), _unit("policies"), _unit("risk")]
    files = {
        "r/quotes/app.properties": "request.queueName=quote-requests\n",
        "r/quotes/Producer.java": '@Value("${request.queueName}") String q; void send() { jms.convertAndSend(q, event); }',
        "r/policies/app.properties": "incoming.queueName=quote-requests\nrisk.queueName=newpolicies\nanswer.queueName=quote-answers\n",
        "r/policies/Consumer.java": '@JmsListener(destination = "${incoming.queueName}") void on(Event e) {}',
        "r/policies/RiskProducer.java": '@Value("${risk.queueName}") String q; void send() { jms.convertAndSend(q, e); }',
        "r/policies/AnswerListener.java": '@JmsListener(destination = "${answer.queueName}") void on(Event e) {}',  # nobody sends answers
        "r/risk/config.json": '{"mq": {"queueName": "newpolicies"}}',
        "r/risk/index.js": "channel.subscribe({destination: `/queue/${config.mq.queueName}`}, handler)",
    }

    links = detect_links(files, units, [], RULES, [])
    assert [(x.source.split("::")[-1], x.target.split("::")[-1], x.detail) for x in links] == [("policies", "risk", "newpolicies"), ("quotes", "policies", "quote-requests")]


def test_a_service_catalog_constant_names_the_unit_it_stands_for():
    units = [_unit("persistence", "r/services/tools.persistence"), _unit("auth", "r/services/tools.auth"), _unit("webui", "r/services/tools.webui")]
    files = {
        "r/utilities/registry/Service.java": 'public enum Service { PERSISTENCE("tools.persistence"), AUTH("tools.auth"); }',
        "r/services/tools.webui/Cart.java": "client.get(Service.PERSISTENCE, path); client.post(Service.AUTH, path);",
        "r/services/tools.persistence/Self.java": "register(Service.PERSISTENCE);",  # its own name
    }

    assert _links(files, units) == [("CONSUMES", "webui", "auth", "rest", "service catalog"), ("CONSUMES", "webui", "persistence", "rest", "service catalog")]


def test_a_gateway_route_that_a_unit_calls_names_the_provider():
    units = [_unit("frontend"), _unit("auth", "r/services/auth-service"), _unit("loan", "r/services/loan-service")]
    files = {
        "r/infrastructure/nginx/nginx.conf": (
            "upstream auth_service { server auth-service:8000; }\nupstream loan_service { server loan-service:8000; }\n"
            "server { location /api/v1/auth/ { proxy_pass http://auth_service/api/v1/auth/; }\n"
            "location /api/v1/loans { proxy_pass http://loan_service/api/v1/loans; }\n"
            "location / { proxy_pass http://frontend; } }"  # a catch-all route is no route to a unit
        ),
        "r/frontend/src/App.tsx": "const API_BASE = '/api/v1';\nconst login = () => api('/auth/login', {});",
        "r/services/loan-service/config.py": "API_PREFIX = '/api/v1'\nNAME = 'loan'",  # names the base, calls no route
    }
    services = [
        {"name": "auth-service", "unit": "unit::r::auth", "environment": {}, "ports": []},
        {"name": "loan-service", "unit": "unit::r::loan", "environment": {}, "ports": []},
        {"name": "frontend", "unit": "unit::r::frontend", "environment": {}, "ports": []},
    ]

    assert _links(files, units, services) == [("CONSUMES", "frontend", "auth", "rest", "gateway route")]


def test_a_code_edge_between_files_only_one_unit_each_holds_is_a_use():
    units = [_unit("online", "r/app", members=["r/app/cbl/MENU.cbl", "r/app/cpy/SHARED.cpy"]), _unit("auth", "r/app/auth", members=["r/app/auth/AUTH.cbl", "r/app/cpy/SHARED.cpy"])]
    edges = [("r/app/auth/AUTH.cbl", "r/app/cbl/MENU.cbl"), ("r/app/auth/AUTH.cbl", "r/app/cpy/SHARED.cpy")]  # the copybook is shared

    assert _links({}, units, code_edges=edges) == [("CONSUMES", "auth", "online", "code", "code edge")]
