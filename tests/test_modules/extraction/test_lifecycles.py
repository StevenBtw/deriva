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


# Status types beside their domain (BusinessLayer params status_members): a status type is often no member of its business
# domain, but lies in the folder of a member, is declared in a member's file, or carries a member's name


def _widened(files, members):
    from deriva.modules.extraction.lifecycles import status_members

    return detect_lifecycles(files, status_members(members, files, RULES), [], RULES, docs={})


def test_a_status_enum_in_the_folder_of_a_domain_member_is_that_domain_s_lifecycle():
    files = {
        "r/cargo/Cargo.java": "public class Cargo { private Delivery delivery; }",
        "r/cargo/TransportStatus.java": "public enum TransportStatus { NOT_RECEIVED, IN_PORT, ONBOARD_CARRIER, CLAIMED }",
    }
    members = [{"domain": "domain::cargo", "object": "Cargo", "name": "Cargo", "path": "r/cargo/Cargo.java"}]

    assert detect_lifecycles(files, members, [], RULES, docs={}) == []
    [life] = _widened(files, members)
    assert (life.domain, life.attribute, life.states) == ("domain::cargo", "TransportStatus", ["NOT_RECEIVED", "IN_PORT", "ONBOARD_CARRIER", "CLAIMED"])


def test_a_status_enum_declared_in_a_member_s_file_is_that_domain_s_lifecycle():
    files = {"r/book/BookEntity.java": "class BookEntity { enum BookState { AVAILABLE, ON_HOLD, CHECKED_OUT } BookState state; }"}
    members = [{"domain": "domain::book", "object": "Book", "name": "BookEntity", "path": "r/book/BookEntity.java"}]

    [life] = _widened(files, members)
    assert (life.attribute, life.states) == ("BookState", ["AVAILABLE", "ON_HOLD", "CHECKED_OUT"])


def test_a_status_type_named_after_a_member_elsewhere_joins_it_by_the_closest_folder():
    """The same package in another module wins over a copy in an unrelated folder (a test fixture); a tie joins none."""
    files = {
        "r/provider/x/loan/domain/Loan.java": "public class Loan { private Integer loanStatus; }",
        "r/core/x/loan/domain/LoanStatus.java": "public enum LoanStatus { SUBMITTED, APPROVED, ACTIVE, CLOSED }",
        "r/checks/data/LoanStatus.java": "public enum LoanStatus { PENDING, DONE, FAILED }",
    }
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/provider/x/loan/domain/Loan.java"}]

    [life] = _widened(files, members)
    assert (life.attribute, life.states) == ("LoanStatus", ["SUBMITTED", "APPROVED", "ACTIVE", "CLOSED"])

    tied = {"r/a/Order.java": "class Order {}", "r/b/OrderStatus.java": "enum OrderStatus { NEW, PAID, SENT }", "r/c/OrderStatus.java": "enum OrderStatus { X1, X2, X3 }"}
    assert _widened(tied, [{"domain": "domain::order", "object": "Order", "name": "Order", "path": "r/a/Order.java"}]) == []


def test_a_member_s_own_type_and_unrelated_types_are_not_added():
    from deriva.modules.extraction.lifecycles import status_members

    files = {"r/a/Order.java": "class Order {}", "r/a/OrderService.java": "class OrderService {}", "r/z/PaymentStatus.java": "enum PaymentStatus { A1, B1, C1 }"}
    members = [{"domain": "domain::order", "object": "Order", "name": "Order", "path": "r/a/Order.java"}]

    assert status_members(members, files, RULES) == members


def test_a_folder_shared_by_several_domains_gives_its_status_type_to_the_member_it_names_or_to_none():
    from deriva.modules.extraction.lifecycles import status_members

    files = {
        "r/m/Loan.java": "class Loan {}",
        "r/m/Group.java": "class Group {}",
        "r/m/LoanSubStatus.java": "enum LoanSubStatus { A1, B1, C1 }",
        "r/m/TransferStatus.java": "enum TransferStatus { A1, B1, C1 }",
    }
    members = [
        {"domain": "domain::group", "object": "Group", "name": "Group", "path": "r/m/Group.java"},
        {"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/m/Loan.java"},
    ]

    added = {m["name"]: m["domain"] for m in status_members(members, files, RULES)[2:]}
    assert added == {"LoanSubStatus": "domain::loan"}

    # A folder named after one of its domains keeps its status types there
    named = {"r/order/Order.java": "class Order {}", "r/order/OrderLine.java": "class OrderLine {}", "r/order/ShippingStatus.java": "enum ShippingStatus { A1, B1, C1 }"}
    in_order = [
        {"domain": "domain::order", "object": "Order", "name": "Order", "path": "r/order/Order.java"},
        {"domain": "domain::line", "object": "Order Line", "name": "OrderLine", "path": "r/order/OrderLine.java"},
    ]
    assert {m["name"]: m["domain"] for m in status_members(in_order, named, RULES)[2:]} == {"ShippingStatus": "domain::order"}

    # A status type no member's name starts goes to the one domain whose member file uses it
    files["r/m/Group.java"] = "class Group { TransferStatus transfer; }"
    added = {m["name"]: m["domain"] for m in status_members(members, files, RULES)[2:]}
    assert added == {"LoanSubStatus": "domain::loan", "TransferStatus": "domain::group"}


def test_verb_names_name_the_process_by_what_happens_to_its_object_then_manage_it():
    from deriva.modules.extraction.lifecycles import Lifecycle, verb_names

    life = Lifecycle(key="k", domain="d", entity="Loan Application", attribute="status", states=["DRAFT", "SUBMITTED", "APPROVED", "IN_PORT", "WRITTEN_OFF"])
    verbs = {"SUBMITTED": "Submit", "APPROVED": "Approve", "WRITTEN_OFF": "Write Off"}

    assert verb_names(life, "Loan Application", verbs) == ["Submit Loan Application", "Approve Loan Application", "Write Off Loan Application", "Manage Loan Application"]
    assert verb_names(life, "Loan Application", {}) == ["Manage Loan Application"]


def test_a_kotlin_enum_class_in_a_member_s_file_is_that_domain_s_lifecycle():
    files = {"r/loan/Loan.kt": "class Loan(val state: LoanState)\nenum class LoanState { DRAFT, OPEN, CLOSED }\n"}
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/loan/Loan.kt"}]

    [life] = _widened(files, members)
    assert (life.attribute, life.states) == ("LoanState", ["DRAFT", "OPEN", "CLOSED"])


def test_an_enum_named_only_in_a_comment_joins_nothing():
    from deriva.modules.extraction.lifecycles import status_members

    files = {"r/loan/Loan.java": "// the enum LoanStatus moved to the api module\nclass Loan { }\n"}
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/loan/Loan.java"}]

    assert status_members(members, files, RULES) == members


def test_a_folder_of_two_domains_where_no_rule_decides_gives_its_status_type_to_none():
    from deriva.modules.extraction.lifecycles import status_members

    files = {"r/m/Loan.java": "class Loan {}", "r/m/Group.java": "class Group {}", "r/m/AccountStatus.java": "enum AccountStatus { A1, B1, C1 }"}
    members = [
        {"domain": "domain::group", "object": "Group", "name": "Group", "path": "r/m/Group.java"},
        {"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/m/Loan.java"},
    ]

    assert status_members(members, files, RULES) == members


def test_a_plural_folder_named_after_a_domain_keeps_its_status_type_there():
    from deriva.modules.extraction.lifecycles import status_members

    files = {"r/cargos/Cargo.java": "class Cargo {}", "r/cargos/Leg.java": "class Leg {}", "r/cargos/HandlingStatus.java": "enum HandlingStatus { A1, B1, C1 }"}
    members = [
        {"domain": "domain::cargo", "object": "Cargo", "name": "Cargo", "path": "r/cargos/Cargo.java"},
        {"domain": "domain::leg", "object": "Leg", "name": "Leg", "path": "r/cargos/Leg.java"},
    ]

    assert {m["name"]: m["domain"] for m in status_members(members, files, RULES)[2:]} == {"HandlingStatus": "domain::cargo"}


def test_the_main_status_file_wins_over_its_test_copy():
    from deriva.modules.extraction.lifecycles import status_members

    files = {
        "r/src/main/java/x/loan/Loan.java": "class Loan {}",
        "r/src/main/java/x/loan/LoanStatus.java": "enum LoanStatus { A1, B1, C1 }",
        "r/src/test/java/x/loan/LoanStatus.java": "enum LoanStatus { T1, T2, T3 }",
    }
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/src/main/java/x/loan/Loan.java"}]

    [added] = status_members(members, files, RULES)[1:]
    assert added["path"] == "r/src/main/java/x/loan/LoanStatus.java"


def test_status_members_is_stable_under_the_order_of_members_and_files():
    from deriva.modules.extraction.lifecycles import status_members

    files = {
        "r/m/Loan.java": "class Loan {}",
        "r/m/Group.java": "class Group { TransferStatus transfer; }",
        "r/m/LoanSubStatus.java": "enum LoanSubStatus { A1, B1, C1 }",
        "r/m/TransferStatus.java": "enum TransferStatus { A1, B1, C1 }",
    }
    members = [
        {"domain": "domain::group", "object": "Group", "name": "Group", "path": "r/m/Group.java"},
        {"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/m/Loan.java"},
    ]
    forward = status_members(members, files, RULES)
    backward = status_members(members[::-1], dict(reversed(list(files.items()))), RULES)

    assert sorted((m["name"], m["domain"]) for m in forward) == sorted((m["name"], m["domain"]) for m in backward)


def test_verb_names_say_each_verb_once():
    from deriva.modules.extraction.lifecycles import Lifecycle, verb_names

    life = Lifecycle(key="k", domain="d", entity="Loan", attribute="status", states=["APPROVED", "RE_APPROVED", "CLOSED"])

    assert verb_names(life, "Loan", {"APPROVED": "Approve", "RE_APPROVED": "Approve", "CLOSED": "Close"}) == ["Approve Loan", "Close Loan", "Manage Loan"]
    assert verb_names(Lifecycle(key="k", domain="d", entity="Loan", attribute="status", states=[]), "Loan", {}) == ["Manage Loan"]


def test_a_csharp_enum_with_its_brace_on_the_next_line_in_a_member_s_file_is_that_domain_s_lifecycle():
    files = {"r/Loans/Loan.cs": "public class Loan { public LoanState State; }\npublic enum LoanState\n{\n    Draft,\n    Open,\n    Closed\n}\n"}
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/Loans/Loan.cs"}]

    [life] = _widened(files, members)
    assert (life.attribute, life.states) == ("LoanState", ["Draft", "Open", "Closed"])


def test_an_enum_a_block_comment_names_joins_nothing():
    from deriva.modules.extraction.lifecycles import status_members

    files = {"r/loan/Loan.java": "/* enum LoanStatus { OLD } was here */\nclass Loan { }\n"}
    members = [{"domain": "domain::loan", "object": "Loan", "name": "Loan", "path": "r/loan/Loan.java"}]

    assert status_members(members, files, RULES) == members


def _enum_states(text: str, name: str = "LoanState", path: str = "r/loan/LoanState.java") -> list[str]:
    members = [{"domain": "domain::loan", "object": "Loan", "name": name, "path": path}]
    lives = detect_lifecycles({path: text}, members, [], RULES, docs={})
    return lives[0].states if lives else []


def test_a_java_enum_with_a_constructor_gives_the_bare_names():
    text = 'public enum LoanState {\n    DRAFT(0, "x"),\n    OPEN(1, "y"),\n    CLOSED(2, "z");\n    LoanState(int c, String d) { }\n}\n'

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED"]


def test_a_constructor_argument_that_is_a_name_is_no_state():
    text = "public enum LoanState { DRAFT(0, NONE, 2), OPEN(1, Level.LOW, 3), CLOSED(2, FINAL, 4); }"

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED"]


def test_a_csharp_enum_with_values_gives_the_bare_names():
    text = "public enum LoanState\n{\n    Draft = 0,\n    Open = 1,\n    Closed = 2,\n}\n"

    assert _enum_states(text, path="r/Loans/LoanState.cs") == ["Draft", "Open", "Closed"]


def test_a_csharp_constant_with_an_attribute_keeps_its_name():
    text = 'public enum LoanState\n{\n    [Description("New")] Draft,\n    [Display(Name = "Open")] Open,\n    Closed\n}\n'

    assert _enum_states(text, path="r/Loans/LoanState.cs") == ["Draft", "Open", "Closed"]


def test_comments_and_a_trailing_comma_in_an_enum_body_give_no_state():
    text = "public enum LoanState {\n    /** the first */ DRAFT,\n    OPEN, // still open\n    CLOSED,\n}\n"

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED"]


def test_a_url_string_before_an_enum_is_no_comment():
    """A "//" inside a string starts no comment, so the string's quotes stay paired and the enum after it is found."""
    text = 'class Links { String HOME = "http://example.org/a"; }\npublic enum LoanState { DRAFT("Draft"), OPEN("Open"), CLOSED("Closed"); }\n'

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED"]


def test_a_quote_inside_a_comment_opens_no_string():
    text = "// the loan's states\npublic enum LoanState { DRAFT, OPEN, CLOSED }\n// it's done\n"

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED"]


def test_a_kotlin_enum_with_a_constructor_gives_the_bare_names():
    text = "enum class LoanState(val code: Int) { DRAFT(0), OPEN(1), CLOSED(2) }"

    assert _enum_states(text, path="r/loan/LoanState.kt") == ["DRAFT", "OPEN", "CLOSED"]


def test_a_string_with_a_bracket_or_a_comma_in_a_constructor_argument_leaves_the_names_whole():
    text = 'public enum LoanState { DRAFT("a("), OPEN("b, c"), CLOSED("d]"), SETTLED(")") }'

    assert _enum_states(text) == ["DRAFT", "OPEN", "CLOSED", "SETTLED"]


def test_an_attribute_with_a_comma_in_its_text_leaves_the_names_whole():
    text = 'public enum LoanState\n{\n    [Obsolete("Use Open, not this")] Draft,\n    [Description("[open]")] Open,\n    Closed\n}\n'

    assert _enum_states(text, path="r/Loans/LoanState.cs") == ["Draft", "Open", "Closed"]


def test_verb_names_cover_every_name_of_the_object_in_order():
    """A lifecycle of an entity whose domain names its object otherwise (Underwriting Case in the Assessment domain)
    offers the verbs for both names, as the Lifecycle templates do."""
    from deriva.modules.extraction.lifecycles import Lifecycle, verb_names

    life = Lifecycle(key="k", domain="d", entity="Underwriting Case", attribute="status", states=["PENDING", "APPROVED"])

    assert verb_names(life, ["Assessment", "Underwriting Case"], {"APPROVED": "Approve"}) == [
        "Approve Assessment",
        "Manage Assessment",
        "Approve Underwriting Case",
        "Manage Underwriting Case",
    ]
    assert verb_names(life, ["Assessment", "Assessment"], {"APPROVED": "Approve"}) == ["Approve Assessment", "Manage Assessment"]


def test_verb_names_skip_an_empty_name_of_the_object():
    """A domain whose businessObject is an empty string gives no " Manage " name; the entity's name still counts."""
    from deriva.modules.extraction.lifecycles import Lifecycle, verb_names

    life = Lifecycle(key="k", domain="d", entity="Loan", attribute="status", states=["APPROVED"])

    assert verb_names(life, ["", "Loan"], {"APPROVED": "Approve"}) == ["Approve Loan", "Manage Loan"]
    assert verb_names(life, "  ", {"APPROVED": "Approve"}) == []


def test_a_pascal_case_enum_s_states_are_reached_where_its_values_are_set():
    """C# enum states (Draft, Open) count where the code sets them, like SCREAMING_CASE states do."""
    files = {
        "r/a/LoanState.cs": "public enum LoanState { Draft, Open, Closed }",
        "r/a/Opening.cs": "loan.State = LoanState.Open;",
        "r/b/Closing.cs": "loan.State = LoanState.Closed;",
    }
    members = [{"domain": "domain::loan", "object": "Loan", "name": "LoanState", "path": "r/a/LoanState.cs"}]

    [life] = detect_lifecycles(files, members, _units("a", "b"), RULES, docs={})

    assert life.states == ["Draft", "Open", "Closed"]
    assert life.units_of_state["Open"] == ["unit::a"] and life.units_of_state["Closed"] == ["unit::b"]


def test_an_enum_constant_with_a_class_body_keeps_the_states_after_it():
    """A Java constant may have its own body (DRAFT { ... }): the states after it still count, the members after ";" do not."""
    files = {
        "r/a/LoanStatus.java": (
            "public enum LoanStatus {\n  DRAFT { boolean editable() { return true; } },\n  APPROVED,\n  CLOSED;\n"
            "  boolean editable() { return false; }\n  private final int code = 0;\n}\n"
        )
    }
    members = [{"domain": "domain::loan", "object": "Loan", "name": "LoanStatus", "path": "r/a/LoanStatus.java"}]

    [life] = detect_lifecycles(files, members, [], RULES, docs={})

    assert life.states == ["DRAFT", "APPROVED", "CLOSED"]


def test_a_plural_folder_is_named_after_its_singular_domain():
    """A folder "businesses" is named after the Business domain, as "cargos" is after Cargo."""
    from deriva.modules.extraction.lifecycles import status_members

    files = {
        "r/businesses/Business.java": "class Business {}",
        "r/businesses/Partner.java": "class Partner {}",
        "r/businesses/ApprovalStatus.java": "enum ApprovalStatus { A1, B1, C1 }",
    }
    members = [
        {"domain": "domain::business", "object": "Business", "name": "Business", "path": "r/businesses/Business.java"},
        {"domain": "domain::partner", "object": "Partner", "name": "Partner", "path": "r/businesses/Partner.java"},
    ]

    assert {m["name"]: m["domain"] for m in status_members(members, files, RULES)[2:]} == {"ApprovalStatus": "domain::business"}
