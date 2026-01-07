-- Migration: Add patterns for 6 new ArchiMate element derivation modules and enable them
-- ApplicationInterface, BusinessEvent, BusinessFunction, Device, Node, SystemSoftware

-- ============================================================================
-- Enable the new element types
-- ============================================================================
UPDATE derivation_config SET enabled = true WHERE step_name = 'ApplicationInterface' AND phase = 'generate';
UPDATE derivation_config SET enabled = true WHERE step_name = 'BusinessEvent' AND phase = 'generate';
UPDATE derivation_config SET enabled = true WHERE step_name = 'BusinessFunction' AND phase = 'generate';
UPDATE derivation_config SET enabled = true WHERE step_name = 'Device' AND phase = 'generate';
UPDATE derivation_config SET enabled = true WHERE step_name = 'Node' AND phase = 'generate';
UPDATE derivation_config SET enabled = true WHERE step_name = 'SystemSoftware' AND phase = 'generate';

-- ============================================================================
-- ApplicationInterface patterns - API endpoints and exposed interfaces
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(91, 'ApplicationInterface', 'include', 'api', '["api", "endpoint", "route", "handler", "controller", "rest", "graphql", "grpc", "webhook", "websocket"]'),
(92, 'ApplicationInterface', 'exclude', 'internal', '["_", "private", "internal"]'),
(93, 'ApplicationInterface', 'exclude', 'utility', '["helper", "util"]');

-- ============================================================================
-- BusinessEvent patterns - Business state changes and triggers
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(94, 'BusinessEvent', 'include', 'handler', '["on_", "handle", "emit", "trigger", "dispatch"]'),
(95, 'BusinessEvent', 'include', 'event', '["event", "signal", "message", "notification"]'),
(96, 'BusinessEvent', 'include', 'lifecycle', '["created", "updated", "deleted", "changed"]'),
(97, 'BusinessEvent', 'exclude', 'technical', '["click", "mouse", "key", "scroll"]');

-- ============================================================================
-- BusinessFunction patterns - Business capabilities and organizational functions
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(98, 'BusinessFunction', 'include', 'domain', '["service", "domain", "business", "core"]'),
(99, 'BusinessFunction', 'include', 'capability', '["payment", "order", "inventory", "shipping", "billing", "auth"]'),
(100, 'BusinessFunction', 'exclude', 'infrastructure', '["util", "helper", "common", "shared", "lib"]');

-- ============================================================================
-- Device patterns - Physical hardware and deployment targets
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(101, 'Device', 'include', 'hardware', '["server", "host", "machine", "hardware", "physical"]'),
(102, 'Device', 'include', 'infra', '["terraform", "cloudformation", "ansible", "infrastructure"]'),
(103, 'Device', 'include', 'storage', '["storage", "disk"]'),
(104, 'Device', 'exclude', 'software', '[".py", ".js", ".ts", "test"]');

-- ============================================================================
-- Node patterns - Computational resources and containers
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(105, 'Node', 'include', 'container', '["docker", "container", "pod"]'),
(106, 'Node', 'include', 'k8s', '["kubernetes", "deployment", "k8s", "helm"]'),
(107, 'Node', 'include', 'cloud', '["ec2", "instance", "vm", "lambda", "function"]'),
(108, 'Node', 'exclude', 'config', '[".env", "config."]'),
(109, 'Node', 'exclude', 'test', '["test"]');

-- ============================================================================
-- SystemSoftware patterns - OS, runtimes, and platform services
-- ============================================================================
INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns) VALUES
(110, 'SystemSoftware', 'include', 'runtime', '["python", "node", "java", "jvm", "runtime"]'),
(111, 'SystemSoftware', 'include', 'database', '["postgres", "mysql", "mongo", "redis"]'),
(112, 'SystemSoftware', 'include', 'messaging', '["kafka", "rabbitmq", "celery"]'),
(113, 'SystemSoftware', 'include', 'webserver', '["nginx", "apache"]'),
(114, 'SystemSoftware', 'include', 'container', '["docker"]'),
(115, 'SystemSoftware', 'exclude', 'library', '["utils", "helper", "typing"]');
