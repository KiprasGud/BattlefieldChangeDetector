// Mirrors backend/app/contracts.py. FROZEN: change via small PR.
export type Confidence = "high" | "medium" | "low";
export type AlignMethod = "sift" | "ecc" | "none";
export type Category = "missing_object" | "new_structure" | "terrain_change" | "unknown_anomaly";

export const CATEGORY_ORDER: Category[] = ["missing_object", "new_structure", "terrain_change", "unknown_anomaly"];
export const CATEGORY_LABELS: Record<Category, string> = {
  missing_object: "Missing Equipment/Objects",
  new_structure: "New Structures/Construction",
  terrain_change: "Terrain/Landscape Changes",
  unknown_anomaly: "Unknown Anomaly",
};
export const CATEGORY_CODES: Record<Category, string> = {
  missing_object: "MISS",
  new_structure: "STRUCT",
  terrain_change: "TERR",
  unknown_anomaly: "UNK",
};

export interface Change {
  type: string;
  description: string;
  location_text: string;
  confidence: Confidence;
  box: [number, number, number, number]; // [ymin, xmin, ymax, xmax], 0-1000
  sector?: string | null;
  category?: Category | null; // review bucket, see CATEGORY_LABELS
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
  align_method?: AlignMethod;
  images: {
    aligned_b_url: string;
    annotated_url: string;
    image_a_url?: string;
    heatmap_url?: string;
  };
  timings?: Record<string, number>;
  warnings?: string[];
  lang?: string; // set from the job record (GET /api/jobs/{id}), not sent by sync /api/analyze
}
