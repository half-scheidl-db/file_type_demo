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

export default function InspectionGrid({ inspections }: { inspections: InspectionRecord[] }) {
  const [selected, setSelected] = useState<InspectionRecord | null>(null);

  if (inspections.length === 0) {
    return (
      <section className="emptyState">
        <strong>No inspections yet</strong>
        <span>Drop images into the Unity Catalog Volume, then update the pipeline.</span>
      </section>
    );
  }

  return (
    <>
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
                <div><dt>Issue</dt><dd>{item.observedIssue || "none"}</dd></div>
                <div><dt>Confidence</dt><dd>{Math.round(item.confidence * 100)}%</dd></div>
              </dl>
            </div>
          </button>
        ))}
      </section>

      {selected && (
        <div className="modalBackdrop" role="presentation" onMouseDown={() => setSelected(null)}>
          <section className="modal" role="dialog" aria-modal="true" aria-label={`Inspection ${selected.fileName}`} onMouseDown={(event) => event.stopPropagation()}>
            <button className="closeButton" aria-label="Close" onClick={() => setSelected(null)}>×</button>
            <div className="modalImage">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`/api/image/${selected.inspectionId}`} alt={`Inspection ${selected.fileName}`} />
            </div>
            <div className="modalBody">
              <div className="modalTitleRow">
                <div><div className="eyebrow">AI interpretation</div><h2>{selected.fileName}</h2></div>
                <span className={`badge static ${selected.status.toLowerCase()}`}>{selected.status}</span>
              </div>
              <div className="reason"><strong>{selected.observedIssue || "none"}</strong><span>{selected.reason}</span></div>
              <dl className="details">
                <div><dt>Confidence</dt><dd>{Math.round(selected.confidence * 100)}%</dd></div>
                <div><dt>Batch</dt><dd>{selected.batchId}</dd></div>
                <div><dt>Production line</dt><dd>{selected.productionLine}</dd></div>
                <div><dt>Equipment</dt><dd>{selected.equipmentId}</dd></div>
                <div><dt>Inspection timestamp</dt><dd>{timeLabel(selected.inspectionTs)}</dd></div>
                <div><dt>Content type</dt><dd>{selected.contentType || "—"}</dd></div>
                <div><dt>Size</dt><dd>{sizeLabel(selected.fileSize)}</dd></div>
                <div className="wide"><dt>FILE URI</dt><dd>{selected.fileUri}</dd></div>
                <div className="wide"><dt>Checksum</dt><dd>{selected.checksum || "not populated by file ingestion"}</dd></div>
              </dl>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
