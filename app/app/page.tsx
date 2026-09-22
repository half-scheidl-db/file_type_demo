import InspectionGrid from "@/components/inspection-grid";
import { listInspections } from "@/lib/databricks";
import type { InspectionRecord } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function Home() {
  let inspections: InspectionRecord[] = [];
  let error: string | null = null;

  try {
    inspections = await listInspections();
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Could not query inspections";
  }

  const pass = inspections.filter((item) => item.status === "PASS").length;
  const failReview = inspections.filter((item) => item.status !== "PASS").length;

  return (
    <main className="shell">
      <header className="hero">
        <div className="eyebrow">Manufacturing quality control</div>
        <h1>Visual Inspection</h1>
        <p>Native multimodal manufacturing data with Databricks FILE</p>
      </header>

      <section className="summary" aria-label="Inspection summary">
        <div className="summaryCard"><span>Total inspections</span><strong>{inspections.length}</strong></div>
        <div className="summaryCard pass"><span>PASS</span><strong>{pass}</strong></div>
        <div className="summaryCard attention"><span>FAIL / REVIEW</span><strong>{failReview}</strong></div>
      </section>

      {error ? (
        <div className="errorBox">
          <strong>Could not load inspection data.</strong>
          <span>{error}</span>
        </div>
      ) : (
        <InspectionGrid inspections={inspections} />
      )}
    </main>
  );
}
