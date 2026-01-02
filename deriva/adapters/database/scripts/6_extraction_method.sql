-- Extraction method configuration
-- Adds extraction_method field to extraction_config to specify LLM vs AST extraction

-- Add extraction_method column
-- Values: 'llm' (default), 'ast', 'structural'
ALTER TABLE extraction_config ADD COLUMN extraction_method VARCHAR DEFAULT 'llm';

-- Set defaults based on node type
-- Structural types don't use LLM
UPDATE extraction_config SET extraction_method = 'structural' WHERE node_type IN ('Repository', 'Directory', 'File');

-- LLM-based extraction (default for semantic types)
UPDATE extraction_config SET extraction_method = 'llm' WHERE node_type IN ('BusinessConcept', 'Technology', 'Test');

-- Types that can use either LLM or AST - default to LLM, user can override
UPDATE extraction_config SET extraction_method = 'llm' WHERE node_type IN ('TypeDefinition', 'Method', 'ExternalDependency');
