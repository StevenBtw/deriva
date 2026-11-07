-- The other JavaScript and TypeScript extensions are source files (new in 0.9.0): .jsx, .mjs and .cjs are JavaScript,
-- .tsx, .mts and .cts TypeScript (.tsx with JSX in it). A database that already lists one keeps its own row.
-- A marker setting per extension makes this run once: a row deleted later stays deleted.
-- A fresh database runs this before its seed, and the seed fills only empty tables: so the inserts wait for seeded tables.
-- Statements are split at semicolons, so comments here hold none.
INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.cjs', 'source', 'javascript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.cjs')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_cjs_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_cjs_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_cjs_added');

INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.jsx', 'source', 'javascript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.jsx')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_jsx_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_jsx_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_jsx_added');

INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.mjs', 'source', 'javascript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.mjs')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_mjs_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_mjs_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_mjs_added');

INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.cts', 'source', 'typescript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.cts')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_cts_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_cts_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_cts_added');

INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.mts', 'source', 'typescript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.mts')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_mts_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_mts_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_mts_added');

INSERT INTO file_type_registry (extension, file_type, subtype, chunk_delimiter, chunk_overlap)
SELECT '.tsx', 'source', 'typescript', chr(10) || 'function ', 0
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM file_type_registry WHERE extension = '.tsx')
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_tsx_added');

INSERT INTO system_settings (key, value)
SELECT 'file_type_tsx_added', 'true'
WHERE EXISTS (SELECT 1 FROM file_type_registry)
AND EXISTS (SELECT 1 FROM system_settings)
AND NOT EXISTS (SELECT 1 FROM system_settings WHERE key = 'file_type_tsx_added');
