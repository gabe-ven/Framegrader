import type {
  AnalysisSnapshot,
  CreatedAnalysis,
  HistoryPage,
  JobView,
} from "@/types/analysis";

export const MAX_UPLOAD_MB = 25;
export const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/tiff",
  "image/bmp",
];

export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

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

/** Absolute URL for an API path (also used for server-issued image URLs). */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

const CLIENT_ID_KEY = "framegrader.clientId";
let memoryClientId: string | null = null;

/**
 * This browser's anonymous identity: a random UUID kept in localStorage and
 * sent as X-Client-Id. The server stores only its hash, as the owner of each
 * analysis this browser creates — it is what makes history private and what
 * authorises sharing and deleting. Clearing site data forgets it (and with
 * it, access to private analyses); public links keep working.
 */
export function getClientId(): string {
  try {
    const stored = localStorage.getItem(CLIENT_ID_KEY);
    if (stored) return stored;
    const fresh = crypto.randomUUID();
    localStorage.setItem(CLIENT_ID_KEY, fresh);
    return fresh;
  } catch {
    // Storage blocked (private mode, sandboxed iframe): stable for this tab.
    memoryClientId ??= crypto.randomUUID();
    return memoryClientId;
  }
}

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("X-Client-Id", getClientId());
  return headers;
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

// For a request that never got a response at all — the server is down, the
// connection dropped mid-flight, or DNS/CORS refused it. The browser's own
// message for all of these is the bare "Failed to fetch", which tells the
// user nothing about what to do.
const UNREACHABLE =
  "Couldn't reach the analysis server — it may be restarting or stopped. " +
  "Check the backend is running, then try again.";

/** The server's `detail` message from an error body, or a generic one. */
function errorDetail(status: number, body: string): string {
  try {
    const data = JSON.parse(body);
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    // response had no JSON body; use the default message
  }
  return `Request failed (${status}).`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { ...init, headers: authHeaders(init.headers) });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError(UNREACHABLE);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(errorDetail(res.status, body), res.status);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface UploadProgress {
  sent: number;
  total: number;
}

/**
 * Upload a photo and queue its analysis. Resolves as soon as it is queued.
 *
 * XMLHttpRequest rather than fetch: fetch has no upload progress events, and
 * sending a full-size camera JPEG takes several seconds on a home connection
 * (measured ~3.4 MB/s to the Render host) — long enough that a button with no
 * progress on it reads as frozen.
 */
export function createAnalysis(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<CreatedAnalysis> {
  const body = new FormData();
  body.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("/api/analyses"));
    authHeaders().forEach((value, key) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.({ sent: e.loaded, total: e.total });
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new ApiError(errorDetail(xhr.status, xhr.responseText), xhr.status));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText));
      } catch {
        reject(new ApiError(errorDetail(xhr.status, ""), xhr.status));
      }
    };
    xhr.onerror = () => reject(new ApiError(UNREACHABLE));
    xhr.send(body);
  });
}

export function getAnalysis(id: string, signal?: AbortSignal): Promise<AnalysisSnapshot> {
  return request<AnalysisSnapshot>(`/api/analyses/${encodeURIComponent(id)}`, { signal });
}

export function listHistory(before?: number | null): Promise<HistoryPage> {
  const qs = before != null ? `?before=${before}` : "";
  return request<HistoryPage>(`/api/analyses${qs}`);
}

export function setVisibility(id: string, isPublic: boolean): Promise<AnalysisSnapshot> {
  return request<AnalysisSnapshot>(`/api/analyses/${encodeURIComponent(id)}/visibility`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ public: isPublic }),
  });
}

export function deleteAnalysis(id: string): Promise<void> {
  return request<void>(`/api/analyses/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** Queue an AI color-grade suggestion. Idempotent server-side. */
export function requestColorGrade(id: string): Promise<JobView> {
  return request<JobView>(`/api/analyses/${encodeURIComponent(id)}/color-grade`, {
    method: "POST",
  });
}

/** The stored copy of a photo, for editing when the original File is gone. */
export async function fetchImageBlob(url: string): Promise<Blob> {
  const res = await fetch(apiUrl(url));
  if (!res.ok) throw new ApiError(`Couldn't load the photo (${res.status}).`, res.status);
  return res.blob();
}

/** True once nothing about this analysis can change without a new request. */
export function isSettled(snap: AnalysisSnapshot): boolean {
  const terminal = (s: string) => s === "succeeded" || s === "failed";
  return terminal(snap.status) && Object.values(snap.jobs).every((j) => !j || terminal(j.status));
}

const POLL_INTERVAL_MS = 1500;

/**
 * Follow an analysis until it settles: Server-Sent Events first, polling as
 * the fallback.
 *
 * SSE is read through fetch rather than EventSource because EventSource
 * cannot send the X-Client-Id header that private analyses require. If the
 * stream can't be opened or drops (a proxy that buffers event streams, a
 * flaky mobile connection), this quietly switches to polling the same
 * snapshot endpoint — the caller can't tell the difference.
 *
 * Resolves with the final snapshot; rejects only on a hard error (404, abort).
 */
export async function followAnalysis(
  id: string,
  onSnapshot: (snap: AnalysisSnapshot) => void,
  signal: AbortSignal,
): Promise<AnalysisSnapshot> {
  let last: AnalysisSnapshot | null = null;
  const emit = (snap: AnalysisSnapshot) => {
    if (!last || snap.version !== last.version) onSnapshot(snap);
    last = snap;
  };

  try {
    const res = await fetch(apiUrl(`/api/analyses/${encodeURIComponent(id)}/events`), {
      headers: authHeaders({ Accept: "text/event-stream" }),
      signal,
    });
    if (res.status === 404) throw new ApiError("Analysis not found.", 404);
    if (res.ok && res.body) {
      for await (const event of readEventStream(res.body)) {
        if (event.type === "snapshot") emit(JSON.parse(event.data) as AnalysisSnapshot);
        if (event.type === "gone") throw new ApiError("Analysis not found.", 404);
        if (event.type === "end" && last) return last;
      }
    }
  } catch (err) {
    if (err instanceof ApiError || signal.aborted) throw err;
    // Network or stream failure: fall through to polling.
  }

  for (;;) {
    const snap = await getAnalysis(id, signal);
    emit(snap);
    if (isSettled(snap)) return snap;
    await sleep(POLL_INTERVAL_MS, signal);
  }
}

export interface SseEvent {
  type: string;
  data: string;
}

/** Minimal text/event-stream parser: yields one {type, data} per event. */
export async function* readEventStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      // stream: true keeps a multi-byte character split across chunks intact.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let type = "message";
        const data: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith(":")) continue; // keep-alive comment
          if (line.startsWith("event:")) type = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        }
        if (data.length) yield { type, data: data.join("\n") };
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}
