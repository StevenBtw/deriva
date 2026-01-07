-- Derivation Config Extension
-- Adds max_candidates and batch_size columns to derivation_config
-- Creates derivation_patterns table for configurable pattern matching

-- =============================================================================
-- SCHEMA EXTENSIONS
-- =============================================================================

-- Add max_candidates and batch_size columns to derivation_config
ALTER TABLE derivation_config ADD COLUMN IF NOT EXISTS max_candidates INTEGER DEFAULT 30;
ALTER TABLE derivation_config ADD COLUMN IF NOT EXISTS batch_size INTEGER DEFAULT 10;

-- Create derivation_patterns table
CREATE TABLE IF NOT EXISTS derivation_patterns (
    id INTEGER PRIMARY KEY,
    step_name VARCHAR NOT NULL,           -- e.g., "ApplicationService", "BusinessObject"
    pattern_type VARCHAR NOT NULL,        -- "include" or "exclude"
    pattern_category VARCHAR,             -- optional category for grouping (e.g., "lifecycle", "utility")
    patterns TEXT NOT NULL,               -- JSON array of pattern strings
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(step_name, pattern_type, pattern_category)
);

-- =============================================================================
-- UPDATE EXISTING DERIVATION_CONFIG WITH max_candidates AND batch_size
-- =============================================================================

-- ApplicationComponent
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'ApplicationComponent' AND is_active = TRUE;

-- ApplicationService
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'ApplicationService' AND is_active = TRUE;

-- ApplicationInterface
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'ApplicationInterface' AND is_active = TRUE;

-- DataObject
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'DataObject' AND is_active = TRUE;

-- BusinessProcess
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'BusinessProcess' AND is_active = TRUE;

-- BusinessObject
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'BusinessObject' AND is_active = TRUE;

-- BusinessFunction
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'BusinessFunction' AND is_active = TRUE;

-- BusinessEvent
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'BusinessEvent' AND is_active = TRUE;

-- BusinessActor (uses 20 max_candidates)
UPDATE derivation_config SET max_candidates = 20, batch_size = 10 WHERE step_name = 'BusinessActor' AND is_active = TRUE;

-- TechnologyService
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'TechnologyService' AND is_active = TRUE;

-- Node
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'Node' AND is_active = TRUE;

-- Device
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'Device' AND is_active = TRUE;

-- SystemSoftware
UPDATE derivation_config SET max_candidates = 30, batch_size = 10 WHERE step_name = 'SystemSoftware' AND is_active = TRUE;

-- =============================================================================
-- UPDATE INPUT_GRAPH_QUERY FOR GENERATE STEPS (using proper queries)
-- =============================================================================

-- ApplicationComponent: Query directories excluding build artifacts and static assets
UPDATE derivation_config SET input_graph_query = 'MATCH (n:`Graph:Directory`)
WHERE n.active = true
  AND NOT n.name IN [''__pycache__'', ''node_modules'', ''.git'', ''.venv'', ''venv'', ''dist'', ''build'',
                     ''static'', ''assets'', ''public'', ''images'', ''img'', ''css'', ''js'', ''fonts'',
                     ''templates'', ''views'', ''layouts'', ''partials'']
  AND NOT n.path =~ ''.*(test|spec|__pycache__|node_modules|\\.git|\\.venv|venv|dist|build).*''
RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties'
WHERE step_name = 'ApplicationComponent' AND is_active = TRUE;

-- ApplicationService: Query Method nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n:`Graph:Method`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.methodName) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'ApplicationService' AND is_active = TRUE;

-- BusinessObject: Query TypeDefinition and BusinessConcept nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n)
WHERE (n:`Graph:TypeDefinition` OR n:`Graph:BusinessConcept`)
  AND n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.typeName, n.conceptName) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'BusinessObject' AND is_active = TRUE;

-- BusinessProcess: Query Method nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n:`Graph:Method`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.methodName) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'BusinessProcess' AND is_active = TRUE;

-- BusinessActor: Query TypeDefinition and BusinessConcept nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n)
WHERE (n:`Graph:TypeDefinition` OR n:`Graph:BusinessConcept`)
  AND n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.typeName, n.conceptName) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'BusinessActor' AND is_active = TRUE;

-- DataObject: Query File nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n:`Graph:File`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.fileName, n.name) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'DataObject' AND is_active = TRUE;

-- TechnologyService: Query ExternalDependency nodes
UPDATE derivation_config SET input_graph_query = 'MATCH (n:`Graph:ExternalDependency`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.dependencyName, n.name) as name,
       labels(n) as labels,
       properties(n) as properties'
WHERE step_name = 'TechnologyService' AND is_active = TRUE;

-- =============================================================================
-- UPDATE INSTRUCTIONS FOR GENERATE STEPS
-- =============================================================================

-- ApplicationComponent instruction
UPDATE derivation_config SET instruction = 'You are identifying ApplicationComponent elements from source code directories.

An ApplicationComponent is a modular, deployable part of a system that:
- Encapsulates related functionality (not just a folder)
- Has clear boundaries and responsibilities
- Contains code that works together as a unit
- Could potentially be a separate module or package

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the directory is
- community: Which cluster of related code it belongs to
- kcore: How connected it is to the core codebase
- is_bridge: Whether it connects different parts of the codebase

Review each candidate and decide which should become ApplicationComponent elements.

INCLUDE directories that:
- Represent cohesive functional units (services, modules, packages)
- Have meaningful names indicating purpose
- Are structural roots of related code

EXCLUDE directories that:
- Are just organizational containers with no cohesive purpose
- Contain only configuration or static assets
- Are too granular (single-file directories)'
WHERE step_name = 'ApplicationComponent' AND is_active = TRUE;

-- ApplicationService instruction
UPDATE derivation_config SET instruction = 'You are identifying ApplicationService elements from source code methods.

An ApplicationService represents explicitly exposed application behavior:
- Web routes and API endpoints
- Service interfaces that external clients can call
- Handlers that respond to external requests

Each candidate includes method information and graph metrics.

Review each candidate and decide which should become ApplicationService elements.

INCLUDE methods that:
- Handle HTTP requests (routes, endpoints, views)
- Expose functionality to external clients
- Are entry points for user interactions
- Have names suggesting they respond to requests

EXCLUDE methods that:
- Are internal/private helpers
- Are utility functions
- Are lifecycle methods (__init__, setup, etc.)
- Only perform internal processing

When naming:
- Use service-oriented names (e.g., "Invoice Form Service" not "invoice_form")
- Describe what the service provides'
WHERE step_name = 'ApplicationService' AND is_active = TRUE;

-- BusinessObject instruction
UPDATE derivation_config SET instruction = 'You are identifying BusinessObject elements from source code type definitions.

A BusinessObject represents a passive element that has business relevance:
- Data entities that the business cares about (Customer, Order, Invoice)
- Domain concepts that appear in business conversations
- Information structures that would appear in business documentation

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the type is
- community: Which cluster of related types it belongs to
- in_degree: How many other types reference it (higher = more important)

Review each candidate and decide which should become BusinessObject elements.

INCLUDE types that:
- Represent real-world business concepts (Customer, Order, Product)
- Are data entities that store business information
- Would be meaningful to a business analyst (not just a developer)
- Have names that are nouns representing "things" the business cares about

EXCLUDE types that:
- Are purely technical (handlers, adapters, decorators)
- Are framework/library classes (BaseModel, FlaskForm)
- Are utility classes (StringHelper, DateUtils)
- Are internal implementation details
- Are exceptions or error types
- Are configuration or settings classes

When naming:
- Use business-friendly names (e.g., "Invoice" not "InvoiceModel")
- Capitalize appropriately (e.g., "Customer Order" not "customer_order")'
WHERE step_name = 'BusinessObject' AND is_active = TRUE;

-- BusinessProcess instruction
UPDATE derivation_config SET instruction = 'You are identifying BusinessProcess elements from source code methods.

A BusinessProcess represents a sequence of business behaviors that achieves
a specific outcome. It is NOT just any function - it represents a complete
business activity that delivers value.

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the method is
- in_degree/out_degree: How connected it is

Review each candidate and decide which should become BusinessProcess elements.

INCLUDE methods that:
- Represent complete business activities (Create Invoice, Process Payment)
- Coordinate multiple steps to achieve a business outcome
- Would be meaningful to a business analyst
- Are named with verbs indicating business actions

EXCLUDE methods that:
- Are purely technical (validation, parsing, formatting)
- Are framework lifecycle methods (__init__, setup, etc.)
- Are simple getters/setters
- Are utility/helper functions
- Only do one small technical step

When naming:
- Use business-friendly verb phrases (e.g., "Create Invoice" not "create_invoice")
- Focus on the business outcome, not technical implementation'
WHERE step_name = 'BusinessProcess' AND is_active = TRUE;

-- BusinessActor instruction
UPDATE derivation_config SET instruction = 'You are identifying BusinessActor elements from source code types and concepts.

A BusinessActor represents a business entity capable of performing behavior:
- Users and roles (Customer, Administrator, Operator)
- Organizational units (Department, Team)
- External parties (Supplier, Partner)
- System actors when they represent a logical role

Each candidate includes graph metrics to help assess importance.

Review each candidate and decide which should become BusinessActor elements.

INCLUDE types that:
- Represent people, roles, or organizational entities
- Can initiate or perform business activities
- Would appear in a business context diagram
- Have names indicating actors (User, Customer, Manager, etc.)

EXCLUDE types that:
- Represent data/information (Invoice, Order, Report)
- Are technical components (Controller, Handler, Service)
- Are utility/framework classes
- Are abstract base classes

When naming:
- Use role names (e.g., "Customer" not "CustomerModel")
- Be specific about the actor''s function'
WHERE step_name = 'BusinessActor' AND is_active = TRUE;

-- DataObject instruction
UPDATE derivation_config SET instruction = 'You are identifying DataObject elements from files in a codebase.

A DataObject represents data structured for automated processing:
- Database files (SQLite, SQL scripts)
- Configuration files (JSON, YAML, ENV)
- Schema definitions
- Data exchange formats

Each candidate includes file information and graph metrics.

Review each candidate and decide which should become DataObject elements.

INCLUDE files that:
- Store application data (databases, data files)
- Define configuration (settings, environment)
- Define data schemas or structures
- Are used for data exchange

EXCLUDE files that:
- Are source code (Python, JavaScript, etc.)
- Are templates (HTML, Jinja)
- Are documentation (README, docs)
- Are static assets (images, CSS)

When naming:
- Use descriptive names (e.g., "Application Database" not "database.db")
- Indicate the data''s purpose'
WHERE step_name = 'DataObject' AND is_active = TRUE;

-- TechnologyService instruction
UPDATE derivation_config SET instruction = 'You are identifying TechnologyService elements from external dependencies.

A TechnologyService represents an externally visible unit of functionality
provided by infrastructure or external systems, such as:
- Databases (PostgreSQL, MongoDB, Redis, etc.)
- Message queues (Kafka, RabbitMQ, etc.)
- External APIs and HTTP clients
- Cloud services (AWS S3, Azure Blob, etc.)
- Authentication services

Review each candidate dependency. Consider:
- Does this provide infrastructure functionality?
- Is it a service the application connects TO (not just a utility library)?
- Would it appear in an architecture diagram?

INCLUDE:
- Database drivers and ORMs (sqlalchemy, psycopg2, pymongo)
- HTTP clients for external APIs (requests, httpx, axios)
- Message queue clients (kafka-python, pika)
- Cloud SDK components (boto3, azure-storage)
- Caching services (redis, memcached)

EXCLUDE:
- Standard library modules
- Utility libraries (json parsing, date handling)
- Testing frameworks
- Development tools
- Internal application modules'
WHERE step_name = 'TechnologyService' AND is_active = TRUE;

-- =============================================================================
-- UPDATE EXAMPLES FOR GENERATE STEPS
-- =============================================================================

-- ApplicationComponent example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "appcomp_user_service",
      "name": "User Service",
      "documentation": "Handles user authentication, registration, and profile management",
      "source": "dir_myproject_src_services_user",
      "confidence": 0.9
    },
    {
      "identifier": "appcomp_frontend",
      "name": "Frontend Application",
      "documentation": "React-based web interface for the application",
      "source": "dir_myproject_frontend",
      "confidence": 0.85
    }
  ]
}'
WHERE step_name = 'ApplicationComponent' AND is_active = TRUE;

-- ApplicationService example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "as_invoice_form",
      "name": "Invoice Form Service",
      "documentation": "Web endpoint for creating and managing invoice data through a form interface",
      "source": "method_invoice_form",
      "confidence": 0.9
    },
    {
      "identifier": "as_export_pdf",
      "name": "PDF Export Service",
      "documentation": "Endpoint for generating and downloading invoice PDFs",
      "source": "method_invoice_pdf",
      "confidence": 0.85
    }
  ]
}'
WHERE step_name = 'ApplicationService' AND is_active = TRUE;

-- BusinessObject example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "bo_invoice",
      "name": "Invoice",
      "documentation": "A commercial document issued by a seller to a buyer, indicating products, quantities, and prices",
      "source": "type_Invoice",
      "confidence": 0.95
    },
    {
      "identifier": "bo_customer",
      "name": "Customer",
      "documentation": "A person or organization that purchases goods or services",
      "source": "type_Customer",
      "confidence": 0.9
    },
    {
      "identifier": "bo_line_item",
      "name": "Line Item",
      "documentation": "An individual entry on an invoice representing a product or service with quantity and price",
      "source": "type_Position",
      "confidence": 0.85
    }
  ]
}'
WHERE step_name = 'BusinessObject' AND is_active = TRUE;

-- BusinessProcess example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "bp_create_invoice",
      "name": "Create Invoice",
      "documentation": "Process of generating a new invoice with line items and customer details",
      "source": "method_invoice_form",
      "confidence": 0.9
    },
    {
      "identifier": "bp_process_payment",
      "name": "Process Payment",
      "documentation": "Handles payment submission and validation for customer orders",
      "source": "method_handle_payment",
      "confidence": 0.85
    }
  ]
}'
WHERE step_name = 'BusinessProcess' AND is_active = TRUE;

-- BusinessActor example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "ba_customer",
      "name": "Customer",
      "documentation": "External party who purchases products or services and receives invoices",
      "source": "type_Customer",
      "confidence": 0.95
    },
    {
      "identifier": "ba_administrator",
      "name": "Administrator",
      "documentation": "Internal user with elevated privileges for system management",
      "source": "type_Admin",
      "confidence": 0.9
    }
  ]
}'
WHERE step_name = 'BusinessActor' AND is_active = TRUE;

-- DataObject example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "do_application_database",
      "name": "Application Database",
      "documentation": "SQLite database storing invoices, customers, and line items",
      "source": "file_database.db",
      "confidence": 0.95
    },
    {
      "identifier": "do_app_configuration",
      "name": "Application Configuration",
      "documentation": "Environment configuration for Flask application settings",
      "source": "file_.flaskenv",
      "confidence": 0.85
    }
  ]
}'
WHERE step_name = 'DataObject' AND is_active = TRUE;

-- TechnologyService example
UPDATE derivation_config SET example = '{
  "elements": [
    {
      "identifier": "techsvc_postgresql",
      "name": "PostgreSQL Database",
      "documentation": "Relational database service for persistent data storage",
      "source": "dep_sqlalchemy",
      "confidence": 0.95
    },
    {
      "identifier": "techsvc_redis_cache",
      "name": "Redis Cache",
      "documentation": "In-memory data store used for caching and session management",
      "source": "dep_redis",
      "confidence": 0.9
    }
  ]
}'
WHERE step_name = 'TechnologyService' AND is_active = TRUE;

-- =============================================================================
-- DERIVATION PATTERNS DATA
-- =============================================================================

-- ApplicationService patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(1, 'ApplicationService', 'include', 'http_methods', '["get", "post", "put", "patch", "delete"]'),
(2, 'ApplicationService', 'include', 'routing', '["route", "endpoint", "api", "rest"]'),
(3, 'ApplicationService', 'include', 'handlers', '["view", "handler", "controller", "index", "list", "detail", "show"]'),
(4, 'ApplicationService', 'include', 'auth', '["login", "logout", "register", "authenticate"]'),
(5, 'ApplicationService', 'include', 'operations', '["search", "filter", "export", "download", "upload", "import"]'),
(6, 'ApplicationService', 'exclude', 'private', '["_", "private", "internal", "helper"]'),
(7, 'ApplicationService', 'exclude', 'lifecycle', '["__init__", "__del__", "setup", "teardown"]'),
(8, 'ApplicationService', 'exclude', 'utility', '["validate", "parse", "format", "convert", "serialize", "deserialize"]');

-- BusinessObject patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(10, 'BusinessObject', 'exclude', 'base_classes', '["base", "abstract", "mixin", "interface", "protocol"]'),
(11, 'BusinessObject', 'exclude', 'utility', '["helper", "utils", "util", "tools", "common"]'),
(12, 'BusinessObject', 'exclude', 'framework', '["handler", "middleware", "decorator", "wrapper", "factory", "builder", "adapter", "proxy"]'),
(13, 'BusinessObject', 'exclude', 'testing', '["test", "mock", "stub", "fake", "fixture"]'),
(14, 'BusinessObject', 'exclude', 'config', '["config", "settings", "options", "params"]'),
(15, 'BusinessObject', 'exclude', 'errors', '["error", "exception"]'),
(16, 'BusinessObject', 'include', 'people', '["user", "account", "customer", "client", "member"]'),
(17, 'BusinessObject', 'include', 'commerce', '["order", "invoice", "payment", "transaction", "receipt"]'),
(18, 'BusinessObject', 'include', 'inventory', '["product", "item", "catalog", "inventory", "stock"]'),
(19, 'BusinessObject', 'include', 'documents', '["document", "report", "contract", "agreement"]'),
(20, 'BusinessObject', 'include', 'communication', '["message", "notification", "email", "alert"]'),
(21, 'BusinessObject', 'include', 'workflow', '["project", "task", "workflow", "process"]'),
(22, 'BusinessObject', 'include', 'organization', '["employee", "department", "organization", "company"]'),
(23, 'BusinessObject', 'include', 'contact', '["address", "contact", "profile", "preference"]'),
(24, 'BusinessObject', 'include', 'subscription', '["subscription", "plan", "license", "quota"]'),
(25, 'BusinessObject', 'include', 'records', '["position", "entry", "record", "detail"]');

-- BusinessProcess patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(30, 'BusinessProcess', 'exclude', 'lifecycle', '["__init__", "__del__", "__enter__", "__exit__", "__str__", "__repr__", "__eq__", "__hash__"]'),
(31, 'BusinessProcess', 'exclude', 'utility', '["helper", "util", "validate", "parse", "format", "convert", "transform", "serialize", "deserialize"]'),
(32, 'BusinessProcess', 'exclude', 'accessors', '["get_", "set_", "is_", "has_", "_get", "_set"]'),
(33, 'BusinessProcess', 'exclude', 'framework', '["setup", "teardown", "configure", "initialize"]'),
(34, 'BusinessProcess', 'include', 'crud_create', '["create", "add", "insert", "new"]'),
(35, 'BusinessProcess', 'include', 'crud_update', '["update", "modify", "edit", "change"]'),
(36, 'BusinessProcess', 'include', 'crud_delete', '["delete", "remove", "cancel"]'),
(37, 'BusinessProcess', 'include', 'workflow', '["submit", "approve", "reject", "review"]'),
(38, 'BusinessProcess', 'include', 'actions', '["process", "handle", "execute", "run"]'),
(39, 'BusinessProcess', 'include', 'compute', '["generate", "calculate", "compute"]'),
(40, 'BusinessProcess', 'include', 'communication', '["send", "notify", "email", "alert"]'),
(41, 'BusinessProcess', 'include', 'data_transfer', '["export", "import", "sync"]'),
(42, 'BusinessProcess', 'include', 'auth', '["register", "login", "logout", "authenticate"]'),
(43, 'BusinessProcess', 'include', 'commerce', '["checkout", "payment", "order", "invoice", "ship", "deliver", "fulfill"]');

-- BusinessActor patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(50, 'BusinessActor', 'include', 'roles', '["user", "admin", "administrator", "manager", "operator"]'),
(51, 'BusinessActor', 'include', 'external', '["customer", "client", "buyer", "seller", "vendor"]'),
(52, 'BusinessActor', 'include', 'internal', '["employee", "staff", "worker", "agent", "representative"]'),
(53, 'BusinessActor', 'include', 'members', '["member", "subscriber", "owner", "author", "creator"]'),
(54, 'BusinessActor', 'include', 'organizational', '["department", "team", "group", "organization", "company", "partner", "supplier", "provider"]'),
(55, 'BusinessActor', 'include', 'system', '["system", "service", "bot", "scheduler", "daemon"]'),
(56, 'BusinessActor', 'include', 'auth', '["principal", "identity", "account", "role", "permission"]'),
(57, 'BusinessActor', 'exclude', 'data', '["data", "model", "entity", "record", "item", "entry", "request", "response", "message", "event", "log"]'),
(58, 'BusinessActor', 'exclude', 'technical', '["handler", "controller", "service", "repository", "factory", "helper", "util", "config", "settings", "option"]'),
(59, 'BusinessActor', 'exclude', 'errors', '["exception", "error", "validator", "parser"]'),
(60, 'BusinessActor', 'exclude', 'base_classes', '["base", "abstract", "interface", "mixin"]');

-- DataObject patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(70, 'DataObject', 'include', 'database', '["database", "db", "sqlite", "sql"]'),
(71, 'DataObject', 'include', 'config', '["config", "json", "yaml", "yml", "toml", "ini", "env"]'),
(72, 'DataObject', 'include', 'schema', '["schema", "xsd", "dtd"]'),
(73, 'DataObject', 'include', 'data', '["csv", "xml", "data"]'),
(74, 'DataObject', 'exclude', 'source', '["source", "python", "javascript", "typescript"]'),
(75, 'DataObject', 'exclude', 'templates', '["template", "html", "css"]'),
(76, 'DataObject', 'exclude', 'testing', '["test", "spec"]'),
(77, 'DataObject', 'exclude', 'docs', '["docs", "markdown", "readme"]'),
(78, 'DataObject', 'exclude', 'assets', '["asset", "image", "font"]');

-- TechnologyService patterns
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(80, 'TechnologyService', 'include', 'databases', '["sql", "postgres", "mysql", "sqlite", "mongo", "redis", "elastic", "database", "db", "orm", "sqlalchemy", "prisma", "duckdb"]'),
(81, 'TechnologyService', 'include', 'messaging', '["kafka", "rabbitmq", "celery", "amqp", "queue", "pubsub"]'),
(82, 'TechnologyService', 'include', 'http', '["http", "request", "api", "rest", "graphql", "grpc", "websocket", "flask", "fastapi", "django", "express", "axios", "fetch"]'),
(83, 'TechnologyService', 'include', 'cloud', '["aws", "azure", "gcp", "s3", "lambda", "dynamodb", "cloudwatch"]'),
(84, 'TechnologyService', 'include', 'auth', '["oauth", "jwt", "auth", "ldap", "saml"]'),
(85, 'TechnologyService', 'include', 'storage', '["storage", "blob", "file", "minio"]'),
(86, 'TechnologyService', 'include', 'infrastructure', '["docker", "kubernetes", "nginx", "vault", "consul"]'),
(87, 'TechnologyService', 'exclude', 'stdlib', '["os", "sys", "json", "re", "datetime", "time", "logging", "typing", "collections", "functools", "itertools", "pathlib", "io", "copy"]'),
(88, 'TechnologyService', 'exclude', 'stdlib_advanced', '["dataclasses", "enum", "abc", "contextlib", "warnings", "math"]'),
(89, 'TechnologyService', 'exclude', 'testing', '["pytest", "unittest", "mock", "typing_extensions", "pydantic"]'),
(90, 'TechnologyService', 'exclude', 'dev_tools', '["setuptools", "pip", "wheel", "black", "ruff", "mypy", "isort"]');
