"""Business processes from structure: the lifecycle of a business domain's status (enum or assigned code values),
ordered, with the units that reach each state; events where the lifecycle passes to another unit; documented
flows that name the states."""

from __future__ import annotations

from deriva.modules.extraction.lifecycles import LifecycleRules, detect_lifecycles

RULES = LifecycleRules(status_words=("status", "state"), flow_words=("flow", "lifecycle"), heading_noise=("flow",))


def _units(*names):
    return [{"id": f"unit::{n}", "path": f"r/{n}", "name": n} for n in names]


def test_an_enum_status_member_of_a_domain_is_its_lifecycle_in_declaration_order():
    files = {
        "r/a/domain/RequestStatus.java": (
            "public enum RequestStatus implements ValueObject {\n  REQUEST_SUBMITTED,\n  QUOTE_RECEIVED,\n  QUOTE_ACCEPTED;\n  boolean ok() { return true; }\n}"
        ),
        "r/a/Coordinator.java": "request.setStatus(RequestStatus.REQUEST_SUBMITTED);",
        "r/b/Processor.java": "request.setStatus(RequestStatus.QUOTE_RECEIVED); x(RequestStatus.QUOTE_ACCEPTED);",
    }
    members = [{"domain": "domain::quote", "object": "Quote Request", "name": "RequestStatus", "path": "r/a/domain/RequestStatus.java"}]

    [life] = detect_lifecycles(files, members, _units("a", "b"), RULES, docs={})

    assert (life.domain, life.attribute, life.states) == ("domain::quote", "RequestStatus", ["REQUEST_SUBMITTED", "QUOTE_RECEIVED", "QUOTE_ACCEPTED"])
    assert life.units_of_state == {"REQUEST_SUBMITTED": ["unit::a"], "QUOTE_RECEIVED": ["unit::b"], "QUOTE_ACCEPTED": ["unit::b"]}
    assert life.events == ["QUOTE_RECEIVED"]  # the lifecycle passes from unit a to unit b; an enum has no start event
    assert life.name_candidates == ["Quote Request Lifecycle"]


def test_orm_status_values_come_from_the_default_the_allowed_values_and_the_assignments():
    files = {
        "r/lease/app/models.py": 'class LeaseApplication(Base):\n    __tablename__ = "lease_applications"\n    status = Column(String(30), default="DRAFT")\n',
        "r/lease/app/routes.py": (
            'def submit(app):\n    app.status = "SUBMITTED"\n\ndef update(app, new):\n    valid = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DISBURSED"}\n    app.status = new\n'
        ),
        "r/uw/app/services.py": "def approve(db):\n    db.execute(text(\"UPDATE leases.lease_applications SET status = 'APPROVED' WHERE id = :i\"))\n",
    }
    members = [{"domain": "domain::lease", "object": "Lease", "name": "LeaseApplication", "path": "r/lease/app/models.py"}]

    [life] = detect_lifecycles(files, members, _units("lease", "uw"), RULES, docs={})

    assert (life.attribute, life.states) == ("status", ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DISBURSED"])
    assert life.units_of_state["APPROVED"] == ["unit::uw"]  # the specific assignment (SQL) decides over the generic setter
    assert life.events == ["SUBMITTED", "APPROVED", "DISBURSED"]  # the start (out of the default), then each change of unit
    assert life.name_candidates == ["Lease Lifecycle", "Lease Application Lifecycle"]  # the object, then the entity


def test_a_documented_flow_anchors_states_to_units_and_names_the_process():
    files = {
        "r/lease/app/models.py": 'class LeaseApplication(Base):\n    status = Column(String(30), default="DRAFT")\n',
        "r/lease/app/routes.py": 'def update(app, new):\n    valid = ["SUBMITTED", "APPROVED", "DISBURSED"]\n    app.status = new\n',
    }
    docs = {
        "r/README.md": (
            "### Lease processing flow\n\n1. **Apply** for a lease: the application shows status `SUBMITTED`.\n"
            "2. **Approve in upkeep**: the status moves to `APPROVED`.\n3. **Process disbursement**: the status moves to `DISBURSED`.\n"
        )
    }
    members = [{"domain": "domain::lease", "object": "Lease", "name": "LeaseApplication", "path": "r/lease/app/models.py"}]
    units = [
        {"id": "unit::lease", "path": "r/lease", "name": "lease-service"},
        {"id": "unit::uw", "path": "r/uw", "name": "upkeep-service"},
        {"id": "unit::disb", "path": "r/disb", "name": "disbursement-service"},
    ]

    [life] = detect_lifecycles(files, members, units, RULES, docs=docs)

    assert life.units_of_state["APPROVED"] == ["unit::uw"] and life.units_of_state["DISBURSED"] == ["unit::disb"]
    assert life.events == ["SUBMITTED", "APPROVED", "DISBURSED"]
    assert life.name_candidates == ["Lease Lifecycle", "Lease Application Lifecycle", "Lease Processing"]  # templates, then the flow's heading
    assert life.flow == "r/README.md#Lease processing flow"


def test_a_vocabulary_of_fewer_states_or_without_a_business_domain_is_no_lifecycle():
    files = {"r/a/models.py": 'class Payment(Base):\n    status = Column(String(20), default="SUCCESS")\n\ndef fail(p):\n    p.status = "FAILED"\n'}
    members = [{"domain": "domain::pay", "object": "Payment", "name": "Payment", "path": "r/a/models.py"}]

    assert detect_lifecycles(files, members, _units("a"), RULES, docs={}) == []


def test_states_set_only_by_assignments_join_in_the_order_of_their_first_file():
    files = {
        "r/a/models.py": 'class Case(Base):\n    status = Column(String(20), default="PENDING")\n',
        "r/a/services.py": 'def decide(case):\n    case.status = "APPROVED"\n    other.status = "IGNORED"\n',
        "r/b/services.py": 'def back(case):\n    case.status = "REFERRED_BACK"\n',
    }
    members = [{"domain": "domain::case", "object": "Case", "name": "Case", "path": "r/a/models.py"}]

    [life] = detect_lifecycles(files, members, _units("a", "b"), RULES, docs={})

    assert life.states == ["PENDING", "APPROVED", "REFERRED_BACK"]  # "other" names no entity with a status


def test_a_variable_that_names_two_entities_belongs_to_the_one_in_its_own_unit():
    files = {
        "r/uw/models.py": 'class UpkeepCase(Base):\n    status = Column(String(30), default="PENDING")\n',
        "r/coll/models.py": 'class CollectionsCase(Base):\n    status = Column(String(20), default="ACTIVE")\n',
        "r/uw/services.py": 'def decide(case):\n    case.status = "APPROVED"\n    case.status = "REJECTED"\n',
    }
    members = [
        {"domain": "domain::uw", "object": "Upkeep", "name": "UpkeepCase", "path": "r/uw/models.py"},
        {"domain": "domain::coll", "object": "Collections", "name": "CollectionsCase", "path": "r/coll/models.py"},
    ]

    [life] = detect_lifecycles(files, members, _units("uw", "coll"), RULES, docs={})

    assert (life.entity, life.states) == ("Upkeep Case", ["PENDING", "APPROVED", "REJECTED"])


def test_an_enum_transition_table_chains_events_only_along_its_transitions():
    files = {
        "r/a/domain/RequestStatus.java": (
            "public enum RequestStatus {\n  SUBMITTED,\n  REJECTED,\n  RECEIVED,\n  ACCEPTED,\n  CREATED;\n"
            "  public boolean canTransitionTo(RequestStatus next) {\n    switch(this) {\n"
            "    case SUBMITTED:\n      return next == REJECTED || next == RECEIVED;\n"
            "    case RECEIVED:\n      return next == ACCEPTED;\n"
            "    case ACCEPTED:\n      return next == CREATED;\n"
            "    case REJECTED:\n    case CREATED:\n      return false;\n    default:\n      return false;\n    }\n  }\n}"
        ),
        "r/a/Coordinator.java": "x(RequestStatus.SUBMITTED); y(RequestStatus.ACCEPTED);",
        "r/b/Processor.java": "x(RequestStatus.REJECTED); y(RequestStatus.RECEIVED); z(RequestStatus.CREATED);",
    }
    members = [{"domain": "domain::quote", "object": "Quote", "name": "RequestStatus", "path": "r/a/domain/RequestStatus.java"}]

    [life] = detect_lifecycles(files, members, _units("a", "b"), RULES, docs={})

    assert life.events == ["REJECTED", "ACCEPTED", "CREATED"]  # hand-offs in state order
    assert life.transitions == [("ACCEPTED", "CREATED"), ("RECEIVED", "ACCEPTED"), ("SUBMITTED", "RECEIVED"), ("SUBMITTED", "REJECTED")]
    # REJECTED and ACCEPTED have no event before them on a transition path: both hang off the lifecycle; no REJECTED -> ACCEPTED
    assert life.triggers == [(None, "REJECTED"), (None, "ACCEPTED"), ("ACCEPTED", "CREATED")]


def test_guarded_assignments_are_transitions_and_unguarded_ones_are_not():
    files = {
        "r/a/models.py": 'class CollectionsCase(Base):\n    status = Column(String(30), default="REMINDER")\n',
        "r/a/services.py": (
            "def escalate(case):\n"
            '    if case.status == "REMINDER":\n        case.status = "OVERDUE_NOTICE"\n'
            '    elif case.status == "OVERDUE_NOTICE":\n        case.status = "LEGAL_NOTICE"\n'
            "    else:\n"
            '        case.status = "CLOSED_OUT"\n'
            "\n"
            "def reopen(case):\n"
            '    if case.status != "CLOSED_OUT":\n        raise ValueError("open")\n'
            '    case.status = "REMINDER"\n'
        ),
    }
    members = [{"domain": "domain::coll", "object": "Collections", "name": "CollectionsCase", "path": "r/a/models.py"}]

    [life] = detect_lifecycles(files, members, _units("a"), RULES, docs={})

    # The else branch is not guarded by a state; the != guard that raises requires CLOSED_OUT before REMINDER
    assert life.transitions == [("CLOSED_OUT", "REMINDER"), ("OVERDUE_NOTICE", "LEGAL_NOTICE"), ("REMINDER", "OVERDUE_NOTICE")]


def test_an_update_with_a_state_condition_and_a_table_of_next_states_are_transitions():
    files = {
        "r/a/models.py": 'class Ticket(Base):\n    __tablename__ = "tickets"\n    status = Column(String(20), default="OPEN")\n',
        "r/a/services.py": (
            'NEXT = {"OPEN": ["RESOLVED"], "RESOLVED": ("CLOSED", "OPEN")}\n'
            "def close(db):\n    db.execute(text(\"UPDATE tickets SET status = 'CLOSED' WHERE status = 'RESOLVED'\"))\n"
            'def resolve(ticket):\n    ticket.status = "RESOLVED"\n'
        ),
    }
    members = [{"domain": "domain::ticket", "object": "Ticket", "name": "Ticket", "path": "r/a/models.py"}]

    [life] = detect_lifecycles(files, members, _units("a"), RULES, docs={})

    assert life.transitions == [("OPEN", "RESOLVED"), ("RESOLVED", "CLOSED"), ("RESOLVED", "OPEN")]


def test_consecutive_steps_of_a_documented_flow_are_transitions_and_an_unproven_alternative_hangs_off_the_lifecycle():
    files = {
        "r/lease/app/models.py": 'class LeaseApplication(Base):\n    status = Column(String(30), default="DRAFT")\n',
        "r/lease/app/routes.py": 'def update(app, new):\n    valid = ["SUBMITTED", "APPROVED", "DISBURSED"]\n    app.status = new\n',
        "r/lease/app/rejects.py": 'def reject(app):\n    app.status = "REJECTED"\n',
    }
    docs = {
        "r/README.md": (
            "### Lease processing flow\n\n1. **Apply** for a lease: the application shows status `SUBMITTED`.\n"
            "2. **Approve in upkeep**: the status moves to `APPROVED`.\n3. **Process disbursement**: the status moves to `DISBURSED`.\n"
        )
    }
    members = [{"domain": "domain::lease", "object": "Lease", "name": "LeaseApplication", "path": "r/lease/app/models.py"}]
    units = [
        {"id": "unit::lease", "path": "r/lease", "name": "lease-service"},
        {"id": "unit::uw", "path": "r/uw", "name": "upkeep-service"},
        {"id": "unit::disb", "path": "r/disb", "name": "disbursement-service"},
    ]

    [life] = detect_lifecycles(files, members, units, RULES, docs=docs)

    assert life.events == ["SUBMITTED", "APPROVED", "DISBURSED", "REJECTED"]
    assert life.transitions == [("APPROVED", "DISBURSED"), ("SUBMITTED", "APPROVED")]
    assert life.triggers == [(None, "SUBMITTED"), ("SUBMITTED", "APPROVED"), ("APPROVED", "DISBURSED"), (None, "REJECTED")]


def test_with_transitions_the_states_follow_them_and_the_start_event_comes_out_of_the_default():
    files = {
        "r/a/models.py": 'class CollectionsCase(Base):\n    status = Column(String(30), default="REMINDER")\n',
        "r/a/create.py": 'def open_case(case):\n    case.status = "LEGAL_NOTICE"\n',
        "r/a/services.py": (
            "def escalate(case):\n"
            '    if case.status == "REMINDER":\n        case.status = "OVERDUE_NOTICE"\n'
            '    elif case.status == "OVERDUE_NOTICE":\n        case.status = "LEGAL_NOTICE"\n'
        ),
    }
    members = [{"domain": "domain::coll", "object": "Collections", "name": "CollectionsCase", "path": "r/a/models.py"}]

    [life] = detect_lifecycles(files, members, _units("a"), RULES, docs={})

    # By first file the order would be REMINDER, LEGAL_NOTICE, OVERDUE_NOTICE; the transitions decide
    assert life.states == ["REMINDER", "OVERDUE_NOTICE", "LEGAL_NOTICE"]
    assert life.events == ["OVERDUE_NOTICE"]
