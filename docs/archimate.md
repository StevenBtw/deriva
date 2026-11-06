# ArchiMate

ArchiMate is the open standard for describing an enterprise architecture: who acts, what they do and what they work on, across business, applications and technology. By default Deriva derives 13 of its element types and 8 of its relationship types from a code repository; this page explains each one and where Deriva finds it in code. Every other core type has a step that is off by default; most of these steps are experimental.

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
| Business | BusinessActor, BusinessRole | | BusinessObject |
| Application | ApplicationComponent, ApplicationInterface | ApplicationService, ApplicationFunction | DataObject |
| Technology | Node, SystemSoftware | TechnologyService, TechnologyFunction | Artifact |

BusinessProcess, BusinessFunction, BusinessEvent and Device have steps that are off by default, and the remaining core types have experimental steps (see [Beyond what Deriva derives](#beyond-what-deriva-derives)). A step is switched on in the studio's Output ontology page or with `deriva-cli config enable derivation <step>`.

## Application layer

### ApplicationComponent

A modular, deployable part of a software system that encapsulates behavior and data.

- **Aspect:** active structure.
- **Deriva's candidates:** the repository's deployable units (a folder that a container file, a web entry point or a manifest's entry point builds) and its build modules (libraries, and aggregators that become systems). Units the LLM marks as tooling around the product are left out, and one LLM choice per repository can group the top-level components into applications.
- **Naming:** after the product and the part it is, from the README title, the manifest and the folder.

ApplicationComponent is a structural container: it realizes services, but it does not serve users directly.

### ApplicationInterface

A point of access where application services are made available to users or other systems.

- **Aspect:** active structure (the external side of a component).
- **Deriva's candidates:** source files whose names point at routes, endpoints, controllers or command line entry points, public methods with route or command decorators, controller classes, mainframe screens and batch jobs that run programs; the LLM decides which of them are interfaces and of what kind.
- **Naming:** after the kind of access: "REST API", "Command Line Interface".

An ApplicationInterface is the door, not the service behind it.

### ApplicationService

An explicitly defined behavior that the application exposes.

- **Aspect:** behavior.
- **Deriva's candidates:** each component's interfaces and the operations behind them, grouped into the services the component offers.
- **Naming:** an activity on an object, such as "Customer Management" or "Report Generation". The activity comes from the kind of interface, and the LLM chooses the object among name candidates from the component's code and documentation.

ApplicationService is what the application does, not what it is.

### ApplicationFunction

Automated behavior that an application component performs.

- **Aspect:** behavior.
- **Deriva's candidates:** every component that is a deployable unit, a library or a feature package gets one, its main behavior; no LLM call.
- **Naming:** after its component.

### DataObject

Data structured for automated processing.

- **Aspect:** passive structure.
- **Deriva's candidates:** persistent data the code defines: aggregate roots, ORM entities, shared mainframe records and DDL tables. Value objects, identifiers, DTOs and configuration classes are left out, and so is test code.
- **Naming:** a singular noun phrase.

DataObject is application-level data. Its business-level counterpart is BusinessObject.

## Business layer

Business elements come from structure where the code shows them: the roles and actors the code names, and the data domains that group its data entities. The documentation adds the actors it names next to the system, which the LLM picks from. A repository with little of either can end up with few or no business elements. That is intended: an empty business layer is better than one filled with technical elements.

### BusinessActor

A business entity that can perform behavior: a person, a department or an outside organization.

- **Aspect:** active structure.
- **Deriva's candidates:** the people and organizations the code names (user types, actor constants), and those the documentation names next to the system, chosen by the LLM.
- **Naming:** a noun for who it is: "Customer", "Supplier".

A BusinessActor is the real actor; a BusinessRole is the responsibility it takes on.

### BusinessRole

The responsibility for behavior that an actor can be assigned to.

- **Aspect:** active structure.
- **Deriva's candidates:** the roles the code names as such: role constants, permission roles and the roles that routes require; no LLM call.
- **Naming:** a role noun: "Administrator", "Underwriter".

### BusinessObject

A passive element that matters from a business point of view.

- **Aspect:** passive structure.
- **Deriva's candidates:** data domains, groups of data entities that one business object stands for (an aggregate and the entities it holds). Configuration classes and technically named tables and records are left out; so are domains that only identify something and domains of tables without code behind them.
- **Naming:** a singular noun.

A BusinessObject is the business concept; a DataObject is how an application stores it.

### BusinessProcess, BusinessFunction and BusinessEvent

Their steps are off by default. The BusinessProcess step reads the lifecycles of business objects (the values of a status type and the code that sets them), named by what happens to the object; the BusinessEvent step reads the states of those lifecycles; the BusinessFunction step reads business concepts classified as functions.

A process is causal: one step leads to the next. A function groups behavior by capability instead. An event is a point in time; a process has a duration.

## Technology layer

### Node

A computational or physical resource that hosts, manipulates or interacts with other elements.

- **Aspect:** active structure.
- **Deriva's candidates:** the deployment environment the repository describes: Compose, Kubernetes, a cloud template or a mainframe setup.
- **Naming:** an infrastructure noun: "Container Platform", "Mainframe".

A Node is a logical resource; a Device is physical hardware. The Device step is off by default.

### SystemSoftware

Software that provides an environment for other software to run in.

- **Aspect:** active structure.
- **Deriva's candidates:** the software the deployments use, such as databases, message brokers, caches and runtimes.
- **Naming:** the product or platform: "PostgreSQL", "Relational Database".

SystemSoftware is platform software. Software written for the organization itself is an ApplicationComponent.

### TechnologyService and TechnologyFunction

Technology functionality that is explicitly exposed, and the internal behavior that realizes it.

- **Aspect:** behavior.
- **Deriva's candidates:** every technology realizer (the environment and the service software in it) whose kind a closed table names gets one function and one service; a kind the table does not list gets none. No LLM call.
- **Naming:** a service noun by the realizer's kind, such as "Data Storage"; the function is named after its realizer.

### Artifact

The deployable form of an application component: its image, package or bundle.

- **Aspect:** passive structure.
- **Deriva's candidates:** each deployable unit, library and static bundle gets one; no LLM call.
- **Naming:** after the component it deploys.

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

ArchiMate defines exactly which relationship may connect which two element types, in the relationship tables of the specification (Appendix B). Deriva checks every relationship against those tables, for every type it derives. A relationship is kept only when the table allows it, either directly or as a derived relationship (see [Derived relationships](#derived-relationships)).

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

Deriva derives elements in aspect order, so that the elements later steps refer to already exist: active structure first, then behavior, then passive structure. Steps that build on elements of those phases come after them, whatever their own aspect: an application service, for example, is built from the components, interfaces and objects derived before it, and a role is active structure but follows the elements it is built from. The default order is:

| Phase | Element types |
| --- | --- |
| Active structure | ApplicationComponent, Node, SystemSoftware, BusinessActor, ApplicationInterface |
| Behavior | TechnologyService |
| Passive structure | DataObject, BusinessObject |
| Built from the above | ApplicationService, ApplicationFunction, Artifact, BusinessRole, TechnologyFunction |
| Abstraction | The grouping of components into applications; BusinessActor from the documentation (the same type as above, from a second source) |

Steps that are off by default keep their place in this order when they are switched on.

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

### Experimental core types

The other core types of the three layers have a first, experimental step each, off by default: BusinessService, BusinessCollaboration, BusinessInterface, BusinessInteraction, Contract, Representation and Product; ApplicationCollaboration, ApplicationProcess, ApplicationInteraction and ApplicationEvent; TechnologyCollaboration, TechnologyInterface, TechnologyProcess, TechnologyInteraction, TechnologyEvent, Path and CommunicationNetwork. Each reads broad candidates from the graph, and one LLM call per batch keeps a candidate as the type or rejects it; a kept candidate keeps its own name, and its relationships are the direct ones the metamodel allows. Expect rough results.

### Other domains

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
