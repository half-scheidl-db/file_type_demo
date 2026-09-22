import { downloadFile, getInspection } from "@/lib/databricks";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ inspectionId: string }> },
) {
  const { inspectionId } = await context.params;
  const inspection = await getInspection(inspectionId);

  if (!inspection) {
    return new Response("Inspection not found", { status: 404 });
  }

  try {
    const upstream = await downloadFile(inspection.fileUri);
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": inspection.contentType || upstream.headers.get("content-type") || "application/octet-stream",
        "Cache-Control": "private, max-age=60",
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to retrieve image";
    return new Response(message, { status: 502 });
  }
}
