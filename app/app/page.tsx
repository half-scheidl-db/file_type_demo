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
  const fail = inspections.filter((item) => item.status === "FAIL").length;
  const review = inspections.filter((item) => item.status === "REVIEW").length;

  return (
    <main className="shell">
      <header className="hero">
        <div className="eyebrow">Pen Assembly 03 · VISION-01</div>
        <h1>Visual Quality Inspection</h1>
        <p>Automated inspection results for the current production batch.</p>
      </header>

      <section className="summary" aria-label="Inspection summary">
        <div className="summaryCard"><span>Total inspected</span><strong>{inspections.length}</strong></div>
        <div className="summaryCard pass"><span>Passed</span><strong>{pass}</strong></div>
        <div className="summaryCard fail"><span>Failed</span><strong>{fail}</strong></div>
        <div className="summaryCard attention"><span>Needs review</span><strong>{review}</strong></div>
      </section>

      {error ? (
        <div className="errorBox">
          <strong>Inspection data is currently unavailable.</strong>
          <span>{error}</span>
        </div>
      ) : (
        <InspectionGrid inspections={inspections} />
      )}
    </main>
  );
}
