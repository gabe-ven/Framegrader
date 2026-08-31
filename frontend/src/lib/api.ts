import type {
  AnalysisResponse,
  AIAnalysisResponse,
  ColorGradeResponse,
} from "@/types/analysis";

export const MAX_UPLOAD_MB = 25;
export const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/tiff",
  "image/bmp",
];

export class ApiError extends Error {}

/**
 * Origin the API is served from, baked in at build time.
 *
 * Defaults to "" so every call stays a same-origin relative path — what the
 * Vite dev proxy expects, and what a reverse proxy serving the SPA and the API
 * together expects. Set VITE_API_BASE_URL only when the two are on different
 * origins (static hosting for the SPA plus a separate API host), in which case
 * that origin must also appear in the backend's ALLOWED_ORIGINS.
 *
 * A trailing slash is stripped so "https://api.example.com/" and
 * "https://api.example.com" both produce a single-slash URL.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

/** Client-side guardrails that mirror the backend's validation. */
export function validateFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return "Unsupported file type. Use JPEG, PNG, WEBP, TIFF, or BMP.";
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Image is larger than the ${MAX_UPLOAD_MB}MB limit.`;
  }
  return null;
}

/** Callers pass an API path; the configured base is applied in one place. */
async function postForm<T>(path: string, body: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body });
  } catch {
    // fetch only rejects when the request never got a response at all — the
    // server is down, the connection dropped mid-flight (a backend restart
    // during a long AI call does this), or DNS/CORS refused it. The browser's
    // own message for all of these is the bare "Failed to fetch", which tells
    // the user nothing about what to do, so name the actual condition.
    throw new ApiError(
      "Couldn't reach the analysis server — it may be restarting or stopped. " +
        "Check the backend is running, then try again.",
    );
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {
      // response had no JSON body; keep the default message
    }
    throw new ApiError(detail);
  }

  return res.json();
}

export async function analyzeImage(file: File): Promise<AnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  return postForm<AnalysisResponse>("/api/analyze", body);
}

/**
 * Request the AI critique. Runs separately from analyzeImage so the fast CV
 * metrics can render first; the prior analysis is passed as `context` so the
 * model reasons from the already-computed measurements.
 */
export async function generateAIAnalysis(
  file: File,
  context?: AnalysisResponse | null,
): Promise<AIAnalysisResponse> {
  const body = new FormData();
  body.append("file", file);
  if (context) body.append("context", JSON.stringify(context));
  return postForm<AIAnalysisResponse>("/api/ai-analysis", body);
}

/**
 * Request AI color grading suggestions. `context` is typically the prior
 * /analyze response merged with the AI critique's scene summary, so the
 * model grounds its suggestion in the already-computed measurements.
 */
export async function requestColorGrade(
  file: File,
  context?: Record<string, unknown> | null,
): Promise<ColorGradeResponse> {
  const body = new FormData();
  body.append("file", file);
  if (context) body.append("context", JSON.stringify(context));
  return postForm<ColorGradeResponse>("/api/color-grade", body);
}
