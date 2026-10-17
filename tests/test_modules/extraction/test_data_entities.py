"""Data entities from structure: aggregate roots, ORM entities, shared mainframe records and DDL tables; value objects, ids, DTOs, configs and technical records out."""

from __future__ import annotations

from deriva.modules.extraction.data_entities import EntityRules, detect_entities

RULES = EntityRules(
    root_markers=("RootEntity", "AggregateRoot"),
    entity_annotations=("Entity", "Table", "Document"),
    orm_bases=("DeclarativeBase", "Model"),
    value_markers=("ValueObject", "Embeddable"),
    id_markers=("EntityIdentifier",),
    dto_bases=("BaseModel",),
    dto_suffixes=("Dto", "Request", "Response"),
    dto_dirs=("dto", "schemas"),
    config_markers=("Configuration",),
    config_suffixes=("Config", "Properties", "Settings"),
    technical_words=("log", "token", "database", "setting", "registry", "abend"),
    min_importers=3,
    record_pattern=r"(?i).*[-_](RECORD|REC|DATA)$",
    name_suffixes=("AggregateRoot", "Root", "Entity", "Model", "Record", "Rec", "Data"),
)


def _t(name: str, path: str, category: str = "class", decorators=(), bases=()) -> dict:
    return {"id": f"typedef::r::{path}::{name}", "name": name, "category": category, "decorators": list(decorators), "path": path, "bases": list(bases)}


def _names(result) -> list[str]:
    return sorted(e.name_candidates[0][0] for e in result.entities)


def _reasons(result) -> dict[str, str]:
    return {x.name: x.reason for x in result.excluded}


def test_when_a_repository_marks_aggregate_roots_only_the_roots_are_entities():
    types = [
        _t("CustomerAggregateRoot", "r/core/Customer.java", decorators=["Entity"], bases=["RootEntity"]),
        _t("CustomerProfileEntity", "r/core/Profile.java", decorators=["Entity"]),
        _t("CustomerId", "r/core/CustomerId.java", decorators=["Embeddable"], bases=["ValueObject", "EntityIdentifier"]),
        _t("Address", "r/core/Address.java", decorators=["Entity"], bases=["ValueObject"]),
    ]

    result = detect_entities(types, {}, {}, RULES)

    assert _names(result) == ["Customer"]
    assert _reasons(result) == {"CustomerProfileEntity": "part of an aggregate", "CustomerId": "id", "Address": "value object"}


def test_orm_entities_are_found_by_annotation_and_by_inheritance_over_two_steps():
    types = [
        _t("PersistenceOrder", "r/persistence/Order.java", decorators=["Entity"]),
        _t("Base", "r/loans/database.py", bases=["DeclarativeBase"]),
        _t("LoanApplication", "r/loans/models.py", bases=["Base"]),
        _t("LoanCreate", "r/loans/schemas.py", bases=["BaseModel"]),
        _t("Helper", "r/loans/util.py"),
    ]

    result = detect_entities(types, {}, {"r/persistence/Order.java": "persistence"}, RULES)

    # The owning unit's name is no part of the entity's name; the ORM base itself is no entity
    assert _names(result) == ["Loan Application", "Order"]
    assert _reasons(result)["LoanCreate"] == "dto"


def test_dtos_configs_and_technical_records_are_out_with_their_reason():
    types = [
        _t("OrderDto", "r/api/OrderDto.java", decorators=["Entity"]),
        _t("Invoice", "r/schemas/Invoice.java", decorators=["Entity"]),
        _t("ShopConfig", "r/core/ShopConfig.java", decorators=["Entity"]),
        _t("NotificationLog", "r/core/Log.java", decorators=["Entity"]),
        _t("DatabaseManagementEntity", "r/core/Db.java", decorators=["Entity"]),
        _t("Payment", "r/core/Payment.java", decorators=["Entity"]),
        _t("ShopSetup", "r/core/ShopSetup.java", decorators=["Entity", "Configuration"]),  # a config marker, no config suffix
    ]

    result = detect_entities(types, {}, {}, RULES)

    assert _names(result) == ["Payment"]
    reasons = _reasons(result)
    assert reasons["OrderDto"] == "dto" and reasons["Invoice"] == "dto" and reasons["ShopConfig"] == "config"
    assert reasons["ShopSetup"] == "config"
    assert reasons["NotificationLog"] == "technical word: log" and reasons["DatabaseManagementEntity"] == "technical word: database"


def test_mainframe_records_count_when_enough_programs_use_them():
    types = [
        _t("ACCOUNT-RECORD", "r/app/cpy/ACCT.cpy", category="record"),
        _t("DALYTRAN-RECORD", "r/app/cpy/DALY.cpy", category="record"),
        _t("ABEND-DATA", "r/app/cpy/ABEND.cpy", category="record"),
    ]
    importers = {"r/app/cpy/ACCT.cpy": 14, "r/app/cpy/DALY.cpy": 2, "r/app/cpy/ABEND.cpy": 7}

    result = detect_entities(types, importers, {}, RULES)

    assert _names(result) == ["Account"]
    assert _reasons(result) == {"DALYTRAN-RECORD": "used by 2 programs (fewer than 3)", "ABEND-DATA": "technical word: abend"}


def test_ddl_tables_are_entities_named_in_the_singular():
    types = [
        _t("benchmark_runs", "r/db/schema.sql", category="table"),
        _t("TRANSACTION_TYPE", "r/ddl/TRNTYPE.ddl", category="table", decorators=["schema:SHOP"]),
        _t("system_settings", "r/db/schema.sql", category="table"),
    ]

    result = detect_entities(types, {}, {}, RULES)

    assert _names(result) == ["Benchmark Run", "Transaction Type"]
    assert _reasons(result) == {"system_settings": "technical word: setting"}


def test_one_concept_in_several_units_is_one_entity_with_all_its_types():
    types = [
        _t("InsuranceQuoteRequestAggregateRoot", "r/self-service/Iqr.java", decorators=["Entity"], bases=["RootEntity"]),
        _t("InsuranceQuoteRequestAggregateRoot", "r/policy/Iqr.java", decorators=["Entity"], bases=["RootEntity"]),
    ]

    (entity,) = detect_entities(types, {}, {}, RULES).entities

    assert entity.name_candidates == [("Insurance Quote Request", "type")]
    assert entity.type_ids == sorted(t["id"] for t in types) and entity.signal == "aggregate root"
    assert entity.key == "insurancequoterequest"


def test_a_shared_working_storage_area_is_no_record_entity():
    """Only records named as records (the pattern) count; a shared work area or communication area is no persistent data."""
    types = [_t("ACCOUNT-RECORD", "r/app/cpy/ACCT.cpy", category="record"), _t("CARDDEMO-COMMAREA", "r/app/cpy/COMMAREA.cpy", category="record")]
    importers = {"r/app/cpy/ACCT.cpy": 14, "r/app/cpy/COMMAREA.cpy": 30}

    result = detect_entities(types, importers, {}, RULES)

    assert _names(result) == ["Account"] and _reasons(result) == {"CARDDEMO-COMMAREA": "not named as a record"}


def test_a_table_generated_for_a_code_entity_is_that_entity():
    """An ORM's DDL names its table after the type (PERSISTENCEORDER): the table follows the type, in or out."""
    types = [
        _t("PersistenceOrder", "r/persistence/Order.java", decorators=["Entity"]),
        _t("DatabaseManagementEntity", "r/persistence/Db.java", decorators=["Entity"]),
        _t("PERSISTENCEORDER", "r/db/setup.sql", category="table"),
        _t("DATABASEMANAGEMENTENTITY", "r/db/setup.sql", category="table"),
    ]

    result = detect_entities(types, {}, {"r/persistence/Order.java": "persistence"}, RULES)

    (order,) = result.entities
    assert order.name_candidates == [("Order", "type")] and len(order.type_ids) == 2
    assert _reasons(result)["DATABASEMANAGEMENTENTITY"] == "technical word: database"


def test_a_table_is_named_in_the_code_files_that_query_it():
    """The table's name after a query keyword (FROM, JOIN, INTO, UPDATE, TABLE), schema-qualified or not: a common word elsewhere is no use."""
    from deriva.modules.extraction.data_entities import table_mentions

    files = {
        "r/db/schema.sql": "CREATE TABLE benchmark_runs (id INT); CREATE TABLE runs (id INT);",
        "r/app/store.py": 'conn.execute("SELECT * FROM benchmark_runs WHERE id = ?")',
        "r/app/other.py": 'conn.execute("SELECT * FROM benchmark_runs_archive")',  # another table
        "r/app/loop.py": "# the pipeline runs twice\nfor runs in range(3): pass",  # the word, not the table
        "r/app/history.py": 'conn.execute("insert into runs (id) values (?)")',
        "r/cbl/PROG.cbl": "EXEC SQL SELECT TR_TYPE FROM LEDGER.TRANSACTION_TYPE END-EXEC.",
        "r/app/join.py": 'q = "SELECT * FROM a JOIN accounts ON a.id = accounts.id"',
        "r/app/update.java": 'String q = "UPDATE balances SET amount = 0";',
        "r/app/drop.sql.py": 'conn.execute("TRUNCATE TABLE audits")',
    }
    tables = {
        "benchmarkrun": ["benchmark_runs"],
        "run": ["runs"],
        "transactiontype": ["TRANSACTION_TYPE"],
        "account": ["accounts"],
        "balance": ["balances"],
        "audit": ["audits"],
    }

    found = table_mentions(tables, files, own_files={"r/db/schema.sql"})

    assert found == {
        "benchmarkrun": ["r/app/store.py"],
        "run": ["r/app/history.py"],
        "transactiontype": ["r/cbl/PROG.cbl"],
        "account": ["r/app/join.py"],
        "balance": ["r/app/update.java"],
        "audit": ["r/app/drop.sql.py"],
    }


def test_a_schema_name_and_comments_are_no_table_mention():
    """users.orders names the table orders in the schema users; a query in a comment is no use of the table."""
    from deriva.modules.extraction.data_entities import table_mentions

    files = {
        "r/app/a.py": 'conn.execute("SELECT * FROM users.orders")',
        "r/app/b.py": "# SELECT * FROM users\nx = 1",
        "r/app/c.java": "// SELECT * FROM users\n/* UPDATE users SET x = 1 */ int y = 0;",
        "r/app/d.sql": "-- SELECT * FROM users\nSELECT 1;",
        "r/app/e.py": 'conn.execute("SELECT * FROM users")  # the real use',
    }

    found = table_mentions({"user": ["users"], "order": ["orders"]}, files)

    assert found == {"user": ["r/app/e.py"], "order": ["r/app/a.py"]}


def test_ancestry_does_not_follow_an_ambiguous_base_name():
    """Two types named Base: an ORM base and an unrelated one. Thing(Base) cannot be told apart, so it is no ORM entity."""
    types = [
        _t("Base", "r/orm/base.py", bases=["DeclarativeBase"]),
        _t("Base", "r/ui/base.py"),
        _t("Thing", "r/ui/thing.py", bases=["Base"]),
        _t("Order", "r/orm/order.py", bases=["OrmBase"]),
        _t("OrmBase", "r/orm/ormbase.py", bases=["DeclarativeBase"]),
    ]

    result = detect_entities(types, {}, {}, RULES)

    assert _names(result) == ["Order"]  # one unambiguous step through OrmBase still counts


def test_a_generated_table_follows_a_type_with_a_name_outside_ascii():
    """Names in other scripts keep their letters: two such types never share an empty key."""
    types = [
        _t("Заказ", "r/orm/order.py", decorators=["Entity"]),
        _t("Клиент", "r/orm/client.py", decorators=["Entity"]),
        _t("ЗАКАЗ", "r/db/setup.sql", category="table"),
    ]

    result = detect_entities(types, {}, {}, RULES)

    by_name = {e.name_candidates[0][0]: e for e in result.entities}
    assert sorted(by_name) == ["Заказ", "Клиент"]
    assert len(by_name["Заказ"].type_ids) == 2 and len(by_name["Клиент"].type_ids) == 1  # the table follows its own type
