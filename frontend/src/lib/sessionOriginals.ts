/**
 * Original uploads held in memory for the lifetime of the tab.
 *
 * The server keeps a 2048px copy of every photo (enough for the report and for
 * shared links) but deliberately not the full-resolution original. While the
 * tab that uploaded a photo is still open, though, the original File is right
 * here — so the editor exports at full resolution and the report shows the
 * instant local preview instead of waiting for the stored copy.
 *
 * Gone on refresh, by design: after a reload the app falls back to the stored
 * copy, which is exactly what any other viewer of the link sees.
 */

interface SessionOriginal {
  file: File;
  previewUrl: string | null;
}

const originals = new Map<string, SessionOriginal>();

export function rememberOriginal(id: string, file: File, previewUrl: string | null): void {
  originals.set(id, { file, previewUrl });
}

export function getOriginal(id: string): SessionOriginal | undefined {
  return originals.get(id);
}

export function forgetOriginal(id: string): void {
  const entry = originals.get(id);
  if (entry?.previewUrl) URL.revokeObjectURL(entry.previewUrl);
  originals.delete(id);
}
