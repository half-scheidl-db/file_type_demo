import { headers } from "next/headers";
import type { InspectionRecord, InspectionStatus } from "./types";

const warehouseId = process.env.DATABRICKS_WAREHOUSE_ID;

function configuredNamespace(): { catalog: string; schema: string } {
  const volumePath = process.env.DATABRICKS_VOLUME_PATH;
  if (volumePath) {
    const parts = volumePath.split("/").filter(Boolean);
    if (parts.length >= 4 && parts[0] === "Volumes") {
      return { catalog: parts[1], schema: parts[2] };
    }
    throw new Error(`Unexpected DATABRICKS_VOLUME_PATH: ${volumePath}`);
  }

  // Local-development fallback only. Production receives the volume path from
  // the bundle-managed Databricks App resource binding.
  const localCatalog = process.env.DEMO_CATALOG;
  const localSchema = process.env.DEMO_SCHEMA;
  if (!localCatalog || !localSchema) {
    throw new Error("Set DATABRICKS_VOLUME_PATH or both DEMO_CATALOG and DEMO_SCHEMA");
  }
  return { catalog: localCatalog, schema: localSchema };
}

function safeIdentifier(value: string): string {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) {
    throw new Error(`Unsafe SQL identifier: ${value}`);
  }
  return `\`${value}\``;
}

const namespace = configuredNamespace();
const resultsTable = `${safeIdentifier(namespace.catalog)}.${safeIdentifier(namespace.schema)}.\`inspection_results\``;

function host(): string {
  const value = process.env.DATABRICKS_HOST;
  if (!value) throw new Error("DATABRICKS_HOST is not set");
  const trimmed = value.replace(/\/$/, "");
  // The Apps platform injects DATABRICKS_HOST as a bare hostname (no protocol).
  // Node fetch() requires an absolute URL, so prepend https:// when missing.
  return trimmed.match(/^https?:\/\//) ? trimmed : `https://${trimmed}`;
}

async function authToken(): Promise<string> {
  const requestHeaders = await headers();
  const userToken = requestHeaders.get("x-forwarded-access-token");
  if (userToken) return userToken;

  const localToken = process.env.DATABRICKS_TOKEN;
  if (localToken) return localToken;

  throw new Error("No Databricks user token is available");
}

async function dbFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await authToken();
  const response = await fetch(`${host()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Databricks API ${response.status}: ${body.slice(0, 500)}`);
  }
  return response;
}

type StatementResponse = {
  statement_id: string;
  status: { state: string; error?: { message?: string } };
  manifest?: { schema?: { columns?: Array<{ name: string; position: number }> } };
  result?: { data_array?: Array<Array<string | null>>; next_chunk_internal_link?: string | null };
};

async function executeStatement(statement: string): Promise<Array<Record<string, string | null>>> {
  if (!warehouseId) throw new Error("DATABRICKS_WAREHOUSE_ID is not set");

  let payload = (await (
    await dbFetch("/api/2.0/sql/statements", {
      method: "POST",
      body: JSON.stringify({
        warehouse_id: warehouseId,
        statement,
        wait_timeout: "30s",
        on_wait_timeout: "CONTINUE",
        disposition: "INLINE",
        format: "JSON_ARRAY",
      }),
    })
  ).json()) as StatementResponse;

  while (["PENDING", "RUNNING"].includes(payload.status.state)) {
    await new Promise((resolve) => setTimeout(resolve, 350));
    payload = (await (await dbFetch(`/api/2.0/sql/statements/${payload.statement_id}`)).json()) as StatementResponse;
  }

  if (payload.status.state !== "SUCCEEDED") {
    throw new Error(payload.status.error?.message ?? `SQL statement ended in ${payload.status.state}`);
  }

  const columns = [...(payload.manifest?.schema?.columns ?? [])].sort((a, b) => a.position - b.position);
  const rows: Array<Record<string, string | null>> = [];
  let chunk = payload.result;

  while (chunk) {
    for (const values of chunk.data_array ?? []) {
      const row: Record<string, string | null> = {};
      columns.forEach((column, index) => {
        row[column.name] = values[index] ?? null;
      });
      rows.push(row);
    }

    if (!chunk.next_chunk_internal_link) break;
    const next = (await (await dbFetch(chunk.next_chunk_internal_link)).json()) as { data_array?: Array<Array<string | null>>; next_chunk_internal_link?: string | null };
    chunk = next;
  }

  return rows;
}

function toRecord(row: Record<string, string | null>): InspectionRecord {
  return {
    inspectionId: row.inspection_id ?? "",
    fileName: row.file_name ?? "",
    batchId: row.batch_id ?? "",
    productionLine: row.production_line ?? "",
    equipmentId: row.equipment_id ?? "",
    inspectionTs: row.inspection_ts ?? "",
    ingestedAt: row.ingested_at ?? "",
    status: (row.status ?? "REVIEW") as InspectionStatus,
    observedIssue: row.observed_issue ?? "none",
    confidence: Number(row.confidence ?? 0),
    reason: row.reason ?? "",
    fileUri: row.file_uri ?? "",
    contentType: row.content_type ?? "application/octet-stream",
    fileSize: Number(row.file_size ?? 0),
    checksum: row.checksum,
  };
}

const projection = `
  inspection_id,
  file_name,
  batch_id,
  production_line,
  equipment_id,
  CAST(inspection_ts AS STRING) AS inspection_ts,
  CAST(ingested_at AS STRING) AS ingested_at,
  status,
  observed_issue,
  CAST(confidence AS STRING) AS confidence,
  reason,
  file_uri,
  content_type,
  CAST(file_size AS STRING) AS file_size,
  checksum`;

export async function listInspections(): Promise<InspectionRecord[]> {
  const rows = await executeStatement(`SELECT ${projection} FROM ${resultsTable} ORDER BY ingested_at DESC`);
  return rows.map(toRecord);
}

export async function getInspection(inspectionId: string): Promise<InspectionRecord | null> {
  if (!/^[a-f0-9]{64}$/i.test(inspectionId)) return null;
  const rows = await executeStatement(
    `SELECT ${projection} FROM ${resultsTable} WHERE inspection_id = '${inspectionId}' LIMIT 1`,
  );
  return rows[0] ? toRecord(rows[0]) : null;
}

function volumePath(uri: string): string {
  const path = uri.startsWith("dbfs:/Volumes/") ? uri.slice("dbfs:".length) : uri;
  if (!path.startsWith("/Volumes/")) throw new Error("FILE URI is not a Unity Catalog Volume path");
  return path;
}

export async function downloadFile(uri: string): Promise<Response> {
  const path = volumePath(uri);
  const encoded = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return dbFetch(`/api/2.0/fs/files${encoded}`);
}
