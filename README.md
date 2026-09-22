# Pharmaceutical visual inspection with Databricks FILE

This repository contains a small Databricks demo for ingesting pharmaceutical manufacturing inspection images as native `FILE` values, enriching them with manufacturing metadata, analyzing them with multimodal AI, and displaying the results in a Databricks App.

The flow is:

```text
Inspection images
      ↓
Unity Catalog Volume
      ↓
Lakeflow Declarative Pipeline
      ↓
inspection_image FILE EXTERNAL
      ↓
ai_query multimodal inspection
      ↓
Next.js Databricks App
```

The example uses synthetic images of a fictional injection pen. No real medicine or company branding is used.

## Repository structure

```text
.
├── databricks.yml
├── resources/
│   ├── app.yml
│   ├── jobs.yml
│   └── pipeline.yml
├── src/
│   ├── pipeline/
│   │   └── inspections.sql
│   └── setup/
│       └── setup.sql
├── app/
│   ├── app.yaml
│   ├── package.json
│   ├── server.mjs
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── api/image/[inspectionId]/route.ts
│   ├── components/
│   │   └── inspection-grid.tsx
│   └── lib/
│       ├── databricks.ts
│       └── types.ts
├── sample-data/
│   └── inspection-images/
│       ├── wave1/
│       │   ├── 01_pass_normal_a.png
│       │   ├── 02_pass_normal_b.png
│       │   └── 03_pass_normal_c.png
│       └── wave2/
│           ├── 04_fail_missing_cap.png
│           ├── 05_fail_crooked_label.png
│           ├── 06_fail_damaged_housing.png
│           ├── 07_fail_peeling_label.png
│           ├── 08_fail_contamination.png
│           ├── 09_review_obscured.png
│           └── 10_review_blurred.png
├── utils/
│   └── upload-images.sh
└── README.md
```

## Prerequisites

You need:

- a Databricks workspace with Unity Catalog
- serverless Lakeflow Declarative Pipelines
- Databricks Apps
- a SQL warehouse
- a recent Databricks CLI
- FILE type enabled in the workspace
- a multimodal model endpoint supported by `ai_query`

The pipeline runs on the `PREVIEW` channel because FILE ingestion is currently a preview feature.

The pipeline identity needs access to the target catalog/schema/volume and permission to query the configured model endpoint. App users need `SELECT` on `inspection_results`, `READ VOLUME` on the inspection volume, and `CAN USE` on the SQL warehouse.

## Configuration

The bundle exposes these variables:

| Variable | Default |
|---|---|
| `catalog` | `multimodal_demo` |
| `schema` | `manufacturing` |
| `volume` | `inspection_dropzone` |
| `warehouse_id` | no default |
| `model_endpoint` | `system.ai.llama-4-maverick` |

At minimum, set the warehouse ID:

```bash
export BUNDLE_VAR_warehouse_id="<warehouse-id>"
```

Optional overrides:

```bash
export BUNDLE_VAR_catalog="multimodal_demo"
export BUNDLE_VAR_schema="manufacturing"
export BUNDLE_VAR_volume="inspection_dropzone"
export BUNDLE_VAR_model_endpoint="system.ai.llama-4-maverick"
```

## Deploy

Validate and deploy the bundle:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

The bundle creates or manages the catalog, schema, volume, Lakeflow pipeline, refresh job, and Databricks App.

The inspection drop zone is:

```text
/Volumes/<catalog>/<schema>/<volume>/
```

`src/setup/setup.sql` contains equivalent idempotent DDL for the catalog, schema, and volume. It is mainly useful for inspection or manual setup; the bundle is the normal deployment path.

The sample images are not uploaded during deployment.

## Upload inspection images

`utils/upload-images.sh` simulates an external inspection system writing image files into the Unity Catalog Volume.

Upload the first three images:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave1
```

With an explicit CLI profile:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave1 --profile DEFAULT
```

Upload the remaining images later:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave2
```

The destination can also be overridden:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave1 \
  --catalog multimodal_demo \
  --schema manufacturing \
  --volume inspection_dropzone
```

The script processes only `.png`, `.jpg`, and `.jpeg` files. It preserves filenames and does not delete anything from the volume.

## Ingestion

The Bronze streaming table is defined in `src/pipeline/inspections.sql` and reads the volume with:

```sql
FROM STREAM read_files(
  '/Volumes/<catalog>/<schema>/<volume>/',
  format => 'file'
)
```

Each file becomes a row with:

- `inspection_id`
- `file_name`
- `ingested_at`
- `inspection_image FILE EXTERNAL`
- FILE metadata such as URI, content type, size, and checksum
- synthetic manufacturing metadata such as batch, line, equipment, and inspection timestamp

`FILE EXTERNAL` is used because the source images already live in a Unity Catalog Volume. The table keeps a governed reference to the file instead of copying the image into the table.

Run a normal pipeline update with:

```bash
databricks bundle run refresh_inspections -t dev
```

Because the source uses streaming `read_files`, files already processed by a successful pipeline update are not rediscovered on the next normal update.

## Multimodal inspection

The downstream `inspection_results` streaming table reads new rows from `inspection_files` and sends the inspection image to `ai_query`.

The prompt classifies each image as:

- `PASS`
- `FAIL`
- `REVIEW`

It checks for:

- missing protective cap
- crooked or misaligned label
- damaged housing
- partially detached label
- visible contamination
- image obstruction
- insufficient image quality

The result is parsed into typed columns:

- `status`
- `observed_issue`
- `confidence`
- `reason`

The image remains available in the same result row as `inspection_image FILE EXTERNAL`.

Example query:

```sql
SELECT
  inspection_id,
  file_name,
  inspection_image,
  batch_id,
  production_line,
  equipment_id,
  status,
  observed_issue,
  confidence,
  reason
FROM inspection_results
ORDER BY ingested_at DESC;
```

## Databricks App

The Next.js app under `app/` queries `inspection_results` through the Databricks SQL Statement Execution API.

The main page shows the inspection image, status, filename, batch, production line, observed issue, and confidence. Opening a record shows the AI reason, equipment metadata, FILE URI, content type, size, and checksum.

Images are retrieved through a server-side Next.js route. The route looks up the corresponding FILE row and streams the image through the Databricks Files API. Databricks credentials are not sent to the browser.

The App requests these user API scopes:

```text
sql:restricted-query
files
```

## Local development

Bun can be used locally:

```bash
cd app
bun install
bun dev
```

For local access to Databricks:

```bash
export DATABRICKS_HOST="https://<workspace-host>"
export DATABRICKS_TOKEN="<local-dev-token>"
export DATABRICKS_WAREHOUSE_ID="<warehouse-id>"
export DEMO_CATALOG="multimodal_demo"
export DEMO_SCHEMA="manufacturing"
```

Do not commit local tokens or `.env` files.

The deployed app runs on Node.js and starts with:

```bash
npm run start
```

`server.mjs` binds to `0.0.0.0` and uses `process.env.PORT`.

## Demo sequence

Start with the three PASS images:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave1
databricks bundle run refresh_inspections -t dev
```

The app should show three inspection records.

Then upload the remaining images without clearing the tables or resetting pipeline state:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave2
databricks bundle run refresh_inspections -t dev
```

Refresh the app. The original three rows remain and the new rows appear after ingestion and AI processing.

For a short demo, show:

1. the Unity Catalog Volume before and after each upload
2. `inspection_files` with `inspection_image FILE EXTERNAL`
3. `inspection_results` with the FILE and AI result columns
4. the Next.js app showing the same records and source images

## Notes

- FILE ingestion is currently a preview feature, so the pipeline uses `channel: PREVIEW`.
- `inspection_id` is derived deterministically from FILE metadata. If a checksum is unavailable, the pipeline falls back to hashing the URI.
- FILE metadata is read without loading image bytes.
- Multimodal inference requires the image content, so the FILE is cast to binary when passed to `ai_query`.
- The synthetic image classifications are for demonstration only and are not a validated GMP inspection system.
- The app serves image content through Databricks rather than exposing cloud-storage credentials.
- A normal pipeline update processes newly arrived files. A full refresh intentionally reprocesses the dataset.

## Validation

Before presenting the demo:

```bash
databricks bundle validate -t dev
```

Build the app:

```bash
cd app
npm install
npm run build
```

Then test the two ingestion waves:

```bash
./utils/upload-images.sh ./sample-data/inspection-images/wave1
databricks bundle run refresh_inspections -t dev

./utils/upload-images.sh ./sample-data/inspection-images/wave2
databricks bundle run refresh_inspections -t dev
```

The second update should keep the original Wave 1 rows and process only the newly added files.
