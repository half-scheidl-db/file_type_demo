-- Idempotent, standalone setup helper.
-- These defaults mirror databricks.yml. If you run this file manually with
-- non-default bundle values, change only the three variables below.
-- The bundle itself declares the same catalog/schema/volume as resources and
-- is the authoritative deployment path.

DECLARE OR REPLACE VARIABLE demo_catalog STRING DEFAULT 'multimodal_demo';
DECLARE OR REPLACE VARIABLE demo_schema  STRING DEFAULT 'manufacturing';
DECLARE OR REPLACE VARIABLE demo_volume  STRING DEFAULT 'inspection_dropzone';

CREATE CATALOG IF NOT EXISTS IDENTIFIER(demo_catalog);

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(demo_catalog || '.' || demo_schema);

CREATE VOLUME IF NOT EXISTS IDENTIFIER(demo_catalog || '.' || demo_schema || '.' || demo_volume)
COMMENT 'External-system drop zone for synthetic manufacturing inspection images';
