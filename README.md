# Databricks FILE type — pharmaceutical visual inspection demo

A deliberately small end-to-end demo for one customer message:

> **The image isn’t an attachment to the data anymore. It is data.**

```text
External inspection system
        ↓
Unity Catalog Volume drop zone
        ↓
STREAM read_files(..., format => 'file')
        ↓
inspection_image FILE EXTERNAL + manufacturing metadata
        ↓
multimodal ai_query
        ↓
Next.js Databricks App
```

## What this demonstrates

- **Native:** `inspection_image FILE EXTERNAL`, not `image_path STRING`.
- **Incremental:** a normal Lakeflow pipeline update discovers only newly arrived files.
- **Multimodal:** the governed `FILE` is read natively by Databricks and supplied to `ai_query`; there is no application-side download/base64 step for inference.
- **Unified:** manufacturing context, original image evidence, FILE metadata, and AI interpretation are queryable together.
- **Governed:** the Volume, Delta tables, pipeline, SQL access, and App stay inside Databricks / Unity Catalog governance.

## Directory tree

```text
.
├── .gitignore
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
├── utils/
│   └── upload-images.sh
└── README.md
```

## Prerequisites

1. Databricks workspace with Unity Catalog, serverless Lakeflow pipelines, Databricks Apps, and a serverless/pro SQL warehouse.
2. Current Databricks CLI. This project targets CLI **1.17.0+** and explicitly uses the **direct** deployment engine.
3. Workspace admin enables the **FILE type Beta** from the Previews page. FILE ingestion in a pipeline requires the `PREVIEW` channel.
4. A multimodal model endpoint supported by `ai_query`. The default is `system.ai.llama-4-maverick`; override it if that endpoint is unavailable in your workspace.
5. The pipeline owner/run-as identity needs `CAN QUERY` on the selected model endpoint plus privileges to create/write the target pipeline tables and read the Volume.
6. The deploying identity needs privileges to create the configured catalog, schema, and volume, and permission to create/manage the App and pipeline.
7. App users need `SELECT` on the final `inspection_results` table, `READ VOLUME` on the drop-zone Volume, and `CAN USE` on the configured SQL warehouse. The App uses user authorization so those user permissions remain effective.

## Bundle variables

| Variable | Default | Required override? |
|---|---|---|
| `catalog` | `multimodal_demo` | optional |
| `schema` | `manufacturing` | optional |
| `volume` | `inspection_dropzone` | optional |
| `warehouse_id` | none | **yes** |
| `model_endpoint` | `system.ai.llama-4-maverick` | if unavailable |

Set variables with `BUNDLE_VAR_...` environment variables or `--var`:

```bash
export BUNDLE_VAR_warehouse_id="<warehouse-id>"

# Optional overrides
export BUNDLE_VAR_catalog="multimodal_demo"
export BUNDLE_VAR_schema="manufacturing"
export BUNDLE_VAR_volume="inspection_dropzone"
export BUNDLE_VAR_model_endpoint="system.ai.llama-4-maverick"
```

## Deploy

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```

The bundle uses the direct deployment engine to manage the catalog, schema, Volume, Lakeflow pipeline, refresh job, and Databricks App. The App has `lifecycle.started: true`, so deployment leaves it started.

The drop zone is:

```text
/Volumes/<catalog>/<schema>/<volume>/
```

`src/setup/setup.sql` contains the equivalent idempotent DDL as a readable/reference setup script. Bundle-managed UC resources are the deployment path, which guarantees the Volume exists before the pipeline resource is registered.

The sample images are intentionally **not** uploaded by deployment.

## External-ingestion simulation

Wave 1:

```bash
./utils/upload-images.sh ./wave1
# or
./utils/upload-images.sh ./wave1 --profile DEFAULT
```

Wave 2:

```bash
./utils/upload-images.sh ./wave2
```

Override the UC destination when needed:

```bash
./utils/upload-images.sh ./wave1 \
  --catalog multimodal_demo \
  --schema manufacturing \
  --volume inspection_dropzone
```

Environment variables `DEMO_CATALOG`, `DEMO_SCHEMA`, and `DEMO_VOLUME` are also accepted by the upload utility.

The utility uploads only `.png`, `.jpg`, and `.jpeg` files, preserves filenames, prints every upload, and never deletes anything from the drop zone.

## Trigger / update ingestion

```bash
databricks bundle run refresh_inspections -t dev
```

The job triggers a **normal** pipeline update (`full_refresh: false`). The Bronze table uses:

```sql
FROM STREAM read_files(
  '/Volumes/<catalog>/<schema>/<volume>/',
  format => 'file'
)
```

Lakeflow/Auto Loader state means the Wave 2 update discovers only files added after the Wave 1 update. Existing images are not manually deduplicated or rediscovered through custom filename state.

## Query the unified result

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

The `inspection_image` column is `FILE EXTERNAL`. The source bytes remain in the governed Volume rather than being copied into the Delta table.

## App behavior

The App page is intentionally small:

- title: **Visual Inspection**
- subtitle: **Native multimodal manufacturing data with Databricks FILE**
- cards: Total inspections, PASS, FAIL / REVIEW
- one visual card per inspection
- click a card for image, AI reason, manufacturing metadata, FILE URI, content type, size, and checksum

The browser never receives a Databricks credential. `/api/image/[inspectionId]` executes server-side, resolves the inspection row through Databricks SQL, then streams the referenced Volume file through the Databricks Files API.

The App requests only:

```text
sql:restricted-query
files
```

It reads the forwarded Databricks Apps user token server-side, so Unity Catalog controls continue to apply to the current user.

## Local Next.js / Bun development

Databricks Apps currently supports Node.js 22.16+. Bun is only a local convenience:

```bash
cd app
bun install
bun dev
```

For local access to Databricks data:

```bash
export DATABRICKS_HOST="https://<workspace-host>"
export DATABRICKS_TOKEN="<local-dev-token>"
export DATABRICKS_WAREHOUSE_ID="<warehouse-id>"
export DEMO_CATALOG="multimodal_demo"
export DEMO_SCHEMA="manufacturing"
```

Do not commit local `.env` files or credentials. In Databricks Apps, the SQL warehouse ID and Volume path come from App resource bindings instead.

Databricks Apps detects `package.json`, installs npm dependencies, runs `npm run build`, then runs the `app.yaml` command. Production starts `server.mjs`, which binds to `0.0.0.0` and uses `process.env.PORT` (falling back to `DATABRICKS_APP_PORT`).

## 5-minute Wave 1 → Wave 2 script

### 1. Set the frame

> “This Volume represents the drop zone of an external vision-inspection system. Databricks doesn’t own the camera; it governs and discovers what the camera system lands.”

### 2. Wave 1 — three PASS images

```bash
./utils/upload-images.sh ./wave1
databricks bundle run refresh_inspections -t dev
```

Open the App. With the three synthetic PASS images, the intended view is:

```text
3 inspections
3 PASS
0 FAIL / REVIEW
```

Then show `inspection_files` or `inspection_results` in SQL and point specifically at:

```sql
inspection_image FILE EXTERNAL
```

> “This is not an image path column. The image itself is a first-class data type with metadata and governed content access.”

### 3. Wave 2 — defects and review cases

Without clearing any table or pipeline state:

```bash
./utils/upload-images.sh ./wave2
databricks bundle run refresh_inspections -t dev
```

Refresh the App. Existing rows stay; only the newly arrived files flow through Bronze and then through the streaming AI result table.

> “External files arrived, were incrementally discovered, became FILE rows, were interpreted by multimodal AI, and the App immediately queried the unified result.”

### 4. Close

> **The image isn’t an attachment to the data anymore. It is data.**

## Design decisions and limitations

- **FILE is Beta.** The Lakeflow pipeline intentionally uses `channel: PREVIEW`.
- **FILE EXTERNAL is intentional.** The images already live in a UC Volume, so the table stores governed references without making a second copy.
- **No byte read for metadata.** URI, content type, size, and checksum are read from FILE metadata. `read_files` currently does not populate `FILE.checksum`, so the demo retains that field but deterministically falls back to `sha2(file.uri, 256)` for `inspection_id`. It does not read image bytes merely to create an ID.
- **AI needs image bytes.** `ai_query` currently accepts multimodal content through its `files` argument. `CAST(inspection_image AS BINARY)` is therefore the one native content read for inference; no custom downloader or base64 logic is used.
- **Incremental AI processing.** `inspection_results` is itself a streaming table reading `STREAM inspection_files`, so a normal Wave 2 update consumes new Bronze rows. A **full refresh** intentionally reprocesses everything.
- **Inference is illustrative, not validated GMP inspection.** The synthetic defects are designed to be visually obvious, but foundation-model classification remains probabilistic.
- **Image serving uses the Databricks Files API.** This keeps cloud-storage credentials out of the browser and keeps Volume authorization inside Databricks.
- **No package lock is committed in this minimal version.** Databricks Apps runs `npm install` when no pnpm lockfile is present. You can generate and commit `package-lock.json` with `npm install --package-lock-only` if your team wants a fully pinned npm dependency graph.

## Validation

Run before the demo in the target workspace:

```bash
# Bundle schema + workspace-aware validation
databricks bundle validate -t dev

# Node/Next build
cd app
npm install
npm run build

# Production startup smoke test
PORT=3000 DATABRICKS_HOST="https://<workspace-host>" \
DATABRICKS_TOKEN="<token>" DATABRICKS_WAREHOUSE_ID="<warehouse-id>" \
DEMO_CATALOG="multimodal_demo" DEMO_SCHEMA="manufacturing" \
npm run start
```

Then validate incremental behavior explicitly:

```bash
# Wave 1
./utils/upload-images.sh ./wave1
databricks bundle run refresh_inspections -t dev

# Wave 2 — no table clearing, no full refresh
./utils/upload-images.sh ./wave2
databricks bundle run refresh_inspections -t dev
```

A normal second update must retain Wave 1 rows and append only Wave 2 files/results.
