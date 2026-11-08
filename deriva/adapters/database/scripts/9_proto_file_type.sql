-- The .proto extension is an interface schema (Protocol Buffers, new in 0.9.0). A database that already lists it keeps its own row.
-- A marker setting makes this run once: a .proto row deleted later stays deleted.
-- A fresh database runs this before its seed, and the seed fills only empty tables: so both inserts wait for seeded tables.
-- Statements are split at semicolons, so comments here hold none.
INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.proto', 'schema', 'proto', NULL, 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.proto')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_proto_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_proto_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_proto_added');
