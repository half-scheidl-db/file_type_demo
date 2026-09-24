"use client";

import { useState } from "react";
import type { InspectionRecord } from "@/lib/types";

function sizeLabel(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function timeLabel(value: string) {
  if (!value) return "—";
  const date = new Date(value.replace(" ", "T"));
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function observationTone(value: string | boolean) {
  if (value === true) return "negative";
  if (["MISSING", "MISALIGNED", "DETACHED", "DAMAGED", "PRESENT", "INSUFFICIENT"].includes(String(value))) {
    return "negative";
  }
  if (value === "UNKNOWN") return "review";
  return "normal";
}

function observationLabel(value: string | boolean) {
  if (typeof value === "boolean") return value ? "Detected" : "None";
  return value.replaceAll("_", " ").toLowerCase();
}

function Observation({
  label,
  value,
}: {
  label: string;
  value: string | boolean;
}) {
  return (
    <div className="observation">
      <dt>{label}</dt>
      <dd className={`observationValue ${observationTone(value)}`}>{observationLabel(value)}</dd>
    </div>
  );
}

export default function InspectionGrid({ inspections }: { inspections: InspectionRecord[] }) {
  const [selected, setSelected] = useState<InspectionRecord | null>(null);

  if (inspections.length === 0) {
    return (
      <section className="emptyState">
        <strong>No inspection results available</strong>
        <span>New inspection records will appear here after processing.</span>
      </section>
    );
  }

  return (
    <>
      <div className="sectionHeading">
        <div>
          <h2>Inspection records</h2>
          <p>Latest automated assessments for the current batch.</p>
        </div>
        <span className="recordCount">{inspections.length} records</span>
      </div>

      <section className="grid" aria-label="Inspection records">
        {inspections.map((item) => (
          <button key={item.inspectionId} className="inspectionCard" onClick={() => setSelected(item)}>
            <div className="imageFrame">
              {/* Native FILE content is proxied by a server-side route; no credential reaches the browser. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/api/image/${item.inspectionId}`} alt={`Inspection ${item.fileName}`} />
              <span className={`badge ${item.status.toLowerCase()}`}>{item.status}</span>
            </div>
            <div className="cardBody">
              <div className="filename" title={item.fileName}>{item.fileName}</div>
              <dl>
                <div><dt>Batch</dt><dd>{item.batchId}</dd></div>
                <div><dt>Line</dt><dd>{item.productionLine}</dd></div>
                <div><dt>Finding</dt><dd>{item.observedIssue || "none"}</dd></div>
                <div><dt>Confidence</dt><dd>{Math.round(item.confidence * 100)}%</dd></div>
              </dl>
            </div>
          </button>
        ))}
      </section>

      {selected && (
        <div className="modalBackdrop" role="presentation" onMouseDown={() => setSelected(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label={`Inspection ${selected.fileName}`}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button className="closeButton" aria-label="Close" onClick={() => setSelected(null)}>×</button>
            <div className="modalImage">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/api/image/${selected.inspectionId}`} alt={`Inspection ${selected.fileName}`} />
            </div>
            <div className="modalBody">
              <div className="modalTitleRow">
                <div>
                  <div className="eyebrow">Inspection result</div>
                  <h2>{selected.fileName}</h2>
                </div>
                <span className={`badge static ${selected.status.toLowerCase()}`}>{selected.status}</span>
              </div>

              <div className="reason">
                <strong>{selected.observedIssue || "none"}</strong>
                <span>{selected.reason}</span>
              </div>

              <div className="subsectionTitle">Inspection checks</div>
              <dl className="observations">
                <Observation label="Protective cap" value={selected.capStatus} />
                <Observation label="Label alignment" value={selected.labelAlignment} />
                <Observation label="Label attachment" value={selected.labelAttachment} />
                <Observation label="Housing" value={selected.housingCondition} />
                <Observation label="Contamination" value={selected.contamination} />
                <Observation label="Obstruction" value={selected.imageObstruction} />
                <Observation label="Image quality" value={selected.imageQuality} />
                <Observation label="Confidence" value={`${Math.round(selected.confidence * 100)}%`} />
              </dl>

              <div className="subsectionTitle">Production context</div>
              <dl className="details">
                <div><dt>Batch</dt><dd>{selected.batchId}</dd></div>
                <div><dt>Production line</dt><dd>{selected.productionLine}</dd></div>
                <div><dt>Equipment</dt><dd>{selected.equipmentId}</dd></div>
                <div><dt>Inspection timestamp</dt><dd>{timeLabel(selected.inspectionTs)}</dd></div>
                <div><dt>Content type</dt><dd>{selected.contentType || "—"}</dd></div>
                <div><dt>File size</dt><dd>{sizeLabel(selected.fileSize)}</dd></div>
                <div className="wide"><dt>Source file</dt><dd>{selected.fileUri}</dd></div>
                <div className="wide"><dt>Checksum</dt><dd>{selected.checksum || "Not available"}</dd></div>
              </dl>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
