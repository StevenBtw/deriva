-- Migration: Add 6 new ArchiMate element derivation modules
-- ApplicationInterface, BusinessEvent, BusinessFunction, Device, Node, SystemSoftware

-- ============================================================================
-- ApplicationInterface - API endpoints and exposed interfaces
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'ApplicationInterface', 'generate', 'ApplicationInterface', 35, true,
    'MATCH (n:Method) WHERE n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 500',
    'Analyze these code methods and identify which represent APPLICATION INTERFACES - points of access where application services are made available to users, other applications, or systems. Focus on:
- REST API endpoints and route handlers
- GraphQL resolvers and mutations
- gRPC service methods
- Public SDK/library interfaces
- Webhook handlers
- WebSocket handlers

For each interface found, generate an ArchiMate ApplicationInterface element with a meaningful business-oriented name and documentation.',
    '{"elements": [{"name": "User Registration API", "documentation": "REST API endpoint for user registration, handling account creation and initial profile setup.", "source_id": "method_register_user"}]}',
    50, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('ApplicationInterface', 'include', 'api', 'api'),
    ('ApplicationInterface', 'include', 'api', 'endpoint'),
    ('ApplicationInterface', 'include', 'api', 'route'),
    ('ApplicationInterface', 'include', 'api', 'handler'),
    ('ApplicationInterface', 'include', 'api', 'controller'),
    ('ApplicationInterface', 'include', 'api', 'rest'),
    ('ApplicationInterface', 'include', 'api', 'graphql'),
    ('ApplicationInterface', 'include', 'api', 'grpc'),
    ('ApplicationInterface', 'include', 'api', 'webhook'),
    ('ApplicationInterface', 'include', 'api', 'websocket'),
    ('ApplicationInterface', 'exclude', 'internal', '_'),
    ('ApplicationInterface', 'exclude', 'internal', 'private'),
    ('ApplicationInterface', 'exclude', 'internal', 'internal'),
    ('ApplicationInterface', 'exclude', 'utility', 'helper'),
    ('ApplicationInterface', 'exclude', 'utility', 'util');

-- ============================================================================
-- BusinessEvent - Business state changes and triggers
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'BusinessEvent', 'generate', 'BusinessEvent', 15, true,
    'MATCH (n) WHERE (n:Method OR n:TypeDefinition) AND n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 500',
    'Analyze these code elements and identify which represent BUSINESS EVENTS - organizational state changes that trigger business processes or responses. Focus on:
- Event handlers (on*, handle*, emit*, trigger*)
- Domain events and messages
- Notification triggers
- State change events
- Lifecycle events (created, updated, deleted)
- Integration events

For each event found, generate an ArchiMate BusinessEvent element with a meaningful business-oriented name and documentation describing the trigger and impact.',
    '{"elements": [{"name": "Order Placed", "documentation": "Business event triggered when a customer completes an order, initiating fulfillment and notification processes.", "source_id": "method_on_order_placed"}]}',
    40, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('BusinessEvent', 'include', 'handler', 'on_'),
    ('BusinessEvent', 'include', 'handler', 'handle'),
    ('BusinessEvent', 'include', 'handler', 'emit'),
    ('BusinessEvent', 'include', 'handler', 'trigger'),
    ('BusinessEvent', 'include', 'handler', 'dispatch'),
    ('BusinessEvent', 'include', 'event', 'event'),
    ('BusinessEvent', 'include', 'event', 'signal'),
    ('BusinessEvent', 'include', 'event', 'message'),
    ('BusinessEvent', 'include', 'event', 'notification'),
    ('BusinessEvent', 'include', 'lifecycle', 'created'),
    ('BusinessEvent', 'include', 'lifecycle', 'updated'),
    ('BusinessEvent', 'include', 'lifecycle', 'deleted'),
    ('BusinessEvent', 'include', 'lifecycle', 'changed'),
    ('BusinessEvent', 'exclude', 'technical', 'click'),
    ('BusinessEvent', 'exclude', 'technical', 'mouse'),
    ('BusinessEvent', 'exclude', 'technical', 'key'),
    ('BusinessEvent', 'exclude', 'technical', 'scroll');

-- ============================================================================
-- BusinessFunction - Business capabilities and organizational functions
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'BusinessFunction', 'generate', 'BusinessFunction', 12, true,
    'MATCH (n:Module) WHERE n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 300',
    'Analyze these code modules and identify which represent BUSINESS FUNCTIONS - collections of business behavior based on business capabilities. Focus on:
- Domain-specific modules (payments, orders, inventory)
- Service layers implementing business logic
- Business capability groupings
- Organizational unit modules
- Core business domains

For each function found, generate an ArchiMate BusinessFunction element with a meaningful business-oriented name and documentation describing the business capability.',
    '{"elements": [{"name": "Payment Processing", "documentation": "Business function responsible for handling all payment-related activities including authorization, capture, and refunds.", "source_id": "module_payments"}]}',
    30, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('BusinessFunction', 'include', 'domain', 'service'),
    ('BusinessFunction', 'include', 'domain', 'domain'),
    ('BusinessFunction', 'include', 'domain', 'business'),
    ('BusinessFunction', 'include', 'domain', 'core'),
    ('BusinessFunction', 'include', 'capability', 'payment'),
    ('BusinessFunction', 'include', 'capability', 'order'),
    ('BusinessFunction', 'include', 'capability', 'inventory'),
    ('BusinessFunction', 'include', 'capability', 'shipping'),
    ('BusinessFunction', 'include', 'capability', 'billing'),
    ('BusinessFunction', 'include', 'capability', 'auth'),
    ('BusinessFunction', 'exclude', 'infrastructure', 'util'),
    ('BusinessFunction', 'exclude', 'infrastructure', 'helper'),
    ('BusinessFunction', 'exclude', 'infrastructure', 'common'),
    ('BusinessFunction', 'exclude', 'infrastructure', 'shared'),
    ('BusinessFunction', 'exclude', 'infrastructure', 'lib');

-- ============================================================================
-- Device - Physical hardware and deployment targets
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'Device', 'generate', 'Device', 75, true,
    'MATCH (n:File) WHERE n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 300',
    'Analyze these configuration files and identify which reference DEVICES - physical IT resources upon which system software and artifacts may be deployed. Focus on:
- Hardware specifications in infrastructure-as-code
- Physical server definitions
- IoT device configurations
- Network appliance configs
- Storage device definitions
- Container host definitions

For each device found, generate an ArchiMate Device element with a meaningful name and documentation describing the hardware purpose.',
    '{"elements": [{"name": "Production Database Server", "documentation": "Physical server hosting the production PostgreSQL database cluster with high-availability configuration.", "source_id": "file_db_server_tf"}]}',
    25, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('Device', 'include', 'hardware', 'server'),
    ('Device', 'include', 'hardware', 'host'),
    ('Device', 'include', 'hardware', 'machine'),
    ('Device', 'include', 'hardware', 'hardware'),
    ('Device', 'include', 'hardware', 'physical'),
    ('Device', 'include', 'infra', 'terraform'),
    ('Device', 'include', 'infra', 'cloudformation'),
    ('Device', 'include', 'infra', 'ansible'),
    ('Device', 'include', 'infra', 'infrastructure'),
    ('Device', 'include', 'storage', 'storage'),
    ('Device', 'include', 'storage', 'disk'),
    ('Device', 'exclude', 'software', '.py'),
    ('Device', 'exclude', 'software', '.js'),
    ('Device', 'exclude', 'software', '.ts'),
    ('Device', 'exclude', 'software', 'test');

-- ============================================================================
-- Node - Computational resources and containers
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'Node', 'generate', 'Node', 70, true,
    'MATCH (n:File) WHERE n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 300',
    'Analyze these configuration files and identify which represent NODES - computational or physical resources that host and run software. Focus on:
- Kubernetes deployments and pods
- Docker Compose services
- Cloud VM/instance definitions (EC2, Compute Engine)
- Container definitions
- Serverless function configurations
- Cluster node definitions

For each node found, generate an ArchiMate Node element with a meaningful name and documentation describing its computational role.',
    '{"elements": [{"name": "API Gateway Node", "documentation": "Kubernetes deployment running the API gateway service, handling request routing and authentication.", "source_id": "file_api_gateway_yaml"}]}',
    30, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('Node', 'include', 'container', 'docker'),
    ('Node', 'include', 'container', 'container'),
    ('Node', 'include', 'container', 'pod'),
    ('Node', 'include', 'k8s', 'kubernetes'),
    ('Node', 'include', 'k8s', 'deployment'),
    ('Node', 'include', 'k8s', 'k8s'),
    ('Node', 'include', 'k8s', 'helm'),
    ('Node', 'include', 'cloud', 'ec2'),
    ('Node', 'include', 'cloud', 'instance'),
    ('Node', 'include', 'cloud', 'vm'),
    ('Node', 'include', 'cloud', 'lambda'),
    ('Node', 'include', 'cloud', 'function'),
    ('Node', 'exclude', 'config', '.env'),
    ('Node', 'exclude', 'config', 'config.'),
    ('Node', 'exclude', 'test', 'test');

-- ============================================================================
-- SystemSoftware - OS, runtimes, and platform services
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    input_graph_query, instruction, example, max_candidates, batch_size
) VALUES (
    'SystemSoftware', 'generate', 'SystemSoftware', 65, true,
    'MATCH (n:ExternalDependency) WHERE n.name IS NOT NULL RETURN n.id AS id, n.name AS name, labels(n) AS labels LIMIT 300',
    'Analyze these external dependencies and identify which represent SYSTEM SOFTWARE - software that provides an environment for running applications. Focus on:
- Operating systems and distributions
- Runtime environments (JVM, Node.js runtime, Python interpreter)
- Container runtimes (Docker, containerd)
- Database systems (PostgreSQL, MySQL, MongoDB)
- Message brokers (RabbitMQ, Kafka)
- Web servers (Nginx, Apache)
- Middleware and platform services

For each system software found, generate an ArchiMate SystemSoftware element with a meaningful name and documentation.',
    '{"elements": [{"name": "PostgreSQL Database", "documentation": "Relational database management system providing persistent data storage for application data.", "source_id": "dep_postgresql"}]}',
    35, 10
);

INSERT INTO derivation_patterns (step_name, pattern_type, pattern_category, pattern) VALUES
    ('SystemSoftware', 'include', 'runtime', 'python'),
    ('SystemSoftware', 'include', 'runtime', 'node'),
    ('SystemSoftware', 'include', 'runtime', 'java'),
    ('SystemSoftware', 'include', 'runtime', 'jvm'),
    ('SystemSoftware', 'include', 'runtime', 'runtime'),
    ('SystemSoftware', 'include', 'database', 'postgres'),
    ('SystemSoftware', 'include', 'database', 'mysql'),
    ('SystemSoftware', 'include', 'database', 'mongo'),
    ('SystemSoftware', 'include', 'database', 'redis'),
    ('SystemSoftware', 'include', 'messaging', 'kafka'),
    ('SystemSoftware', 'include', 'messaging', 'rabbitmq'),
    ('SystemSoftware', 'include', 'messaging', 'celery'),
    ('SystemSoftware', 'include', 'webserver', 'nginx'),
    ('SystemSoftware', 'include', 'webserver', 'apache'),
    ('SystemSoftware', 'include', 'container', 'docker'),
    ('SystemSoftware', 'exclude', 'library', 'utils'),
    ('SystemSoftware', 'exclude', 'library', 'helper'),
    ('SystemSoftware', 'exclude', 'library', 'typing');

-- ============================================================================
-- Relationship configs for new element types
-- ============================================================================
INSERT INTO derivation_config (
    step_name, phase, element_type, priority, enabled,
    instruction, example
) VALUES
    ('ApplicationInterface_relationships', 'relationship', 'ApplicationInterface', 135, true,
     'Derive relationships FROM ApplicationInterface elements. Valid relationships include: Serving (to actors/components that use this interface), Assignment (from components that implement this interface), Composition (to parent services).',
     '{"relationships": [{"source": "interface_user_api", "target": "service_user_mgmt", "relationship_type": "Serving", "confidence": 0.9}]}'),
    ('BusinessEvent_relationships', 'relationship', 'BusinessEvent', 115, true,
     'Derive relationships FROM BusinessEvent elements. Valid relationships include: Triggering (to processes started by this event), Association (to related business objects).',
     '{"relationships": [{"source": "event_order_placed", "target": "process_fulfill_order", "relationship_type": "Triggering", "confidence": 0.9}]}'),
    ('BusinessFunction_relationships', 'relationship', 'BusinessFunction', 112, true,
     'Derive relationships FROM BusinessFunction elements. Valid relationships include: Composition (to sub-functions), Realization (from processes that implement the function), Serving (to actors using this function).',
     '{"relationships": [{"source": "function_payments", "target": "function_refunds", "relationship_type": "Composition", "confidence": 0.85}]}'),
    ('Device_relationships', 'relationship', 'Device', 175, true,
     'Derive relationships FROM Device elements. Valid relationships include: Assignment (to nodes deployed on this device), Composition (to sub-devices), Serving (to software running on this device).',
     '{"relationships": [{"source": "device_db_server", "target": "node_postgres_cluster", "relationship_type": "Assignment", "confidence": 0.9}]}'),
    ('Node_relationships', 'relationship', 'Node', 170, true,
     'Derive relationships FROM Node elements. Valid relationships include: Assignment (to system software running on this node), Serving (to applications using this node), Realization (from devices hosting this node).',
     '{"relationships": [{"source": "node_api_gateway", "target": "sw_nginx", "relationship_type": "Assignment", "confidence": 0.9}]}'),
    ('SystemSoftware_relationships', 'relationship', 'SystemSoftware', 165, true,
     'Derive relationships FROM SystemSoftware elements. Valid relationships include: Serving (to applications using this software), Composition (to sub-components), Realization (from nodes running this software).',
     '{"relationships": [{"source": "sw_postgres", "target": "component_user_repo", "relationship_type": "Serving", "confidence": 0.85}]}');
