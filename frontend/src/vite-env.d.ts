/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Origin the backend API is served from, e.g. "https://api.example.com".
   *
   * Leave unset (or empty) to use same-origin relative paths — correct for the
   * Vite dev proxy and for any deployment that puts the SPA and the API behind
   * one reverse proxy. Declared explicitly rather than leaning on vite/client's
   * index signature, which would type it as `any`.
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
