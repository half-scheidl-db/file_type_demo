# Databricks notebook source
# DBTITLE 1,Pipeline Overview
# MAGIC %md
# MAGIC # Inspection Pipeline with Per-Document MLflow Tracing
# MAGIC
# MAGIC A three-layer medallion pipeline for manufacturing visual inspection.
# MAGIC Each document gets its own **MLflow trace** at the silver layer, linked by a
# MAGIC shared `pipeline_run_id` that flows bronze → silver → gold.
# MAGIC
# MAGIC | Layer | Table | Role | `pipeline_run_id` |
# MAGIC |-------|-------|------|-------------------|
# MAGIC | Bronze | `inspection_files` | File ingestion from UC Volume | Stamps which run ingested the file |
# MAGIC | Silver | `inspection_results` | AI inference + PASS/FAIL/REVIEW | Links each MLflow trace to the run |
# MAGIC | Gold | `inspection_reviews` | Human review queue (FAIL + REVIEW) | End-to-end lineage for reviewers |
# MAGIC
# MAGIC **MLflow trace tree** (per pipeline run):
# MAGIC ```
# MAGIC Experiment: /Users/<you>/inspection-pipeline
# MAGIC   ├─ trace: inspect-<id_1>  [tags: pipeline_run_id, status]
# MAGIC   │    ├─ span: openai.chat  (auto-logged: tokens, latency)
# MAGIC   │    └─ span: classify     (deterministic PASS/FAIL/REVIEW)
# MAGIC   ├─ trace: inspect-<id_2>
# MAGIC   └─ ...
# MAGIC ```

# COMMAND ----------

# DBTITLE 1,Install dependencies
# MAGIC %pip install --upgrade mlflow[databricks] openai
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Configuration & MLflow experiment
import mlflow
import uuid
import json
import base64
import os
from datetime import datetime, timezone
from pyspark.sql import functions as F
from pyspark.sql.types import *
from mlflow.entities import SpanType
from openai import OpenAI

# ── Notebook parameters (overridable via job widgets) ──────────────────
dbutils.widgets.text("catalog", "multimodal_demo")
dbutils.widgets.text("schema", "manufacturing")
dbutils.widgets.text("volume", "inspection_dropzone")
dbutils.widgets.text("model_endpoint", "system.ai.gpt-5-6-luna")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOLUME = dbutils.widgets.get("volume")
MODEL_ENDPOINT = dbutils.widgets.get("model_endpoint")

# ── Shared pipeline run ID (constant for this entire execution) ────────
PIPELINE_RUN_ID = str(uuid.uuid4())
PIPELINE_RUN_TS = datetime.now(timezone.utc)

# ── Table references ───────────────────────────────────────────────────
BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.inspection_files"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.inspection_results"
GOLD_TABLE = f"{CATALOG}.{SCHEMA}.inspection_reviews"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"

# ── MLflow experiment ──────────────────────────────────────────────────
current_user = spark.sql("SELECT current_user()").first()[0]
EXPERIMENT_PATH = f"/Users/{current_user}/inspection-pipeline"
mlflow.set_experiment(EXPERIMENT_PATH)
mlflow.openai.autolog()  # Auto-capture LLM spans (tokens, latency)

# ── OpenAI-compatible client for the model endpoint ────────────────────
db_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
workspace_url = spark.conf.get("spark.databricks.workspaceUrl")

oai_client = OpenAI(
    api_key=db_token,
    base_url=f"https://{workspace_url}/serving-endpoints",
)

print(f"Pipeline Run ID : {PIPELINE_RUN_ID}")
print(f"Timestamp       : {PIPELINE_RUN_TS.isoformat()}")
print(f"MLflow Experiment: {EXPERIMENT_PATH}")
print(f"Bronze          : {BRONZE_TABLE}")
print(f"Silver          : {SILVER_TABLE}")
print(f"Gold            : {GOLD_TABLE}")
print(f"Model           : {MODEL_ENDPOINT}")

# COMMAND ----------

# DBTITLE 1,Inspection prompt and response schema
INSPECTION_PROMPT = """You are inspecting a fictional pharmaceutical injection pen from an automated visual inspection station.

Inspect only what is visibly present in the image. Do not assume a component is present because injection pens normally have one.

Expected assembly and inspection criteria:
- The pen has a protective cap covering the needle end of the device.
- The protective cap is a distinct removable outer component and must be visibly present on a conforming unit.
- If the end that should be covered by the protective cap is visibly exposed, report the cap as MISSING.
- Do not interpret an exposed end, connector, housing section, or internal component as the protective cap.
- The label should be aligned with the long axis of the pen and fully attached. Judge alignment geometrically, not by whether the text is readable. Compare the label's long top and bottom edges, printed text baselines, and overall rectangular orientation against the pen body's longitudinal axis. A visibly rotated, skewed, or diagonal label is MISALIGNED even if it is fully attached and all text remains readable.
- The housing should be intact, with no visible cracks or structural damage.
- No visible foreign material or contamination should be present.

Perform each check independently:
1. Protective cap: PRESENT, MISSING, or UNKNOWN.
2. Label alignment: OK, MISALIGNED, or UNKNOWN. Return MISALIGNED when the label rectangle or its printed text is visibly rotated relative to the pen's long axis. Do not require severe displacement: a clear angular deviation is sufficient. Ignore perspective only when the entire pen and label share the same apparent angle; if the pen body is horizontal but the label edges/text slope relative to it, classify MISALIGNED.
3. Label attachment: OK, DETACHED, or UNKNOWN.
4. Housing condition: OK, DAMAGED, or UNKNOWN.
5. Contamination: NONE, PRESENT, or UNKNOWN.
6. Image obstruction: true only when a foreground object physically overlaps the pen and hides enough of a required inspection region that at least one of checks 1-5 cannot be completed visually. A tray, fixture, rail, background object, shadow, reflection, or object adjacent to the pen is NOT an obstruction if the relevant pen surfaces remain visible. If all checks 1-5 can be completed from the image, image_obstruction must be false.
7. Image quality: SUFFICIENT or INSUFFICIENT.

Use UNKNOWN only when the relevant feature cannot be inspected because it is actually hidden by an overlapping object or because image quality is insufficient. If image_obstruction is true, at least one of checks 1-5 must be UNKNOWN because of that obstruction. Do not mark image_obstruction true merely because inspection-station hardware is visible in the image. Do not convert uncertainty into an assumed normal condition.

Return only the requested structured result. The reason must be short and describe the visible evidence behind the observations."""

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "inspection_observations",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "cap_status": {"type": "string", "enum": ["PRESENT", "MISSING", "UNKNOWN"]},
                "label_alignment": {"type": "string", "enum": ["OK", "MISALIGNED", "UNKNOWN"]},
                "label_attachment": {"type": "string", "enum": ["OK", "DETACHED", "UNKNOWN"]},
                "housing_condition": {"type": "string", "enum": ["OK", "DAMAGED", "UNKNOWN"]},
                "contamination": {"type": "string", "enum": ["NONE", "PRESENT", "UNKNOWN"]},
                "image_obstruction": {"type": "boolean"},
                "image_quality": {"type": "string", "enum": ["SUFFICIENT", "INSUFFICIENT"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": [
                "cap_status", "label_alignment", "label_attachment",
                "housing_condition", "contamination", "image_obstruction",
                "image_quality", "confidence", "reason",
            ],
            "additionalProperties": False,
        },
    },
}

# COMMAND ----------

# DBTITLE 1,Helper functions: classify + traced inspect
def classify_result(r: dict) -> tuple:
    """Deterministic PASS / FAIL / REVIEW from model observations.

    Mirrors the SQL CASE logic from the original SDP pipeline.
    """
    if (
        r.get("image_obstruction")
        or r.get("image_quality") == "INSUFFICIENT"
        or r.get("cap_status") == "UNKNOWN"
        or r.get("label_alignment") == "UNKNOWN"
        or r.get("label_attachment") == "UNKNOWN"
        or r.get("housing_condition") == "UNKNOWN"
        or r.get("contamination") == "UNKNOWN"
    ):
        status = "REVIEW"
        if r.get("image_obstruction"):
            issue = "image obstruction"
        elif r.get("image_quality") == "INSUFFICIENT":
            issue = "insufficient image quality"
        else:
            issue = "incomplete inspection"
    elif (
        r.get("cap_status") == "MISSING"
        or r.get("label_alignment") == "MISALIGNED"
        or r.get("label_attachment") == "DETACHED"
        or r.get("housing_condition") == "DAMAGED"
        or r.get("contamination") == "PRESENT"
    ):
        status = "FAIL"
        if r.get("cap_status") == "MISSING":
            issue = "missing protective cap"
        elif r.get("label_alignment") == "MISALIGNED":
            issue = "crooked or misaligned label"
        elif r.get("label_attachment") == "DETACHED":
            issue = "partially detached label"
        elif r.get("housing_condition") == "DAMAGED":
            issue = "damaged housing"
        else:
            issue = "visible contamination"
    else:
        status = "PASS"
        issue = "none"
    return status, issue


@mlflow.trace(name="inspect_document", span_type=SpanType.CHAIN)
def inspect_document(inspection_id: str, file_uri: str) -> dict:
    """Run multimodal inspection on a single image with full MLflow tracing.

    Trace tree:
      inspect_document (CHAIN)
        ├─ load_image
        ├─ openai.chat.completions (auto-logged by mlflow.openai.autolog)
        └─ classify
    """
    # ── Load image ─────────────────────────────────────────────────────
    with mlflow.start_span(name="load_image") as span:
        with open(file_uri, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        ext = file_uri.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
        span.set_inputs({"file_uri": file_uri})
        span.set_outputs({"size_bytes": len(image_bytes), "mime": mime})

    # ── Call model endpoint (auto-traced by OpenAI autolog) ────────────
    response = oai_client.chat.completions.create(
        model=MODEL_ENDPOINT,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": INSPECTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }
        ],
        response_format=RESPONSE_FORMAT,
    )
    ai_json = response.choices[0].message.content
    observations = json.loads(ai_json)

    # ── Deterministic classification ───────────────────────────────────
    with mlflow.start_span(name="classify") as span:
        status, observed_issue = classify_result(observations)
        span.set_inputs(observations)
        span.set_outputs({"status": status, "observed_issue": observed_issue})

    # ── Tag the trace for filtering in the MLflow UI ───────────────────
    mlflow.update_current_trace(
        tags={
            "inspection_id": inspection_id,
            "pipeline_run_id": PIPELINE_RUN_ID,
            "status": status,
        }
    )

    return {**observations, "status": status, "observed_issue": observed_issue}

# COMMAND ----------

# DBTITLE 1,Bronze: Ingest files from UC Volume
# ── Create bronze table (preserves FILE EXTERNAL type) ─────────────────
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {BRONZE_TABLE} (
        inspection_id      STRING,
        file_name          STRING,
        ingested_at        TIMESTAMP,
        inspection_image   FILE EXTERNAL,
        file_uri           STRING,
        content_type       STRING,
        file_size          BIGINT,
        checksum           STRING,
        batch_id           STRING,
        production_line    STRING,
        equipment_id       STRING,
        inspection_ts      TIMESTAMP,
        pipeline_run_id    STRING
    )
    COMMENT 'Manufacturing inspection images with pipeline run lineage.'
""")

# ── Discover files in the volume and merge new records ─────────────────
# read_files (batch) finds all files; MERGE ensures idempotent inserts.
new_files = spark.sql(f"""
    SELECT
        sha2(coalesce(file.checksum, file.uri), 256)  AS inspection_id,
        regexp_extract(path, '[^/]+$', 0)             AS file_name,
        current_timestamp()                           AS ingested_at,
        file                                          AS inspection_image,
        file.uri                                      AS file_uri,
        file.content_type                             AS content_type,
        file.size                                     AS file_size,
        file.checksum                                 AS checksum,
        'DEMO-001'                                    AS batch_id,
        'Pen Assembly 03'                             AS production_line,
        'VISION-01'                                   AS equipment_id,
        modification_time                             AS inspection_ts,
        '{PIPELINE_RUN_ID}'                           AS pipeline_run_id
    FROM read_files('{VOLUME_PATH}/', format => 'file')
    WHERE lower(path) LIKE '%.png'
       OR lower(path) LIKE '%.jpg'
       OR lower(path) LIKE '%.jpeg'
""")

new_files.createOrReplaceTempView("_bronze_incoming")

spark.sql(f"""
    MERGE INTO {BRONZE_TABLE} AS target
    USING _bronze_incoming AS source
    ON target.inspection_id = source.inspection_id
    WHEN NOT MATCHED THEN INSERT *
""")

new_count = spark.table(BRONZE_TABLE).filter(F.col("pipeline_run_id") == PIPELINE_RUN_ID).count()
total_count = spark.table(BRONZE_TABLE).count()
print(f"Bronze: {new_count} new file(s) ingested | {total_count} total in table")

# COMMAND ----------

# DBTITLE 1,Silver: Per-document AI inspection with MLflow tracing
# ── Create silver table ────────────────────────────────────────────────
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {SILVER_TABLE} (
        inspection_id      STRING,
        file_name          STRING,
        ingested_at        TIMESTAMP,
        file_uri           STRING,
        content_type       STRING,
        file_size          BIGINT,
        checksum           STRING,
        batch_id           STRING,
        production_line    STRING,
        equipment_id       STRING,
        inspection_ts      TIMESTAMP,
        pipeline_run_id    STRING,
        cap_status         STRING,
        label_alignment    STRING,
        label_attachment   STRING,
        housing_condition  STRING,
        contamination      STRING,
        image_obstruction  BOOLEAN,
        image_quality      STRING,
        status             STRING,
        observed_issue     STRING,
        confidence         DOUBLE,
        reason             STRING,
        inspected_at       TIMESTAMP
    )
    COMMENT 'AI inspection results with per-document MLflow traces.'
""")

# ── Find unprocessed bronze records ────────────────────────────────────
unprocessed = spark.sql(f"""
    SELECT b.*
    FROM {BRONZE_TABLE} b
    LEFT ANTI JOIN {SILVER_TABLE} s ON b.inspection_id = s.inspection_id
""")

rows = unprocessed.collect()
print(f"Silver: {len(rows)} document(s) to process\n")

# ── Per-document inference loop ────────────────────────────────────────
# Each iteration produces one MLflow trace tagged with pipeline_run_id.
results = []
for i, row in enumerate(rows):
    print(f"  [{i + 1}/{len(rows)}] {row.file_name} ", end="")
    try:
        result = inspect_document(
            inspection_id=row.inspection_id,
            file_uri=row.file_uri,
        )
        results.append({
            "inspection_id":     row.inspection_id,
            "file_name":         row.file_name,
            "ingested_at":       row.ingested_at,
            "file_uri":          row.file_uri,
            "content_type":      row.content_type,
            "file_size":         row.file_size,
            "checksum":          row.checksum,
            "batch_id":          row.batch_id,
            "production_line":   row.production_line,
            "equipment_id":      row.equipment_id,
            "inspection_ts":     row.inspection_ts,
            "pipeline_run_id":   row.pipeline_run_id,
            "cap_status":        result["cap_status"],
            "label_alignment":   result["label_alignment"],
            "label_attachment":  result["label_attachment"],
            "housing_condition": result["housing_condition"],
            "contamination":     result["contamination"],
            "image_obstruction": result["image_obstruction"],
            "image_quality":     result["image_quality"],
            "status":            result["status"],
            "observed_issue":    result["observed_issue"],
            "confidence":        float(result["confidence"]),
            "reason":            result["reason"],
            "inspected_at":      datetime.now(timezone.utc),
        })
        print(f"\u2192 {result['status']}")
    except Exception as e:
        print(f"\u2192 ERROR: {e}")

# ── Write results to silver table ──────────────────────────────────────
if results:
    silver_schema = StructType([
        StructField("inspection_id", StringType()),
        StructField("file_name", StringType()),
        StructField("ingested_at", TimestampType()),
        StructField("file_uri", StringType()),
        StructField("content_type", StringType()),
        StructField("file_size", LongType()),
        StructField("checksum", StringType()),
        StructField("batch_id", StringType()),
        StructField("production_line", StringType()),
        StructField("equipment_id", StringType()),
        StructField("inspection_ts", TimestampType()),
        StructField("pipeline_run_id", StringType()),
        StructField("cap_status", StringType()),
        StructField("label_alignment", StringType()),
        StructField("label_attachment", StringType()),
        StructField("housing_condition", StringType()),
        StructField("contamination", StringType()),
        StructField("image_obstruction", BooleanType()),
        StructField("image_quality", StringType()),
        StructField("status", StringType()),
        StructField("observed_issue", StringType()),
        StructField("confidence", DoubleType()),
        StructField("reason", StringType()),
        StructField("inspected_at", TimestampType()),
    ])
    results_df = spark.createDataFrame(results, schema=silver_schema)
    results_df.write.mode("append").saveAsTable(SILVER_TABLE)
    print(f"\nSilver: {len(results)} result(s) written to {SILVER_TABLE}")
else:
    print("\nSilver: no new documents to process")

# COMMAND ----------

# DBTITLE 1,Gold: Populate review queue
# ── Create gold review table ───────────────────────────────────────────
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {GOLD_TABLE} (
        inspection_id      STRING,
        file_name          STRING,
        inspection_ts      TIMESTAMP,
        production_line    STRING,
        equipment_id       STRING,
        batch_id           STRING,
        status             STRING,
        observed_issue     STRING,
        cap_status         STRING,
        label_alignment    STRING,
        label_attachment   STRING,
        housing_condition  STRING,
        contamination      STRING,
        image_obstruction  BOOLEAN,
        image_quality      STRING,
        confidence         DOUBLE,
        reason             STRING,
        file_uri           STRING,
        pipeline_run_id    STRING,
        -- Review disposition columns (populated by human reviewers)
        reviewer           STRING,
        review_status      STRING,
        review_notes       STRING,
        reviewed_at        TIMESTAMP
    )
    COMMENT 'Inspection items requiring human review, with disposition tracking and pipeline lineage.'
""")

# ── Insert FAIL / REVIEW items not yet in gold ─────────────────────────
spark.sql(f"""
    INSERT INTO {GOLD_TABLE}
    (inspection_id, file_name, inspection_ts, production_line, equipment_id,
     batch_id, status, observed_issue, cap_status, label_alignment,
     label_attachment, housing_condition, contamination, image_obstruction,
     image_quality, confidence, reason, file_uri, pipeline_run_id)
    SELECT
        r.inspection_id, r.file_name, r.inspection_ts, r.production_line,
        r.equipment_id, r.batch_id, r.status, r.observed_issue,
        r.cap_status, r.label_alignment, r.label_attachment,
        r.housing_condition, r.contamination, r.image_obstruction,
        r.image_quality, r.confidence, r.reason, r.file_uri,
        r.pipeline_run_id
    FROM {SILVER_TABLE} r
    WHERE r.status IN ('FAIL', 'REVIEW')
      AND r.inspection_id NOT IN (SELECT inspection_id FROM {GOLD_TABLE})
""")

pending = spark.table(GOLD_TABLE).filter(F.col("reviewed_at").isNull()).count()
total_reviews = spark.table(GOLD_TABLE).count()
print(f"Gold: {pending} item(s) pending review | {total_reviews} total in review table")

# COMMAND ----------

# DBTITLE 1,Run summary
bronze_run = spark.table(BRONZE_TABLE).filter(F.col("pipeline_run_id") == PIPELINE_RUN_ID).count()
silver_run = spark.table(SILVER_TABLE).filter(F.col("pipeline_run_id") == PIPELINE_RUN_ID).count()

status_breakdown = (
    spark.table(SILVER_TABLE)
    .filter(F.col("pipeline_run_id") == PIPELINE_RUN_ID)
    .groupBy("status")
    .count()
    .orderBy("status")
    .collect()
)

print("\n" + "\u2550" * 55)
print("  Pipeline Run Summary")
print("  Run ID   : " + PIPELINE_RUN_ID)
print("  Timestamp: " + PIPELINE_RUN_TS.isoformat())
print("\u2550" * 55)
print(f"  Bronze files ingested  : {bronze_run}")
print(f"  Silver docs processed  : {silver_run}")
if status_breakdown:
    print("  Status breakdown:")
    for row in status_breakdown:
        print(f"    {row.status:10s} : {row['count']}")
print(f"  MLflow experiment      : {EXPERIMENT_PATH}")
print("\u2550" * 55)
print(f"\n  Filter traces in MLflow UI by tag:")
print(f"    pipeline_run_id = '{PIPELINE_RUN_ID}'")
