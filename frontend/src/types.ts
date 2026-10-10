// Mirrors backend/app/contracts.py. FROZEN: change via small PR.
export type Confidence = "high" | "medium" | "low";

export interface Change {
  type: string;
  description: string;
  location_text: string;
  confidence: Confidence;
  box: [number, number, number, number]; // [ymin, xmin, ymax, xmax], 0-1000
  sector?: string | null;
}

export interface AnalysisResult {
  report_date: string;
  summary: string;
  changes: Change[];
  recommendation: string;
}

export interface AnalyzeResponse {
  job_id: string;
  result: AnalysisResult;
  align_quality: number;
  align_ok: boolean;
  images: { aligned_b_url: string; annotated_url: string };
}
