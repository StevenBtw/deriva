-- Chunking configuration for file types
-- Adds chunking strategy fields to file_type_registry

-- Add chunking configuration columns to file_type_registry
-- chunk_delimiter: Custom delimiter for splitting (e.g., '\n\nclass ', '\ndef ')
-- chunk_max_tokens: Override default max tokens for this extension
-- chunk_overlap: Number of lines/sections to overlap between chunks

ALTER TABLE file_type_registry ADD COLUMN chunk_delimiter VARCHAR;
ALTER TABLE file_type_registry ADD COLUMN chunk_max_tokens INTEGER;
ALTER TABLE file_type_registry ADD COLUMN chunk_overlap INTEGER DEFAULT 0;

-- Set sensible defaults for common code file types
-- Python: split on class/function definitions
UPDATE file_type_registry SET chunk_delimiter = '
class ', chunk_overlap = 0 WHERE extension = '.py';

-- JavaScript/TypeScript: split on function/class definitions
UPDATE file_type_registry SET chunk_delimiter = '
function ', chunk_overlap = 0 WHERE extension IN ('.js', '.ts', '.jsx', '.tsx');

-- Markdown: split on headings
UPDATE file_type_registry SET chunk_delimiter = '
## ', chunk_overlap = 0 WHERE extension IN ('.md', '.markdown');

-- SQL: split on statement boundaries
UPDATE file_type_registry SET chunk_delimiter = ';
', chunk_overlap = 0 WHERE extension = '.sql';

-- JSON/YAML: no special delimiter, use line-based
UPDATE file_type_registry SET chunk_delimiter = NULL, chunk_overlap = 0 WHERE extension IN ('.json', '.yaml', '.yml');
