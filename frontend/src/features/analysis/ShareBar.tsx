import { useState } from "react";
import { Link } from "react-router";
import { setVisibility } from "@/lib/api";
import type { AnalysisSnapshot } from "@/types/analysis";

const BTN =
  "border-4 border-black px-4 py-2 font-mono text-xs font-black uppercase tracking-widest " +
  // 44px touch target on touch screens; inline-flex because the same classes
  // style a <Link>, and min-height is ignored on inline elements.
  "pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center " +
  "text-black shadow-[4px_4px_0_0_#000] transition-transform " +
  "hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-[2px_2px_0_0_#000] " +
  "disabled:opacity-50";

/**
 * Owner: make the result public (a /r/:id link anyone can open) or private
 * again, and copy the link. Anyone else: a banner saying whose this is not.
 */
export function ShareBar({
  snapshot,
  onChange,
}: {
  snapshot: AnalysisSnapshot;
  onChange: (snap: AnalysisSnapshot) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}/r/${snapshot.id}`;

  if (!snapshot.is_owner) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-4 border-4 border-black bg-yellow-400 px-5 py-3 shadow-[6px_6px_0_0_#000]">
        <p className="font-mono text-xs font-black uppercase tracking-widest text-black">
          Shared analysis
        </p>
        <Link to="/" className={`${BTN} bg-white`}>
          Analyze your own →
        </Link>
      </div>
    );
  }

  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      onChange(await setVisibility(snapshot.id, !snapshot.is_public));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't change sharing.");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Couldn't copy — select the link and copy it manually.");
    }
  };

  return (
    <div
      data-testid="share-bar"
      className="flex flex-wrap items-center gap-3 border-4 border-black bg-white px-5 py-3 shadow-[6px_6px_0_0_#000]"
    >
      <span className="font-mono text-xs font-black uppercase tracking-widest text-black">
        {snapshot.is_public ? "Public link" : "Private"}
      </span>
      {snapshot.is_public && (
        <>
          <input
            readOnly
            value={link}
            aria-label="Share link"
            onFocus={(e) => e.currentTarget.select()}
            className="min-w-0 flex-1 border-2 border-black bg-amber-50 px-2 py-1 font-mono text-xs text-black"
          />
          <button onClick={copy} className={`${BTN} bg-yellow-400`}>
            {copied ? "Copied ✓" : "Copy"}
          </button>
        </>
      )}
      <button onClick={toggle} disabled={busy} className={`${BTN} ${snapshot.is_public ? "bg-white" : "bg-yellow-400"} ml-auto`}>
        {snapshot.is_public ? "Make private" : "Create share link"}
      </button>
      {error && <p className="w-full font-mono text-xs font-bold text-red-600">{error}</p>}
    </div>
  );
}
