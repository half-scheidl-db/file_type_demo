export type InspectionStatus = "PASS" | "FAIL" | "REVIEW";

export type InspectionRecord = {
  inspectionId: string;
  fileName: string;
  batchId: string;
  productionLine: string;
  equipmentId: string;
  inspectionTs: string;
  ingestedAt: string;
  status: InspectionStatus;
  observedIssue: string;
  confidence: number;
  reason: string;
  fileUri: string;
  contentType: string;
  fileSize: number;
  checksum: string | null;
};
