-- LLM configuration columns for per-step temperature and max_tokens overrides
-- NULL values = use environment defaults (LLM_TEMPERATURE, LLM_MAX_TOKENS)

-- Add temperature and max_tokens to extraction_config
ALTER TABLE extraction_config ADD COLUMN temperature FLOAT;
ALTER TABLE extraction_config ADD COLUMN max_tokens INTEGER;

-- Add temperature and max_tokens to derivation_config
ALTER TABLE derivation_config ADD COLUMN temperature FLOAT;
ALTER TABLE derivation_config ADD COLUMN max_tokens INTEGER;
