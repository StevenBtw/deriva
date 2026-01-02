-- Extraction Config Versions (Initial Seed)
-- Auto-generated from extraction_config.json

-- Sequence order: 1=Repository, 2=Directory, 3=File, 4=BusinessConcept, 5=Technology, 6=ExternalDependency, 7=TypeDefinition, 8=Method, 9=Test

-- input_sources format:
-- {
--   "files": [{"type": "source", "subtype": "*"}],  -- type/subtype with * wildcard
--   "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]  -- graph node label and property
-- }

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (1, 'Repository', 1, 1, TRUE, '{"files": [], "nodes": []}', 'Extract repository metadata including name, URL, branch, and commit hash from the repository root.', '{"repoName": "my-repo", "url": "https://github.com/user/my-repo", "branch": "main", "commit": "abc123", "confidence": 1.0}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (2, 'Directory', 1, 2, TRUE, '{"files": [], "nodes": [{"label": "Repository", "property": null}]}', 'Extract directory structure from the repository. Create a node for each directory in the hierarchy.', '{"name": "src", "path": "my-repo/src", "confidence": 1.0}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (3, 'File', 1, 3, TRUE, '{"files": [{"type": "source", "subtype": "*"}, {"type": "config", "subtype": "*"}, {"type": "docs", "subtype": "*"}, {"type": "test", "subtype": "*"}, {"type": "build", "subtype": "*"}, {"type": "data", "subtype": "*"}, {"type": "dependency", "subtype": "*"}], "nodes": [{"label": "Directory", "property": null}]}', 'Extract individual files from directories, classify by type using the file type registry, and calculate basic metrics.', '{"fileName": "auth.py", "filePath": "src/auth/auth.py", "fileType": "source", "subtype": "python", "size": 2048, "confidence": 1.0}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (4, 'BusinessConcept', 1, 4, FALSE, '{"files": [{"type": "docs", "subtype": "*"}], "nodes": []}', 'Extract ONLY high-level business domain concepts from the documentation. Focus on the "what" of the business, NOT the "how" of implementation.

INCLUDE (Business Domain):
- Business Entities: domain objects like Invoice, Customer, Order, Product, Payment
- Business Actors: roles like Client, Vendor, Supplier (NOT generic User/Admin)
- Business Processes: workflows like Billing, Fulfillment, Approval
- Business Events: occurrences like Order Placed, Payment Received
- Business Rules: policies with business meaning

EXCLUDE (Technical/Implementation):
- Frameworks, libraries, tools (any technology names)
- Programming languages and technical operations
- CRUD operations, API endpoints, database queries
- Infrastructure, servers, deployments
- Generic actors like User, System, Admin

LIMIT: Maximum 5-7 concepts per file
CONFIDENCE: Only include concepts with confidence >= 0.7', '{"conceptName": "Invoice", "conceptType": "entity", "description": "Document representing a billing transaction with line items and payment terms", "originSource": "docs/readme.md", "confidence": 0.9}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (5, 'Technology', 1, 5, TRUE, '{"files": [{"type": "dependency", "subtype": "*"}, {"type": "config", "subtype": "*"}, {"type": "build", "subtype": "*"}], "nodes": []}', 'Extract HIGH-LEVEL technology infrastructure components that will map to ArchiMate Technology Layer elements.

Focus ONLY on:
- Technology Services: Authentication services, API gateways, message queues, caching services
- System Software: Databases (PostgreSQL, MySQL, MongoDB), web servers (Nginx, Apache), caches (Redis, Memcached)
- Infrastructure/Platform: Cloud platforms (AWS, Azure, GCP), container platforms (Docker, Kubernetes), serverless
- Network: API protocols, communication patterns (REST, GraphQL, gRPC, WebSocket)
- Security/IAM: Authentication mechanisms (OAuth2, JWT, SAML), identity providers

DO NOT include:
- Low-level libraries or utility packages (these go in ExternalDependency)
- Programming language standard libraries
- Development tools or testing frameworks

For each technology, determine:
- techName: Name of the technology
- techCategory: One of [service, system_software, infrastructure, platform, network, security]
- description: Brief description of its role in the system architecture
- version: Version if specified (or null)
- confidence: Your confidence in this extraction (0.0 to 1.0)

Look for clues in:
- Database connection strings or ORM configurations
- Docker/container configurations
- Cloud service references
- Authentication/authorization setup
- API gateway or proxy configurations', '{"techName": "PostgreSQL", "techCategory": "system_software", "description": "Primary relational database for application data", "version": "15", "confidence": 0.95}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (6, 'ExternalDependency', 1, 6, TRUE, '{"files": [{"type": "dependency", "subtype": "*"}, {"type": "config", "subtype": "*"}, {"type": "source", "subtype": "*"}], "nodes": []}', 'Extract external dependencies including libraries, external APIs, and external service integrations.

Categories to extract:
1. LIBRARIES: Package dependencies from manifest files
   - Runtime libraries (flask, react, express)
   - Utility libraries (lodash, requests, axios)

2. EXTERNAL APIS: Third-party API integrations found in code/config
   - Payment APIs (Stripe, PayPal, Square)
   - Communication APIs (SendGrid, Twilio, Mailchimp)
   - Cloud service APIs (AWS S3, Google Cloud Storage)

3. EXTERNAL SERVICES: External systems the application connects to
   - External databases (MongoDB Atlas, AWS RDS)
   - External storage (S3, Azure Blob)
   - Third-party SaaS integrations

For each dependency, identify:
- dependencyName: Name of the dependency/API/service
- dependencyCategory: One of [library, external_api, external_service, external_database]
- version: Version constraint if applicable (or null)
- ecosystem: Package ecosystem for libraries (pypi, npm, maven) or provider for APIs/services
- description: What this dependency is used for
- confidence: Your confidence in this extraction (0.0 to 1.0)

Look for clues in:
- Dependency manifest files (requirements.txt, package.json, pyproject.toml)
- Import statements referencing external packages
- API client initializations and URL patterns
- Environment variable references to external services', '{"dependencyName": "stripe", "dependencyCategory": "external_api", "version": "5.0.0", "ecosystem": "pypi", "description": "Payment processing API client", "confidence": 0.95}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (7, 'TypeDefinition', 1, 7, FALSE, '{"files": [{"type": "source", "subtype": "*"}], "nodes": []}', 'Extract type definitions (classes, interfaces, structs, enums, functions) from source files.

For each type definition, identify:
- typeName: The name of the type (class name, function name, etc.)
- category: One of [class, interface, struct, enum, function, alias, module, other]
- description: A brief description of the type''s purpose based on its name, docstrings, and context
- interfaceType: If this type exposes an API, specify one of [REST API, GraphQL, gRPC, WebSocket, CLI, Internal API], otherwise use "none"
- startLine: Line number where the type definition starts (use line numbers shown in file)
- endLine: Line number where the type definition ends (include the full body)
- confidence: Your confidence in this extraction (0.0 to 1.0)

IMPORTANT: Use the exact line numbers shown in the file content.', '{"typeName": "UserRepository", "category": "class", "description": "Data access layer for User entities", "interfaceType": "Internal API", "startLine": 15, "endLine": 45, "confidence": 0.9}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (8, 'Method', 1, 8, FALSE, '{"files": [], "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]}', 'Extract methods and functions from the type definition code snippet.

For each method, identify:
- methodName: The name of the method or function
- returnType: Return type (use "None" for Python methods without explicit return, "void" for other languages)
- visibility: Access level - "public", "private", or "protected"
  - Python: no prefix = public, _prefix = private, __prefix = protected
  - Other languages: use explicit keywords (public, private, protected)
- parameters: Parameter signature as a string (e.g., "self, name: str, age: int")
- description: Brief description of what the method does based on name and context
- isStatic: true if static method (@staticmethod in Python, static keyword in others)
- isAsync: true if async method (async def in Python, async keyword in others)
- startLine: Line number where the method starts (relative to the snippet shown)
- endLine: Line number where the method ends
- confidence: Your confidence in this extraction (0.0 to 1.0)

Include special methods like __init__, __str__, __repr__, etc.
Skip module-level imports and constants.

IMPORTANT: Use the exact line numbers shown in the code snippet.', '{"methodName": "authenticate", "returnType": "bool", "visibility": "public", "parameters": "self, username: str, password: str", "description": "Authenticates a user with credentials", "isStatic": false, "isAsync": false, "startLine": 5, "endLine": 12, "confidence": 0.9}', TRUE);

INSERT INTO extraction_config
    (id, node_type, version, sequence, enabled, input_sources, instruction, example, is_active)
VALUES
    (9, 'Test', 1, 9, FALSE, '{"files": [{"type": "test", "subtype": "*"}], "nodes": []}', 'Extract test definitions from test files.

For each test, identify:
- testName: Name of the test function/method
- testType: One of [unit, integration, e2e, performance, smoke, regression, other]
- description: Brief description of what the test verifies
- testedElement: What is being tested (class name, function name, feature name)
- framework: Test framework used (e.g., "pytest", "unittest", "jest", "mocha")
- startLine: Line number where the test starts
- endLine: Line number where the test ends
- confidence: Your confidence in this extraction (0.0 to 1.0)

Identify the test type based on:
- File location (e.g., tests/unit/, tests/integration/)
- Test name patterns (test_unit_*, test_integration_*)
- Test content and what it''s testing (mocking = unit, real services = integration)

IMPORTANT: Use the exact line numbers shown in the file content.', '{"testName": "test_user_authentication", "testType": "unit", "description": "Tests user login with valid credentials", "testedElement": "UserService.authenticate", "framework": "pytest", "startLine": 10, "endLine": 25, "confidence": 0.9}', TRUE);
