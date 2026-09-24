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
--
-- The model reports concrete visual observations. PASS / FAIL / REVIEW and
-- observed_issue are derived deterministically below instead of asking the model
-- to make both the visual observation and the quality disposition.
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
  cap_status STRING,
  label_alignment STRING,
  label_attachment STRING,
  housing_condition STRING,
  contamination STRING,
  image_obstruction BOOLEAN,
  image_quality STRING,
  status STRING,
  observed_issue STRING,
  confidence DOUBLE,
  reason STRING
)
COMMENT 'Native image evidence, manufacturing context, structured visual observations, and deterministic inspection result.'
AS
WITH inpection_images_contents AS (
  SELECT *, CAST(inspection_image AS BINARY) as content FROM STREAM inspection_files
),
scored AS (
  SELECT
    *,
    ai_query(
      '${demo.model_endpoint}',
      'You are inspecting a fictional pharmaceutical injection pen from an automated visual inspection station.\n\nInspect only what is visibly present in the image. Do not assume a component is present because injection pens normally have one.\n\nExpected assembly and inspection criteria:\n- The pen has a protective cap covering the needle end of the device.\n- The protective cap is a distinct removable outer component and must be visibly present on a conforming unit.\n- If the end that should be covered by the protective cap is visibly exposed, report the cap as MISSING.\n- Do not interpret an exposed end, connector, housing section, or internal component as the protective cap.\n- The label should be aligned with the long axis of the pen and fully attached. Judge alignment geometrically, not by whether the text is readable. Compare the label's long top and bottom edges, printed text baselines, and overall rectangular orientation against the pen body's longitudinal axis. A visibly rotated, skewed, or diagonal label is MISALIGNED even if it is fully attached and all text remains readable.\n- The housing should be intact, with no visible cracks or structural damage.\n- No visible foreign material or contamination should be present.\n\nPerform each check independently:\n1. Protective cap: PRESENT, MISSING, or UNKNOWN.\n2. Label alignment: OK, MISALIGNED, or UNKNOWN. Return MISALIGNED when the label rectangle or its printed text is visibly rotated relative to the pen's long axis. Do not require severe displacement: a clear angular deviation is sufficient. Ignore perspective only when the entire pen and label share the same apparent angle; if the pen body is horizontal but the label edges/text slope relative to it, classify MISALIGNED.\n3. Label attachment: OK, DETACHED, or UNKNOWN.\n4. Housing condition: OK, DAMAGED, or UNKNOWN.\n5. Contamination: NONE, PRESENT, or UNKNOWN.\n6. Image obstruction: true only when a foreground object physically overlaps the pen and hides enough of a required inspection region that at least one of checks 1-5 cannot be completed visually. A tray, fixture, rail, background object, shadow, reflection, or object adjacent to the pen is NOT an obstruction if the relevant pen surfaces remain visible. If all checks 1-5 can be completed from the image, image_obstruction must be false.\n7. Image quality: SUFFICIENT or INSUFFICIENT.\n\nUse UNKNOWN only when the relevant feature cannot be inspected because it is actually hidden by an overlapping object or because image quality is insufficient. If image_obstruction is true, at least one of checks 1-5 must be UNKNOWN because of that obstruction. Do not mark image_obstruction true merely because inspection-station hardware is visible in the image. Do not convert uncertainty into an assumed normal condition.\n\nReturn only the requested structured result. The reason must be short and describe the visible evidence behind the observations.',
      responseFormat => '{"type":"json_schema","json_schema":{"name":"inspection_observations","strict":true,"schema":{"type":"object","properties":{"cap_status":{"type":"string","enum":["PRESENT","MISSING","UNKNOWN"]},"label_alignment":{"type":"string","enum":["OK","MISALIGNED","UNKNOWN"]},"label_attachment":{"type":"string","enum":["OK","DETACHED","UNKNOWN"]},"housing_condition":{"type":"string","enum":["OK","DAMAGED","UNKNOWN"]},"contamination":{"type":"string","enum":["NONE","PRESENT","UNKNOWN"]},"image_obstruction":{"type":"boolean"},"image_quality":{"type":"string","enum":["SUFFICIENT","INSUFFICIENT"]},"confidence":{"type":"number","minimum":0,"maximum":1},"reason":{"type":"string"}},"required":["cap_status","label_alignment","label_attachment","housing_condition","contamination","image_obstruction","image_quality","confidence","reason"],"additionalProperties":false}}}',
      files => content
    ) AS ai_json
  FROM  inpection_images_contents
),
parsed AS (
  SELECT
    *,
    from_json(
      ai_json,
      'cap_status STRING, label_alignment STRING, label_attachment STRING, housing_condition STRING, contamination STRING, image_obstruction BOOLEAN, image_quality STRING, confidence DOUBLE, reason STRING'
    ) AS result
  FROM scored
),
classified AS (
  SELECT
    *,
    CASE
      WHEN result.image_obstruction
        OR result.image_quality = 'INSUFFICIENT'
        OR result.cap_status = 'UNKNOWN'
        OR result.label_alignment = 'UNKNOWN'
        OR result.label_attachment = 'UNKNOWN'
        OR result.housing_condition = 'UNKNOWN'
        OR result.contamination = 'UNKNOWN'
      THEN 'REVIEW'
      WHEN result.cap_status = 'MISSING'
        OR result.label_alignment = 'MISALIGNED'
        OR result.label_attachment = 'DETACHED'
        OR result.housing_condition = 'DAMAGED'
        OR result.contamination = 'PRESENT'
      THEN 'FAIL'
      ELSE 'PASS'
    END AS derived_status,
    CASE
      WHEN result.image_obstruction THEN 'image obstruction'
      WHEN result.image_quality = 'INSUFFICIENT' THEN 'insufficient image quality'
      WHEN result.cap_status = 'UNKNOWN'
        OR result.label_alignment = 'UNKNOWN'
        OR result.label_attachment = 'UNKNOWN'
        OR result.housing_condition = 'UNKNOWN'
        OR result.contamination = 'UNKNOWN'
      THEN 'incomplete inspection'
      WHEN result.cap_status = 'MISSING' THEN 'missing protective cap'
      WHEN result.label_alignment = 'MISALIGNED' THEN 'crooked or misaligned label'
      WHEN result.label_attachment = 'DETACHED' THEN 'partially detached label'
      WHEN result.housing_condition = 'DAMAGED' THEN 'damaged housing'
      WHEN result.contamination = 'PRESENT' THEN 'visible contamination'
      ELSE 'none'
    END AS derived_observed_issue
  FROM parsed
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
  result.cap_status AS cap_status,
  result.label_alignment AS label_alignment,
  result.label_attachment AS label_attachment,
  result.housing_condition AS housing_condition,
  result.contamination AS contamination,
  result.image_obstruction AS image_obstruction,
  result.image_quality AS image_quality,
  derived_status AS status,
  derived_observed_issue AS observed_issue,
  result.confidence AS confidence,
  result.reason AS reason
FROM classified;
