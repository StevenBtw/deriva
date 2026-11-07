"""The TypeScript extractor: the TypeScript grammar (TSX for .tsx) with what TypeScript has beyond JavaScript."""

from __future__ import annotations

from deriva.adapters.treesitter import TreeSitterManager
from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.typescript import TypeScriptExtractor

SERVICE = """import { Injectable } from '@angular/core';
import type { Order } from './order';

export interface Repository<T> extends Reader<T>, ns.Writer {
  find(id: string): Promise<T>;
}

export type OrderId = string;

export enum Status { Open = 'open', Closed = 'closed' }

@Entity('orders')
@Injectable()
export abstract class BaseService<T> extends Base<T> implements Repository<T>, Auditable {
  constructor(private http: HttpClient, public name?: string, ...rest: number[]) {}

  @Get(':id')
  async find(id: string = 'x'): Promise<T> {
    const raw = await this.http.get<T>(`/api/${id}`);
    return this.map(raw);
  }

  protected abstract map(raw: unknown): T;
}

export function total(orders: Order[], tax = 0.2): number {
  return orders.reduce((sum, o) => sum + o.amount, 0) * (1 + tax);
}

export const handler = async (event: Event): Promise<void> => { await process(event); };
"""

COMPONENT = """import React from 'react';
export interface Props { title: string }
export function Header({ title }: Props): JSX.Element {
  return <h1 className="title">{format(title)}</h1>;
}
"""


def _all(text: str, path: str) -> dict:
    return TreeSitterManager().extract_all(text, path)


def test_the_extractor_is_registered_as_typescript():
    assert isinstance(get_extractor("typescript"), TypeScriptExtractor)
    assert TypeScriptExtractor().grammar_for("src/App.tsx") == "tsx"
    assert TypeScriptExtractor().grammar_for("src/order.service.ts") == "typescript"


def test_interfaces_type_aliases_and_enums_are_types_with_their_bases():
    types = {t.name: t for t in _all(SERVICE, "web/order.service.ts")["types"]}

    assert (types["Repository"].kind, types["Repository"].bases) == ("interface", ["Reader", "ns.Writer"])
    assert (types["OrderId"].kind, types["Status"].kind) == ("type_alias", "enum")


def test_an_abstract_class_has_its_base_its_interfaces_and_its_decorators():
    base = {t.name: t for t in _all(SERVICE, "web/order.service.ts")["types"]}["BaseService"]

    assert (base.kind, base.bases, base.decorators) == ("class", ["Base", "Repository", "Auditable"], ["Entity", "Injectable"])


def test_methods_keep_their_typed_parameters_return_type_decorators_and_accessibility():
    methods = {(m.class_name, m.name): m for m in _all(SERVICE, "web/order.service.ts")["methods"]}

    constructor = methods[("BaseService", "constructor")]
    assert [(p["name"], p["annotation"], p["has_default"]) for p in constructor.parameters] == [
        ("http", "HttpClient", False),
        ("name", "string", True),  # optional
        ("...rest", "number[]", False),
    ]
    find = methods[("BaseService", "find")]
    assert (find.return_annotation, find.decorators, [p["has_default"] for p in find.parameters]) == ("Promise<T>", ["Get"], [True])
    assert methods[(None, "total")].return_annotation == "number"


def test_an_exported_arrow_function_is_a_type_a_method_and_a_caller():
    data = _all(SERVICE, "web/order.service.ts")

    assert "handler" in {t.name for t in data["types"]}
    assert [p["annotation"] for p in next(m for m in data["methods"] if m.name == "handler").parameters] == ["Event"]
    assert ("handler", "process") in {(c.caller_name, c.callee_name) for c in data["calls"]}


def test_an_awaited_call_with_type_arguments_names_its_method():
    """The TypeScript grammar parses ``await this.http.get<T>(...)`` as a call of ``await this.http.get``."""
    calls = {(c.caller_name, c.callee_name, c.callee_qualifier) for c in _all(SERVICE, "web/order.service.ts")["calls"]}

    assert ("find", "get", "this.http") in calls and ("find", "map", "this") in calls


def test_a_tsx_file_is_read_with_the_tsx_grammar():
    """JSX inside TypeScript: with the TypeScript grammar the component is a parse error, with TSX it is read."""
    data = _all(COMPONENT, "web/Header.tsx")

    assert {(t.name, t.kind) for t in data["types"]} == {("Header", "function"), ("Props", "interface")}
    assert next(m for m in data["methods"] if m.name == "Header").return_annotation == "JSX.Element"
    assert ("Header", "format") in {(c.caller_name, c.callee_name) for c in data["calls"]}


def test_javascript_is_unchanged_by_the_typescript_extractor():
    """A .js file still goes to the JavaScript extractor and grammar."""
    data = _all("export class A extends B { m() { return f(); } }\n", "web/a.js")

    assert [(t.name, t.bases) for t in data["types"]] == [("A", ["B"])]
