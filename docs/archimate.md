# ArchiMate

ArchiMate is the open standard for describing an enterprise architecture: who acts, what they do and what they work on, across business, applications and technology. Deriva derives 13 of its element types and 8 of its relationship types from a code repository; this page explains each one and where Deriva finds it in code.

Deriva follows ArchiMate 3.2, the current version of the standard published by The Open Group.

## The ArchiMate grammar

Almost every ArchiMate statement has the same shape: an active element performs behavior on a passive element.

```text
[Active structure] --performs--> [Behavior] --acts on--> [Passive structure]
      (who)                        (what)                    (on what)
```

This mirrors a sentence: subject, verb, object. A clerk (active) approves (behavior) a request (passive).

### Three aspects

| Aspect | Meaning | Examples |
| --- | --- | --- |
| Active structure | Elements that can act | BusinessActor, ApplicationComponent, Node |
| Behavior | What active elements do | BusinessProcess, ApplicationService, TechnologyService |
| Passive structure | Elements that are acted on | BusinessObject, DataObject |

### Three layers

The core of ArchiMate has three layers, and each layer serves the one above it:

```text
+--------------------------------------------------------------+
|  Business layer      what the organization does              |
+--------------------------------------------------------------+
        ^ serves
+--------------------------------------------------------------+
|  Application layer   the software that supports it           |
+--------------------------------------------------------------+
        ^ serves
+--------------------------------------------------------------+
|  Technology layer    the infrastructure the software runs on |
+--------------------------------------------------------------+
```

### The types Deriva derives

| Layer | Active structure | Behavior | Passive structure |
| --- | --- | --- | --- |
| Business | BusinessActor | BusinessProcess, BusinessFunction, BusinessEvent | BusinessObject |
| Application | ApplicationComponent, ApplicationInterface | ApplicationService | DataObject |
| Technology | Node, Device, SystemSoftware | TechnologyService | |

ArchiMate defines more types in these layers (for example BusinessRole, ApplicationFunction and Artifact) and in other domains; Deriva does not derive them. See [Beyond what Deriva derives](#beyond-what-deriva-derives).

## Application layer

### ApplicationComponent

A modular, deployable part of a software system that encapsulates behavior and data.

- **Aspect:** active structure.
- **Deriva's candidates:** the repository's directories.
- **Naming:** after the part of the system it is, usually the directory's name.

ApplicationComponent is a structural container: it realizes services, but it does not serve users directly.

### ApplicationInterface

A point of access where application services are made available to users or other systems.

- **Aspect:** active structure (the external side of a component).
- **Deriva's candidates:** source files whose names point at routes, endpoints, controllers or command line entry points, and public methods with route or command decorators, if they matter in the graph.
- **Naming:** after the kind of access: "REST API", "Command Line Interface".

An ApplicationInterface is the door, not the service behind it.

### ApplicationService

An explicitly defined behavior that the application exposes.

- **Aspect:** behavior.
- **Deriva's candidates:** business concepts classified as a service or capability, and types whose name ends in "Service".
- **Naming:** a verb phrase for what it does: "Data Validation", "Report Generation".

ApplicationService is what the application does, not what it is.

### DataObject

Data structured for automated processing.

- **Aspect:** passive structure.
- **Deriva's candidates:** schema files (Avro, Protocol Buffers, XSD, GraphQL, Thrift), types marked as persistent entities, and types whose names mark them as data (for example ending in Dto, Record, Entity or Schema). Build output, vendored code and tests are left out.
- **Naming:** a singular noun phrase.

DataObject is application-level data. Its business-level counterpart is BusinessObject.

## Business layer

Business elements draw on the business concepts that Deriva finds in the repository's documentation: candidate terms that the BusinessConcept extraction step accepts and classifies as an actor, process, function, event, entity or service. A repository with little documentation can end up with few or no business elements. That is intended: an empty business layer is better than one filled with technical elements.

### BusinessActor

A business entity that can perform behavior: a person, a department or an outside organization.

- **Aspect:** active structure.
- **Deriva's candidates:** business concepts classified as actors.
- **Naming:** a role noun: "Administrator", "Supplier".

A BusinessActor is the real actor. A BusinessRole, which Deriva does not derive, is the responsibility it takes on.

### BusinessProcess

A sequence of business behavior that achieves a defined result.

- **Aspect:** behavior.
- **Deriva's candidates:** business concepts classified as processes.
- **Naming:** a verb phrase: "Request Approval".

A process is causal: one step leads to the next. A function groups behavior by capability instead.

### BusinessFunction

A collection of business behavior grouped by chosen criteria, such as required skills or resources.

- **Aspect:** behavior.
- **Deriva's candidates:** business concepts classified as functions.
- **Naming:** a capability noun: "Reporting", "Account Management".

### BusinessEvent

Something that happens at a moment in time and triggers or follows behavior.

- **Aspect:** behavior.
- **Deriva's candidates:** business concepts classified as events.
- **Naming:** past tense or an event noun: "Request Received".

An event is a point in time; a process has a duration.

### BusinessObject

A passive element that matters from a business point of view.

- **Aspect:** passive structure.
- **Deriva's candidates:** business concepts classified as entities with high confidence, and types whose names mark them as domain data. Technical names (configuration, manager, handler and the like) are left out.
- **Naming:** a singular noun.

A BusinessObject is the business concept; a DataObject is how an application stores it.

## Technology layer

### Node

A computational or physical resource that hosts, manipulates or interacts with other elements.

- **Aspect:** active structure.
- **Deriva's candidates:** container and orchestration files (Dockerfiles, Compose and Kubernetes files) and technologies classified as a platform, infrastructure or system software.
- **Naming:** an infrastructure noun: "Application Server", "Container Host".

A Node is a logical resource; a Device is physical hardware.

### Device

A physical IT resource on which system software and artifacts are deployed.

- **Aspect:** active structure.
- **Deriva's candidates:** infrastructure-as-code files (Terraform, Ansible, CloudFormation) and technologies classified as infrastructure, services or frameworks with high confidence.
- **Naming:** a hardware noun: "Load Balancer", "Storage Array".

### SystemSoftware

Software that provides an environment for other software to run in.

- **Aspect:** active structure.
- **Deriva's candidates:** technologies classified as system software, platforms, infrastructure, frameworks or tools, and external dependencies that are runtimes, platforms, databases or external services.
- **Naming:** the product or platform: "Python Runtime", "Relational Database".

SystemSoftware is platform software. Software written for the organization itself is an ApplicationComponent.

### TechnologyService

Technology functionality that is explicitly exposed.

- **Aspect:** behavior.
- **Deriva's candidates:** technologies classified with high confidence as system software, services, infrastructure or platforms.
- **Naming:** a service noun: "Message Queuing", "File Storage".

The candidates listed on this page are Deriva's defaults. Each element type's candidates come from the graph query in its step configuration, which you can change (see [Optimization](optimization.md)).

## Relationships

### The relationships Deriva derives

| Relationship | Meaning | Example |
| --- | --- | --- |
| Composition | The whole consists of the part; the part cannot exist without it | A component consists of subcomponents |
| Aggregation | The whole groups the part; the part can exist on its own | A node groups the software deployed on it |
| Assignment | An active element performs a behavior | A component performs a service |
| Realization | Something concrete realizes something more abstract | A DataObject realizes a BusinessObject |
| Serving | An element provides its functionality to another | A service serves a process |
| Access | A behavior or active element reads or writes data | A service writes a DataObject |
| Flow | Information or value passes from one behavior to another | One process hands its result to the next |
| Triggering | One behavior or event causes another | An event triggers a process |

### Which relationships are allowed

ArchiMate defines exactly which relationship may connect which two element types, in the relationship tables of the specification (Appendix B). Deriva checks every relationship against those tables for the 13 types it derives. A relationship is kept only when the table allows it, either directly or as a derived relationship (see [Derived relationships](#derived-relationships)).

The tables follow from the grammar. A few consequences that are easy to forget:

- Access always points at passive structure (a BusinessObject or DataObject).
- Flow and Triggering connect behavior and events. Between active structure elements they are allowed only as derived relationships, standing for the behavior those elements perform.
- Assignment goes from active structure to the behavior it performs.

### Relationships Deriva does not propose

Association, Specialization and Influence are valid ArchiMate relationships, but Deriva does not propose them. Association says too little about how two elements relate, and code rarely holds the evidence that the other two need.

Words that sound like relationships but are not ArchiMate:

| Not ArchiMate | Use instead |
| --- | --- |
| Dependency, Uses | Serving |
| Implements | Realization |
| Contains | Composition or Aggregation |

### Derived relationships

A derived relationship summarizes a path of relationships as one shortcut. Relationships have a strength:

- **Structural**, from weak to strong: Realization, Assignment, Aggregation, Composition.
- **Dependency**, from weak to strong: Association, Influence, Access, Serving.

Along a chain of structural relationships, the derived relationship is the weakest one on the path. A dependency relationship can be moved back along the structural relationships before it. Flow and Triggering can be moved to the structural elements that perform the behavior.

Derived relationships help summary views, but a chain cannot support every conclusion, and some conclusions it suggests are wrong. Models should use the direct relationships where they can.

## How Deriva builds the model

### Identifiers come from the code

Each element's identifier is made of the initials of its type and the identifier of the graph node it was derived from. A component derived from a directory starts with `ac_` and continues with that directory's path, and a DataObject starts with `do_`. The same source therefore gives the same identifier in every run, whatever the LLM writes, and two runs on the same repository can be compared element by element.

### Order of derivation

Deriva derives elements in aspect order, so that the elements later steps refer to already exist: active structure first, then behavior, then passive structure. The default order is:

| Phase | Element types |
| --- | --- |
| Active structure | ApplicationComponent, Node, Device, SystemSoftware, BusinessActor |
| Behavior | ApplicationService, ApplicationInterface, TechnologyService, BusinessFunction, BusinessProcess, BusinessEvent |
| Passive structure | DataObject, BusinessObject |

Before the elements, a preparation phase runs graph algorithms (PageRank, Louvain communities, k-core, articulation points, degree) on the extracted graph. After them, Deriva derives the relationships in one pass over the complete set of elements and then runs refine steps that remove duplicates and check structure. `deriva-cli config list derivation` shows the steps in their order, and `deriva-cli config sequence` changes it.

## Common pitfalls

### ApplicationComponent and ApplicationInterface

An ApplicationInterface is an access point, not a container. Services belong to components; an interface only exposes them.

### BusinessObject and DataObject

A DataObject is data in an application (a schema, a stored record). A BusinessObject is the business concept behind it. A configuration file is never a BusinessObject.

### Process and function

A BusinessProcess is a causal sequence that produces a result. A BusinessFunction groups behavior by capability. A capability grouping modelled as a process reads as a sequence that does not exist.

### Circular composition

Composition is strictly hierarchical: if A consists of B, B cannot consist of A.

### Flow between structure elements

Flow connects behavior. Between data and the behavior that uses it, use Access.

### Association as a default

"A is associated with B" says almost nothing. Say what the relationship is: A serves B, A accesses B, A flows to B.

## Beyond what Deriva derives

ArchiMate covers more than the three core layers. Deriva does not derive these domains, but its models can be extended with them by hand, for example in Archi.

### Strategy

| Element | Meaning |
| --- | --- |
| Capability | An ability the organization has or wants |
| Resource | An asset the organization controls |
| Course of Action | An approach for reaching a goal |

### Motivation

| Element | Meaning |
| --- | --- |
| Stakeholder | A role with an interest in the outcome |
| Driver | A force that motivates change |
| Goal | An end state a stakeholder wants |
| Requirement | Something a solution must provide |
| Constraint | A restriction on solutions |
| Principle | General guidance for the architecture |

### Implementation and migration

| Element | Meaning |
| --- | --- |
| Work Package | A set of actions to reach an objective |
| Deliverable | The result of a work package |
| Plateau | The state of the architecture at a point in time |
| Gap | The difference between two plateaus |

### ArchiMate and BPMN

ArchiMate describes the architecture; BPMN describes processes in detail. The two connect like this:

| BPMN | ArchiMate |
| --- | --- |
| Pool or process | BusinessProcess |
| Lane | BusinessRole, assigned to the process |
| User task | An ApplicationService serving the process |
| Automated task | An ApplicationService that realizes the step |
| Data object | DataObject |

## References

### Standards

- [ArchiMate 3.2 Specification](https://pubs.opengroup.org/architecture/archimate32-doc/), The Open Group
- [ArchiMate relationship tables](https://pubs.opengroup.org/architecture/archimate32-doc/), Appendix B of the specification

### Books

- Gerben Wierda, *Mastering ArchiMate Edition 3.2*: a thorough guide with modelling patterns
- Marc Lankhorst, *Enterprise Architecture at Work*: the theory behind ArchiMate

### Online

- [ArchiMate Best Practices](https://github.com/AlbertoDMendoza/ArchiMateBestPractices)
- [ArchiMate Cookbook](https://www.hosiaisluoma.fi/blog/archimate/)
- [ArchiMate Cheat Sheet](https://gbruneau.github.io/ArchiMate/)

ArchiMate is a registered trademark of The Open Group.
