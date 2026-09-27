-- Versioned JSON parameters for extraction steps (e.g. prompt texts), as derivation_config has
ALTER TABLE extraction_config ADD COLUMN params TEXT;
