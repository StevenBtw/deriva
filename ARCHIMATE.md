# ArchiMate Reference Guide

This guide documents ArchiMate 3.2 knowledge for Deriva's derivation pipeline. It provides element definitions, relationship rules, and metamodel constraints used to transform code repositories into enterprise architecture models.

> **Source:** Gerben Wierda, *Mastering ArchiMate Edition 3.2*

---

## Table of Contents

- [Core Concepts](#core-concepts)
- [The Three Aspects](#the-three-aspects)
- [The Three Layers](#the-three-layers)
- [Application Layer Elements](#application-layer-elements)
- [Business Layer Elements](#business-layer-elements)
- [Technology Layer Elements](#technology-layer-elements)
- [Relationships](#relationships)
- [Derived Relations](#derived-relations)
- [Non-Core Domains](#non-core-domains)
- [Common Pitfalls](#common-pitfalls)
- [BPMN Integration](#bpmn-integration)
- [References](#references)

---

## Core Concepts

ArchiMate is a visual language for enterprise architecture modeling. It provides a uniform representation for diagrams that describe enterprise architectures, covering business, application, and technology layers.

### The ArchiMate Grammar

Almost all of ArchiMate is built from three types of elements connected by relations:

```text
[Active Element] ──performs──> [Behavior] ──acts upon──> [Passive Element]
     (WHO)                       (WHAT)                    (ON WHAT)
```

This mirrors natural language: Subject → Verb → Object.

**Example:** A pickpocket (active) steals (behavior) a wallet (passive).

### The ArchiMate Map

| Domain | Description | Elements |
|--------|-------------|----------|
| **Strategy** | Capabilities and resources | Capability, Resource, Course of Action |
| **Business** | Business processes and actors | BusinessProcess, BusinessActor, BusinessObject |
| **Application** | Software applications | ApplicationComponent, ApplicationService, DataObject |
| **Technology** | Infrastructure | Node, Device, SystemSoftware, TechnologyService |
| **Implementation & Migration** | Change management | Plateau, Gap, WorkPackage, Deliverable |
| **Motivation** | Goals and requirements | Goal, Requirement, Driver, Stakeholder |

---

## The Three Aspects

Every ArchiMate element falls into one of three aspects:

| Aspect | Definition | Role | Language |
|--------|------------|------|----------|
| **Active Structure** | Elements that can act (subjects) | WHO performs | Structural nouns: "contains", "comprises" |
| **Behavior** | What active elements do (verbs) | WHAT is performed | Action verbs: "processes", "validates" |
| **Passive Structure** | Elements acted upon (objects) | ON WHAT | Passive nouns: "represents", "is accessed by" |

### Aspect-Based Element Classification

| Layer | Active Structure | Behavior | Passive Structure |
|-------|------------------|----------|-------------------|
| **Business** | BusinessActor, BusinessRole | BusinessProcess, BusinessFunction, BusinessEvent, BusinessService | BusinessObject |
| **Application** | ApplicationComponent, ApplicationCollaboration | ApplicationFunction, ApplicationProcess, ApplicationInteraction, ApplicationService, ApplicationEvent | DataObject |
| **Technology** | Node, Device, SystemSoftware | TechnologyFunction, TechnologyProcess, TechnologyService, TechnologyEvent | Artifact |

### Derivation Sequence

Derive elements in aspect order (Active → Behavior → Passive) across all layers:

```text
Phase 1 (Active):   ApplicationComponent, Node, Device, SystemSoftware, BusinessActor
Phase 2 (Behavior): ApplicationService, ApplicationInterface, TechnologyService, BusinessFunction, BusinessProcess, BusinessEvent
Phase 3 (Passive):  DataObject, BusinessObject
```

This ensures:
- Active elements exist before Behavior elements reference "who performs"
- Behavior elements exist before Passive elements reference "what accesses"

---

## The Three Layers

### Layer Relationships

ArchiMate's core is organized into three layers that can serve each other:

```text
┌─────────────────────────────────────────────────────────────┐
│                     BUSINESS LAYER                          │
│   BusinessActor → BusinessProcess → BusinessObject          │
└─────────────────────┬───────────────────────────────────────┘
                      │ Serving ↑
┌─────────────────────▼───────────────────────────────────────┐
│                   APPLICATION LAYER                          │
│   ApplicationComponent → ApplicationService → DataObject     │
└─────────────────────┬───────────────────────────────────────┘
                      │ Serving ↑
┌─────────────────────▼───────────────────────────────────────┐
│                   TECHNOLOGY LAYER                           │
│   Node/Device → TechnologyService → Artifact                 │
└─────────────────────────────────────────────────────────────┘
```

### Layer Semantics

| Layer | Focus | Typical Sources in Code |
|-------|-------|-------------------------|
| **Business** | What the organization does | Domain concepts, workflows, user roles |
| **Application** | How software supports business | Modules, services, APIs, data models |
| **Technology** | Infrastructure that runs applications | Servers, databases, networks, containers |

---

## Application Layer Elements

### ApplicationComponent

**Definition:** A modular, deployable part of a software system that encapsulates behavior and data.

| Aspect | Active Structure (Internal) |
|--------|----------------------------|
| Code Signals | Directories, packages, modules, namespaces |
| Naming | Directory-based: "CLI Component", "Services Component" |
| Identifier | `ac_<functional_area>` |

**Key distinction:** ApplicationComponent is a structural container. It realizes services but doesn't directly serve users.

### ApplicationInterface

**Definition:** A point of access where application services are made available to external consumers.

| Aspect | Active Structure (External) |
|--------|----------------------------|
| Code Signals | API endpoints, routes, controllers, CLI commands |
| Naming | Capability-based: "CLI Interface", "User API" |
| Identifier | `ai_<interface_type>` |

**Key distinction:** ApplicationInterface is the access point (the "door"), not the service behind it.

### ApplicationService

**Definition:** An explicitly defined exposed behavior that fulfills a need.

| Aspect | Behavior (External) |
|--------|---------------------|
| Code Signals | Service classes, handlers, use case implementations |
| Naming | Verb phrases: "Invoice Processing", "User Authentication" |
| Identifier | `as_<service_description>` |

**Key distinction:** ApplicationService is what the application *does*, not what it *is*.

### DataObject

**Definition:** Data structured for automated processing by applications.

| Aspect | Passive Structure |
|--------|-------------------|
| Code Signals | ORM models, schemas, config files, data files |
| Naming | Singular nouns: "Environment Configuration", "User Profile" |
| Identifier | `do_<data_description>` |

**Key distinction:** DataObject is Application-layer data. BusinessObject is its Business-layer abstraction.

---

## Business Layer Elements

### BusinessActor

**Definition:** A business entity that is capable of performing behavior.

| Aspect | Active Structure |
|--------|------------------|
| Code Signals | User roles, authentication decorators, actor patterns |
| Naming | Role nouns: "Customer", "Administrator", "API Consumer" |
| Identifier | `ba_<actor_name>` |

**Key distinction:** BusinessActor is the *real* actor (person, department, system). BusinessRole is abstract responsibility.

### BusinessProcess

**Definition:** A sequence of business behaviors that achieves a defined outcome.

| Aspect | Behavior |
|--------|----------|
| Code Signals | Workflow orchestrators, multi-step handlers, saga patterns |
| Naming | Verb phrases: "Order Fulfillment", "User Onboarding" |
| Identifier | `bp_<process_description>` |

**Key distinction:** BusinessProcess is causally-related (step A leads to step B). BusinessFunction is grouped by capability.

### BusinessFunction

**Definition:** A collection of business behavior based on chosen criteria (skills, resources).

| Aspect | Behavior |
|--------|----------|
| Code Signals | Capability groupings, functional modules |
| Naming | Capability nouns: "Customer Management", "Reporting" |
| Identifier | `bf_<function_description>` |

**Key distinction:** BusinessFunction groups behaviors by capability. BusinessProcess groups by outcome.

### BusinessObject

**Definition:** A passive element that has relevance from a business perspective.

| Aspect | Passive Structure |
|--------|-------------------|
| Code Signals | Domain entities, business concepts, document types |
| Naming | Singular nouns: "Invoice", "Customer", "Order" |
| Identifier | `bo_<object_name>` |

**Key distinction:** BusinessObject is the business abstraction. DataObject is its application-level representation.

### BusinessEvent

**Definition:** Something that happens instantaneously and triggers or is triggered by behavior.

| Aspect | Behavior |
|--------|----------|
| Code Signals | Event classes, signal handlers, webhooks, triggers |
| Naming | Past tense or event nouns: "Order Placed", "Payment Received" |
| Identifier | `be_<event_description>` |

**Key distinction:** BusinessEvent marks a point in time. BusinessProcess is a duration.

---

## Technology Layer Elements

### Node

**Definition:** A computational or physical resource that hosts, manipulates, or interacts with other elements.

| Aspect | Active Structure |
|--------|------------------|
| Code Signals | Docker/container configs, server definitions, cloud resources |
| Naming | Infrastructure nouns: "Web Server", "Database Server" |
| Identifier | `node_<resource_name>` |

**Key distinction:** Node is abstract infrastructure. Device is physical hardware.

### Device

**Definition:** A physical IT resource upon which system software and artifacts may be deployed.

| Aspect | Active Structure |
|--------|------------------|
| Code Signals | Hardware references, IoT definitions, equipment |
| Naming | Hardware nouns: "Load Balancer", "Storage Array" |
| Identifier | `device_<hardware_name>` |

### SystemSoftware

**Definition:** Software that provides or contributes to an environment for running other software.

| Aspect | Active Structure |
|--------|------------------|
| Code Signals | Runtime dependencies, OS references, platform tools |
| Naming | Platform nouns: "Python Runtime", "PostgreSQL", "Docker Engine" |
| Identifier | `ss_<software_name>` |

**Key distinction:** SystemSoftware is platform/infrastructure software. ApplicationComponent is business-specific software.

### TechnologyService

**Definition:** An explicitly defined exposed technology functionality.

| Aspect | Behavior |
|--------|----------|
| Code Signals | External service integrations, infrastructure APIs |
| Naming | Service nouns: "Database Service", "Message Queue", "File Storage" |
| Identifier | `ts_<service_name>` |

---

## Relationships

### Core Relationship Types

| Relationship | Symbol | Meaning | Example |
|--------------|--------|---------|---------|
| **Composition** | `◆────` | Parent contains child (strong) | Module contains submodules |
| **Aggregation** | `◇────` | Parent groups child (weak) | Package includes classes |
| **Assignment** | `●────▶` | Actor performs behavior | Role performs process |
| **Realization** | `────▷` | Internal creates external | Class implements interface |
| **Serving** | `────▶` | Provides functionality to | Service serves component |
| **Access** | `<──>` | Reads/writes data | Process accesses object |
| **Flow** | `- - ▶` | Information/material transfer | Data flows between processes |
| **Triggering** | `────▶` | Temporal/causal dependency | Event triggers process |

### Relationship Constraints by Aspect

| Relationship | Valid Sources | Valid Targets |
|--------------|---------------|---------------|
| **Composition** | Structure, Passive | Structure, Passive (same-type always allowed) |
| **Aggregation** | Structure, Behavior | Structure, Behavior, Passive |
| **Assignment** | Structure | Behavior |
| **Realization** | Structure, Behavior | Behavior, Passive |
| **Serving** | Structure, Behavior | Structure, Behavior |
| **Access** | Structure, Behavior | **Passive only** |
| **Flow** | **Behavior only** | **Behavior only** |
| **Triggering** | **Behavior only** | **Behavior only** |

### Invalid Relationship Types

The following are NOT valid ArchiMate relationships:

| Invalid Type | Use Instead |
|--------------|-------------|
| Association | Serving, Flow, or Access (be specific) |
| Dependency | Serving |
| Uses | Serving |
| Implements | Realization |
| Contains | Composition |

---

## Derived Relations

Derived relations are shortcuts that summarize a dependency path between elements.

### Relation Strength (Weakest to Strongest)

**Structural:** Realization < Assignment < Aggregation < Composition

**Dependency:** Association < Influence < Access < Serving

### Derivation Rules

1. **Structural chain:** The derived relation is the weakest relation found
2. **Structural + Dependency:** Move dependency endpoint backward over structural = valid shortcut
3. **Dynamic relations (Flow, Triggering):** Move endpoints to structural parents

**Caution:** Derived relations are useful for summary views but have limitations:
- Cannot allow all meaningful conclusions
- May allow false conclusions
- Use basic metamodel relations in actual models

---

## Non-Core Domains

### Strategy Layer

| Element | Definition | Realized By |
|---------|------------|-------------|
| **Capability** | High-level ability (existing or desired) | BusinessFunction, ApplicationService |
| **Resource** | Asset the organization controls | Core structural elements |
| **Course of Action** | Strategic decision | BusinessProcess, ApplicationService |

### Motivation Layer

| Element | Definition |
|---------|------------|
| **Goal** | End state stakeholder wants to achieve |
| **Requirement** | Obligatory aspect of a solution |
| **Stakeholder** | Role interested in outcomes |
| **Driver** | Force that motivates change |
| **Constraint** | Restriction on solutions |
| **Principle** | Generalized guidance for architecture |

### Implementation & Migration

| Element | Definition |
|---------|------------|
| **Plateau** | State of the enterprise at a point in time |
| **Gap** | Difference between plateaus |
| **WorkPackage** | Collection of actions to achieve objectives |
| **Deliverable** | Output of a work package |

---

## Common Pitfalls

### Pitfall 1: Confusing ApplicationComponent and ApplicationInterface

**Wrong:** Creating an ApplicationInterface that contains services
**Right:** ApplicationInterface is an access point; ApplicationComponent contains services

### Pitfall 2: Confusing BusinessObject and DataObject

**Wrong:** Creating DataObject for domain concepts
**Right:**
- DataObject = Application-layer data (config files, schemas)
- BusinessObject = Business-layer concepts (Invoice, Customer)

### Pitfall 3: Using Association Instead of Specific Relations

**Wrong:** "A is associated with B"
**Right:** Be specific - "A serves B" or "A flows to B"

### Pitfall 4: Mixing Process and Function

**Wrong:** Creating BusinessProcess for capability groupings
**Right:**
- BusinessProcess = Causal sequence producing an outcome
- BusinessFunction = Capability grouping by skills/resources

### Pitfall 5: Circular Composition

**Wrong:** A contains B, B contains A
**Right:** Composition is strictly hierarchical (tree structure)

### Pitfall 6: Flow Between Non-Behavior Elements

**Wrong:** DataObject flows to BusinessObject
**Right:** Flow is only between Behavior elements. Use Access for data relationships.

---

## BPMN Integration

ArchiMate and BPMN can be linked to create comprehensive process documentation.

### BPMN to ArchiMate Mapping

| BPMN Element | ArchiMate Element | Relationship |
|--------------|-------------------|--------------|
| Pool | BusinessProcess | Equivalence |
| Lane | BusinessRole | Assignment |
| Task | Activity within BusinessProcess | Part of |
| User Task | ApplicationService serving BusinessProcess | Serving |
| System Task | ApplicationService (automated) | Realization |
| Data Object | DataObject | Equivalence |
| Data Store | Artifact | Equivalence |

### Integration Patterns

**Pattern 1: Process-Service Linkage**
```text
BPMN Task ←── uses ──→ ArchiMate ApplicationService
```

**Pattern 2: Role-Lane Linkage**
```text
BPMN Lane ←── performed by ──→ ArchiMate BusinessRole
```

**Pattern 3: Automated Task**
```text
BPMN System Task ←── realized by ──→ ArchiMate ApplicationComponent
```

---

## References

### Official Standards

| Resource | URL |
|----------|-----|
| ArchiMate 3.2 Specification | https://pubs.opengroup.org/architecture/archimate32-doc/ |
| ArchiMate Relationships (Appendix B) | https://pubs.opengroup.org/architecture/archimate3-doc/ch-relationships-Normative.html |

### Books

| Title | Author | Focus |
|-------|--------|-------|
| *Mastering ArchiMate Edition 3.2* | Gerben Wierda | Comprehensive guide with patterns |
| *Enterprise Architecture at Work* | Marc Lankhorst | Theoretical foundations |

### Online Resources

| Resource | URL |
|----------|-----|
| ArchiMate Best Practices | https://github.com/AlbertoDMendoza/ArchiMateBestPractices |
| ArchiMate Cookbook | https://www.hosiaisluoma.fi/blog/archimate/ |
| ArchiMate Cheat Sheet | https://gbruneau.github.io/ArchiMate/ |
| ArchiMetric Guide | https://www.archimetric.com/ |

---

*ArchiMate is a registered trademark of The Open Group.*
