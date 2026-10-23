import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { apiUrl, deleteAnalysis, listHistory } from "@/lib/api";
import { forgetOriginal } from "@/lib/sessionOriginals";
import type { HistoryItem } from "@/types/analysis";

const CARD = "border-4 border-black bg-white shadow-[6px_6px_0_0_#000]";
const BTN =
  "border-4 border-black px-4 py-2 font-mono text-xs font-black uppercase tracking-widest " +
  "text-black shadow-[4px_4px_0_0_#000] disabled:opacity-50";

/**
 * /history — every analysis this browser has made, newest first.
 *
 * "This browser" is literal: ownership is the anonymous X-Client-Id in
 * localStorage, so history is per-browser and private without any login.
 */
export function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (before: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const page = await listHistory(before);
      setItems((prev) => (before == null ? page.items : [...prev, ...page.items]));
      setNextBefore(page.next_before);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load history.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(null);
  }, [load]);

  const remove = async (id: string) => {
    try {
      await deleteAnalysis(id);
      forgetOriginal(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete.");
    }
  };

  return (
    <div className="theme-comic relative left-1/2 min-h-screen w-screen -translate-x-1/2 bg-bg py-16">
      <div className="mx-auto max-w-5xl space-y-8 px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h1 className="font-sans text-4xl font-black uppercase tracking-tight text-black">
            History
          </h1>
          <Link to="/" className={`${BTN} bg-red-500 text-white`}>
            Analyze a photo →
          </Link>
        </div>

        {error && (
          <p role="alert" className="border-4 border-black bg-red-500 px-4 py-3 font-mono text-sm font-bold text-white">
            {error}
          </p>
        )}

        {!loading && items.length === 0 && !error && (
          <div className={`${CARD} p-8 text-center`}>
            <p className="font-mono text-sm font-bold text-black">
              No analyses yet. They're saved here automatically, in this browser.
            </p>
          </div>
        )}

        <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3" data-testid="history-list">
          {items.map((item) => (
            <HistoryCard key={item.id} item={item} onDelete={() => remove(item.id)} />
          ))}
        </ul>

        {nextBefore != null && (
          <div className="flex justify-center">
            <button onClick={() => load(nextBefore)} disabled={loading} className={`${BTN} bg-white`}>
              {loading ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryCard({ item, onDelete }: { item: HistoryItem; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const date = new Date(item.created_at * 1000);

  return (
    <li className={`${CARD} flex flex-col`}>
      <Link to={`/r/${item.id}`} className="block aspect-[4/3] overflow-hidden border-b-4 border-black bg-amber-50">
        {item.thumb_url ? (
          <img
            src={apiUrl(item.thumb_url)}
            alt={item.filename}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <span className="flex h-full items-center justify-center font-mono text-xs font-black uppercase text-black/50">
            {item.status === "failed" ? "Failed" : "Processing…"}
          </span>
        )}
      </Link>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <Link to={`/r/${item.id}`} className="truncate font-sans text-sm font-black text-black hover:underline">
            {item.filename}
          </Link>
          {item.composition_score != null && (
            <span className="shrink-0 border-2 border-black bg-yellow-400 px-2 font-mono text-xs font-black text-black">
              {Math.round(item.composition_score)}
            </span>
          )}
        </div>
        {item.scene_summary && (
          <p className="line-clamp-2 text-xs font-bold text-black/70">{item.scene_summary}</p>
        )}
        <div className="mt-auto flex items-center justify-between gap-2 pt-2">
          <span className="font-mono text-[10px] font-black uppercase tracking-widest text-black/60">
            {date.toLocaleDateString()} · {item.is_public ? "Public" : "Private"}
          </span>
          {confirming ? (
            <span className="flex gap-2">
              <button onClick={onDelete} className="font-mono text-[10px] font-black uppercase text-red-600">
                Delete
              </button>
              <button onClick={() => setConfirming(false)} className="font-mono text-[10px] font-black uppercase text-black">
                Keep
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              aria-label={`Delete ${item.filename}`}
              className="font-mono text-[10px] font-black uppercase text-black/60 hover:text-red-600"
            >
              Delete
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
