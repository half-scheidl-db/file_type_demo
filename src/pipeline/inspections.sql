-- Bronze: every newly arrived file becomes a native FILE EXTERNAL value.
CREATE OR REFRESH STREAMING TABLE inspection_files (
  inspection_id STRING,
  file_name STRING,
  ingested_at TIMESTAMP,
  inspection_image FILE EXTERNAL,
  file_uri STRING,
  content_type STRING,
  file_size BIGINT,
  checksum STRING,
  batch_id STRING,
  production_line STRING,
  equipment_id STRING,
  inspection_ts TIMESTAMP
)
COMMENT 'Incrementally discovered manufacturing inspection images stored as native FILE references.'
AS
SELECT
  sha2(coalesce(file.checksum, file.uri), 256) AS inspection_id,
  regexp_extract(path, '[^/]+$', 0) AS file_name,
  current_timestamp() AS ingested_at,
  file AS inspection_image,
  file.uri AS file_uri,
  file.content_type AS content_type,
  file.size AS file_size,
  file.checksum AS checksum,
  'DEMO-001' AS batch_id,
  'Pen Assembly 03' AS production_line,
  'VISION-01' AS equipment_id,
  modification_time AS inspection_ts
FROM STREAM read_files(
  '/Volumes/${demo.catalog}/${demo.schema}/${demo.volume}/',
  format => 'file'
)
WHERE lower(path) LIKE '%.png'
   OR lower(path) LIKE '%.jpg'
   OR lower(path) LIKE '%.jpeg';

-- Silver/result table: only new Bronze rows stream through multimodal inference
-- during a normal pipeline update. A full refresh intentionally reprocesses all rows.
CREATE OR REFRESH STREAMING TABLE inspection_results (
  inspection_id STRING,
  file_name STRING,
  ingested_at TIMESTAMP,
  inspection_image FILE EXTERNAL,
  file_uri STRING,
  content_type STRING,
  file_size BIGINT,
  checksum STRING,
  batch_id STRING,
  production_line STRING,
  equipment_id STRING,
  inspection_ts TIMESTAMP,
  status STRING,
  observed_issue STRING,
  confidence DOUBLE,
  reason STRING
)
COMMENT 'Native image evidence, manufacturing context, and structured multimodal inspection result.'
AS
WITH inpection_images_contents AS (
  SELECT *, CAST(inspection_image AS BINARY) as content FROM STREAM inspection_files
),
scored AS (
  SELECT
    *,
    ai_query(
      '${demo.model_endpoint}',
      'You are inspecting a fictional pharmaceutical injection pen from an automated visual inspection station.\nClassify the image as exactly one of: PASS, FAIL, REVIEW.\nCheck only for:\n- missing protective cap\n- crooked or misaligned label\n- damaged housing\n- partially detached label\n- visible contamination\n- image obstruction\n- insufficient image quality\nReturn structured JSON with status, observed_issue, confidence, and reason.\nRules:\n- PASS means no visible defect.\n- FAIL means a visible manufacturing defect is present.\n- REVIEW means the image is insufficient to confidently inspect.\n- Do not infer defects that are not visibly present.',
      responseFormat => '{"type":"json_schema","json_schema":{"name":"inspection_result","strict":true,"schema":{"type":"object","properties":{"status":{"type":"string","enum":["PASS","FAIL","REVIEW"]},"observed_issue":{"type":"string"},"confidence":{"type":"number","minimum":0,"maximum":1},"reason":{"type":"string"}},"required":["status","observed_issue","confidence","reason"],"additionalProperties":false}}}',
      files => content
    ) AS ai_json
  FROM  inpection_images_contents
), parsed AS (
  SELECT
    *,
    from_json(
      ai_json,
      'status STRING, observed_issue STRING, confidence DOUBLE, reason STRING'
    ) AS result
  FROM scored
)
SELECT
  inspection_id,
  file_name,
  ingested_at,
  inspection_image,
  file_uri,
  content_type,
  file_size,
  checksum,
  batch_id,
  production_line,
  equipment_id,
  inspection_ts,
  result.status AS status,
  result.observed_issue AS observed_issue,
  result.confidence AS confidence,
  result.reason AS reason
FROM parsed;
