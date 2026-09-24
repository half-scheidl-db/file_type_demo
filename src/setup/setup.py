# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Setup Overview
# MAGIC %md
# MAGIC # Setup Notebook
# MAGIC
# MAGIC This notebook combines catalog/schema/volume creation and sample image upload
# MAGIC into a single setup flow.
# MAGIC
# MAGIC 1. **SQL cell** — creates the Unity Catalog catalog, schema, and volume (idempotent).
# MAGIC 2. **Python cell** — uploads sample inspection images to the volume.
# MAGIC
# MAGIC Defaults mirror `databricks.yml`. Override via environment variables or by editing
# MAGIC the variables below.

# COMMAND ----------

# DBTITLE 1,Create catalog, schema, and volume
# MAGIC %sql
# MAGIC -- Idempotent setup: create the catalog, schema, and volume.
# MAGIC -- These defaults mirror databricks.yml. If you run this with non-default
# MAGIC -- bundle values, change only the three variables below.
# MAGIC
# MAGIC DECLARE OR REPLACE VARIABLE demo_catalog STRING DEFAULT 'multimodal_demo';
# MAGIC DECLARE OR REPLACE VARIABLE demo_schema  STRING DEFAULT 'manufacturing';
# MAGIC DECLARE OR REPLACE VARIABLE demo_volume  STRING DEFAULT 'inspection_dropzone';
# MAGIC
# MAGIC CREATE CATALOG IF NOT EXISTS IDENTIFIER(demo_catalog);
# MAGIC
# MAGIC CREATE SCHEMA IF NOT EXISTS IDENTIFIER(demo_catalog || '.' || demo_schema);
# MAGIC
# MAGIC CREATE VOLUME IF NOT EXISTS IDENTIFIER(demo_catalog || '.' || demo_schema || '.' || demo_volume)
# MAGIC COMMENT 'External-system drop zone for synthetic manufacturing inspection images';

# COMMAND ----------

# DBTITLE 1,Upload sample images to the UC Volume
import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults – mirror databricks.yml / setup.sql
# Override via environment variables or function arguments.
# ---------------------------------------------------------------------------
DEFAULT_CATALOG = os.getenv("DEMO_CATALOG", "multimodal_demo")
DEFAULT_SCHEMA = os.getenv("DEMO_SCHEMA", "manufacturing")
DEFAULT_VOLUME = os.getenv("DEMO_VOLUME", "inspection_dropzone")

# Resolve the project root from the current Databricks user's workspace path.
_current_user = spark.sql("SELECT current_user()").first()[0]
_PROJECT_ROOT = f"/Workspace/Users/{_current_user}/file_type_demo"

# Base path for sample inspection images (contains wave1/, wave2/, …).
_SAMPLE_IMAGES_ROOT = f"{_PROJECT_ROOT}/sample-data/inspection-images"

# When set, uploads only this single directory; otherwise uploads all wave*/ dirs.
SOURCE_DIR = os.getenv("SOURCE_DIR", "")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def _volume_path(catalog: str, schema: str, volume: str) -> str:
    """Return the FUSE mount path for a UC Volume."""
    return f"/Volumes/{catalog}/{schema}/{volume}"


def _find_images(source_dir: str) -> list[str]:
    """Return a sorted list of image file paths in *source_dir* (non-recursive)."""
    source = Path(source_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"Image directory does not exist: {source_dir}")
    images = sorted(
        str(p)
        for p in source.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    return images


def upload_images(
    source_dir: str,
    *,
    catalog: str = DEFAULT_CATALOG,
    schema: str = DEFAULT_SCHEMA,
    volume: str = DEFAULT_VOLUME,
    overwrite: bool = True,
) -> int:
    """Copy image files from *source_dir* into the target UC Volume.

    Parameters
    ----------
    source_dir : str
        Path to a directory containing .png / .jpg / .jpeg files.
        Typically a /Workspace/… or /Volumes/… path.
    catalog, schema, volume : str
        Unity Catalog coordinates for the destination volume.
    overwrite : bool
        If True (default), overwrite existing files with the same name.

    Returns
    -------
    int
        Number of images uploaded.
    """
    dest = _volume_path(catalog, schema, volume)
    if not os.path.isdir(dest):
        raise FileNotFoundError(
            f"Destination volume path does not exist: {dest}. "
            "Run the SQL cell above first to create the catalog/schema/volume."
        )

    images = _find_images(source_dir)
    if not images:
        print(f"No image files ({', '.join(IMAGE_EXTENSIONS)}) found in {source_dir}")
        return 0

    print(f"Uploading {len(images)} image(s) to {dest}/")
    for img_path in images:
        filename = os.path.basename(img_path)
        target = os.path.join(dest, filename)
        if not overwrite and os.path.exists(target):
            print(f"  -- skipping {filename} (already exists)")
            continue
        shutil.copy2(img_path, target)
        print(f"  -> {filename}")

    print("Done. No files were deleted from the drop zone.")
    return len(images)


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------
if SOURCE_DIR:
    # Explicit directory provided — upload that single directory.
    upload_images(SOURCE_DIR)
else:
    # Upload every wave*/ subdirectory in order (wave1, wave2, …).
    waves = sorted(
        d for d in Path(_SAMPLE_IMAGES_ROOT).iterdir()
        if d.is_dir() and d.name.startswith("wave")
    )
    if not waves:
        print(f"No wave*/ directories found under {_SAMPLE_IMAGES_ROOT}")
    for wave_dir in waves:
        print(f"\n=== {wave_dir.name} ===")
        upload_images(str(wave_dir))
