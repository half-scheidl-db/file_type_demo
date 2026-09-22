"""Tear down all resources created by the file-type-demo bundle.

Databricks cleanup script — reverses setup.sql and the bundle deployment.
Idempotent: missing resources are silently skipped.

Run directly as a Databricks workspace file or job task.
"""

import os
import shutil
from pathlib import Path

from pyspark.sql import SparkSession
from databricks.sdk import WorkspaceClient

# ---------------------------------------------------------------------------
# Defaults – mirror databricks.yml / setup.sql
# ---------------------------------------------------------------------------
CATALOG = os.getenv("DEMO_CATALOG", "multimodal_demo")
SCHEMA = os.getenv("DEMO_SCHEMA", "manufacturing")
VOLUME = os.getenv("DEMO_VOLUME", "inspection_dropzone")
JOB_NAME = "refresh-file-type-inspections"
PIPELINE_NAME = "file-type-visual-inspection"

spark = SparkSession.getActiveSession()
w = WorkspaceClient()



# ---------------------------------------------------------------------------
# 1. Jobs
# ---------------------------------------------------------------------------
print("=== Jobs ===")
for job in w.jobs.list(name=JOB_NAME):
    print(f"  {job.settings.name} (id={job.job_id})")
    w.jobs.delete(job.job_id)
print("  Done.")

# ---------------------------------------------------------------------------
# 2. Pipelines
# ---------------------------------------------------------------------------
print("\n=== Pipelines ===")
for p in w.pipelines.list_pipelines(filter=f"name LIKE '{PIPELINE_NAME}'"):
    print(f"  {p.name} (id={p.pipeline_id})")
    w.pipelines.delete(p.pipeline_id)
print("  Done.")

# ---------------------------------------------------------------------------
# 3. Empty the volume
# ---------------------------------------------------------------------------
print(f"\n=== Volume contents: {CATALOG}.{SCHEMA}.{VOLUME} ===")
volume_path = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
if os.path.isdir(volume_path):
    count = 0
    for entry in Path(volume_path).iterdir():
        if entry.is_file():
            entry.unlink()
            count += 1
        elif entry.is_dir():
            shutil.rmtree(entry)
            count += 1
    print(f"  Cleared {count} item(s).")
else:
    print(f"  Volume path not found, skipping: {volume_path}")

# ---------------------------------------------------------------------------
# 4. Drop streaming tables
# ---------------------------------------------------------------------------
print(f"\n=== Streaming tables in {CATALOG}.{SCHEMA} ===")
for tbl in ("inspection_results", "inspection_files"):
    fqn = f"{CATALOG}.{SCHEMA}.{tbl}"
    print(f"  DROP TABLE IF EXISTS {fqn}")
    spark.sql(f"DROP TABLE IF EXISTS {fqn}")
print("  Done.")

# ---------------------------------------------------------------------------
# 5. Drop volume
# ---------------------------------------------------------------------------
print("\n=== Volume ===")
fqn_vol = f"{CATALOG}.{SCHEMA}.{VOLUME}"
print(f"  DROP VOLUME IF EXISTS {fqn_vol}")
spark.sql(f"DROP VOLUME IF EXISTS {fqn_vol}")
print("  Done.")

# ---------------------------------------------------------------------------
# 6. Drop schema
# ---------------------------------------------------------------------------
print("\n=== Schema ===")
fqn_sch = f"{CATALOG}.{SCHEMA}"
print(f"  DROP SCHEMA IF EXISTS {fqn_sch} CASCADE")
spark.sql(f"DROP SCHEMA IF EXISTS {fqn_sch} CASCADE")
print("  Done.")

# ---------------------------------------------------------------------------
# 7. Drop catalog
# ---------------------------------------------------------------------------
print("\n=== Catalog ===")
print(f"  DROP CATALOG IF EXISTS {CATALOG} CASCADE")
spark.sql(f"DROP CATALOG IF EXISTS {CATALOG} CASCADE")
print("  Done.")

print("\nCleanup complete.")


