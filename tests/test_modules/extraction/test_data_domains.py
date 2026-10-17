"""Information domains from structure (no LLM): aggregates, naming roots, ORM ownership and bounded contexts
group entities into domains; technical-word entities join a domain or form their own only with evidence."""

from __future__ import annotations

from deriva.modules.extraction.data_domains import DomainRules, detect_domains, orm_relations

RULES = DomainRules(identity_words=("user", "login", "role", "token"), unit_noise=("service",))


def _entity(key, name, unit, types=None, signal="orm entity"):
    return {"key": key, "name": name, "signal": signal, "type_ids": types or [f"t::{key}"], "units": [unit]}


def _candidate(type_id, name, reason, unit):
    return {"type_id": type_id, "name": name, "reason": reason, "units": [unit]}


def _domains(result):
    return {d.anchor: sorted(d.members) for d in result.domains}


def test_java_ownership_comes_from_owning_collections_and_mandatory_parents():
    order = """
    @Entity public class PersistenceOrder {
      @OneToMany(mappedBy = "order", cascade = {CascadeType.ALL}) private List<PersistenceOrderItem> orderItems;
      @ManyToOne(optional = false) private PersistenceUser user;
      @ManyToOne private PersistenceShop shop;
    }"""

    assert sorted(orm_relations("Order.java", order)) == [
        ("PersistenceOrder", "owns", "PersistenceOrderItem"),
        ("PersistenceOrder", "refers", "PersistenceShop"),
        ("PersistenceOrder", "refers", "PersistenceUser"),
        ("PersistenceUser", "parent", "PersistenceOrder"),  # a mandatory parent
    ]


def test_sqlalchemy_ownership_comes_from_mandatory_foreign_keys_and_delete_orphan_relationships():
    models = """
class User(Base):
    __tablename__ = "users"
    role_id = Column(Integer, ForeignKey("auth.roles.id"), nullable=False)
    tokens = relationship("RefreshToken", cascade="all, delete-orphan")

class Role(Base):
    __tablename__ = "roles"

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    user_id = Column(UUID, ForeignKey("auth.users.id"))
"""

    assert sorted(orm_relations("models.py", models)) == [
        ("RefreshToken", "refers", "User"),  # an optional foreign key only refers
        ("Role", "parent", "User"),  # a mandatory foreign key
        ("User", "owns", "RefreshToken"),  # delete-orphan
        ("User", "refers", "Role"),
    ]


def test_an_aggregate_root_takes_the_parts_and_value_objects_it_references():
    entities = [_entity("customer", "Customer", "core", ["t::CustomerRoot"], "aggregate root")]
    candidates = [
        _candidate("t::Profile", "Customer Profile", "part of an aggregate", "core"),
        _candidate("t::Address", "Address", "value object", "core"),
        _candidate("t::UserLogin", "User Login", "part of an aggregate", "self-service"),
        _candidate("t::Money", "Money Amount", "value object", "core"),  # referenced by nobody: no domain
    ]
    refs = [("t::CustomerRoot", "t::Profile"), ("t::Profile", "t::Address")]

    result = detect_domains(entities, candidates, refs, [], RULES)

    assert _domains(result) == {"Customer": ["t::Address", "t::CustomerRoot", "t::Profile"], "User Login": ["t::UserLogin"]}


def test_naming_roots_then_ownership_group_entities():
    entities = [_entity(k, n, "persistence") for k, n in (("category", "Category"), ("product", "Product"), ("order", "Order"), ("orderitem", "Order Item"), ("user", "User"))]
    relations = [("category", "owns", "product"), ("product", "owns", "orderitem"), ("order", "owns", "orderitem"), ("user", "owns", "order"), ("product", "refers", "category")]

    result = detect_domains(entities, [], [], relations, RULES)

    # Order Item joins Order by its name; Product then owns no member and joins its one owner; Order keeps its member
    assert _domains(result) == {"Category": ["t::category", "t::product"], "Order": ["t::order", "t::orderitem"], "User": ["t::user"]}


def test_a_lookup_joins_the_one_anchor_that_uses_it_and_unrelated_entities_of_a_unit_group():
    entities = [
        _entity("user", "User", "auth"),
        _entity("role", "Role", "auth"),
        _entity("payment", "Payment", "repayment"),
        _entity("penalty", "Penalty", "repayment"),
        _entity("loan", "Loan", "disbursement"),
        _entity("loanapplication", "Loan Application", "origination"),  # a naming root across units
    ]
    candidates = [_candidate("t::RefreshToken", "Refresh Token", "technical word: token", "auth")]
    relations = [("role", "parent", "user"), ("user", "refers", "role"), ("user", "parent", "t::RefreshToken")]

    result = detect_domains(entities, candidates, [], relations, RULES)

    assert _domains(result) == {
        "User": ["t::RefreshToken", "t::role", "t::user"],
        "Payment": ["t::payment", "t::penalty"],  # the repayment unit's unrelated entities
        "Loan": ["t::loan", "t::loanapplication"],
    }
    assert {d.anchor: d.kind for d in result.domains} == {"User": "ownership", "Payment": "context", "Loan": "naming"}


def test_a_technical_entity_forms_a_domain_only_as_a_root_or_the_only_entity_of_its_unit():
    entities = [_entity("customer", "Customer", "core", ["t::Root"], "aggregate root")]
    candidates = [
        _candidate("t::InteractionLog", "Interaction Log", "technical word: log", "support"),
        _candidate("t::Interaction", "Interaction", "part of an aggregate", "support"),
        _candidate("t::Audit", "Audit Entry", "technical word: audit", "audit"),
        _candidate("t::Template", "Email Template", "technical word: template", "notification"),
        _candidate("t::NotificationLog", "Notification Log", "technical word: log", "notification"),
    ]
    refs = [("t::InteractionLog", "t::Interaction")]

    result = detect_domains(entities, candidates, refs, [], RULES, roots={"t::Root", "t::InteractionLog"})

    domains = {d.anchor: d for d in result.domains}
    assert sorted(domains) == ["Audit Entry", "Customer", "Interaction Log"]
    assert domains["Interaction Log"].exception and domains["Audit Entry"].exception and not domains["Customer"].exception
    assert domains["Interaction Log"].members == ["t::Interaction", "t::InteractionLog"]
    assert sorted((x.name, x.reason) for x in result.excluded) == [
        ("Email Template", "technical word, no domain of its own"),
        ("Notification Log", "technical word, no domain of its own"),
    ]


def test_business_objects_only_for_business_anchors_and_closed_name_candidates():
    entities = [
        _entity("customer", "Customer", "customer-service"),
        _entity("user", "User", "auth-service"),
        _entity("payment", "Payment", "repayment-service"),
        _entity("penalty", "Penalty", "repayment-service"),
        _entity("shopper", "Shopper User", "shop", ["t::shopper"]),
        _entity("basket", "Basket", "shop"),
        _entity("basketitem", "Basket Item", "shop"),  # Basket keeps a member, so it stays a domain
    ]
    candidates = [_candidate("t::Audit", "Audit Entry", "technical word: audit", "audit-service")]
    relations = [("shopper", "owns", "basket")]  # this user owns business data
    docs = {"README.md": "Every change lands in a tamper-proof **audit trail**."}

    result = detect_domains(entities, candidates, [], relations, RULES, unit_names={"repayment-service": "repayment-service", "audit-service": "audit-service"}, docs=docs)

    by_key = {d.key: d for d in result.domains}
    assert by_key["user"].business_object is None  # an identity domain: a DataObject, no BusinessObject
    assert by_key["audit-entry"].business_object is None  # an exception domain
    assert by_key["shopper"].business_object == "Shopper User"  # an identity word, but it owns business data
    assert by_key["payment"].business_object == "Payment"
    assert by_key["payment"].name_candidates == ["Payment Data", "Repayment Data"]  # anchor, unit stem
    assert by_key["user"].name_candidates == ["User", "User Data"]  # no BusinessObject: the bare name may name the data
    assert by_key["audit-entry"].name_candidates == ["Audit Entry", "Audit Entry Data", "Audit Data", "Audit Trail"]  # + the documentation term
    assert by_key["customer"].name_candidates == ["Customer Data"]  # one candidate: no naming call


def test_only_parts_value_objects_and_technical_types_are_candidates():
    candidates = [
        _candidate("t::Map", "Comen1 Ai", "not named as a record", "online"),
        _candidate("t::Rec", "Trnx", "used by 1 programs (fewer than 3)", "batch"),
        _candidate("t::Settings", "App Settings", "config", "app"),
        _candidate("t::Part", "Order Line", "part of an aggregate", "shop"),
    ]

    assert _domains(detect_domains([], candidates, [], [], RULES)) == {"Order Line": ["t::Part"]}


def test_a_root_never_joins_a_part_and_unreached_copies_of_a_part_follow_the_claimed_copy():
    entities = [_entity("quote-request", "Insurance Quote Request", "self-service", ["t::RootA", "t::RootB"], "aggregate root")]
    candidates = [
        _candidate("t::QuoteA", "Insurance Quote", "part of an aggregate", "self-service"),
        _candidate("t::QuoteB", "Insurance Quote", "part of an aggregate", "policy"),  # the other backend's copy, no reference
    ]

    result = detect_domains(entities, candidates, [("t::RootA", "t::QuoteA")], [], RULES)

    assert _domains(result) == {"Insurance Quote Request": ["t::QuoteA", "t::QuoteB", "t::RootA", "t::RootB"]}


def test_a_domain_of_ddl_tables_only_gets_no_business_object():
    entities = [
        _entity("runs", "Run", "app", signal="table"),
        _entity("transactiontype", "Transaction Type", "app", signal="table"),
        _entity("transactiontypecategory", "Transaction Type Category", "app", signal="table"),
        _entity("order", "Order", "shop"),  # a code entity (an ORM class with its table twin)
    ]

    result = detect_domains(entities, [], [], [], RULES)

    assert {d.anchor: d.business_object for d in result.domains} == {"Run": None, "Transaction Type": None, "Order": "Order"}
    assert {d.anchor: d.name_candidates for d in result.domains}["Run"] == ["Run", "Run Data"]  # no BusinessObject: the bare name may name the data
