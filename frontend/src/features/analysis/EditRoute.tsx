import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router";
import { PhotoSkeleton } from "@/components/Shimmer";
import { EditPage } from "@/features/edit/EditPage";
import { fetchImageBlob } from "@/lib/api";
import { getOriginal } from "@/lib/sessionOriginals";
import { MessagePage } from "./MessagePage";
import { useAnalysis } from "./useAnalysis";

/**
 * /r/:id/edit — the editor, for any analysis the viewer can open.
 *
 * Edits the full-resolution original when this tab uploaded it; otherwise
 * (after a refresh, or from a shared link) the server's 2048px stored copy,
 * so downloads from a shared link are at that size.
 */
export function EditRoute() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { snapshot, error, notFound, requestColorGrade, colorGradeRequestError } = useAnalysis(id);
  const original = getOriginal(id);
  const [stored, setStored] = useState<Blob | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const prefetched = useRef(false);

  const source: Blob | null = original?.file ?? stored;
  const imageUrl = snapshot?.image_url ?? null;

  useEffect(() => {
    if (original || !imageUrl) return;
    let cancelled = false;
    fetchImageBlob(imageUrl)
      .then((blob) => !cancelled && setStored(blob))
      .catch((err: unknown) => {
        if (!cancelled) setSourceError(err instanceof Error ? err.message : "Couldn't load the photo.");
      });
    return () => {
      cancelled = true;
    };
  }, [original, imageUrl]);

  // Warm the AI grade in the background as soon as the editor opens, as the
  // results page used to — it's ~10s of Claude time, and the user usually
  // reaches for "AI Suggestion" within that window. Cached server-side, so at
  // most one call per analysis however many times anyone opens this.
  useEffect(() => {
    if (!prefetched.current && snapshot?.measurements) {
      prefetched.current = true;
      void requestColorGrade();
    }
  }, [snapshot, requestColorGrade]);

  if (notFound) {
    return <MessagePage title="Analysis not found" body="It may have been deleted, or it's private." />;
  }
  if ((error && !snapshot) || sourceError) {
    return <MessagePage title="Couldn't open the editor" body={sourceError ?? error ?? ""} retry />;
  }
  if (snapshot && snapshot.status !== "succeeded") {
    // Still running, or failed: the result page shows the right thing.
    return <Navigate to={`/r/${id}`} replace />;
  }
  if (!snapshot || !source) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <PhotoSkeleton />
      </div>
    );
  }

  const job = snapshot.jobs.color_grade;
  const colorGradeStatus = snapshot.color_grade
    ? "success"
    : job?.status === "queued" || job?.status === "running"
      ? "loading"
      : job?.status === "failed" || colorGradeRequestError
        ? "error"
        : "idle";

  return (
    <EditPage
      source={source}
      fileName={snapshot.filename}
      histogram={snapshot.measurements?.vision.histogram ?? null}
      colorGrade={snapshot.color_grade}
      colorGradeStatus={colorGradeStatus}
      colorGradeError={colorGradeRequestError ?? job?.error ?? null}
      fetchColorGrade={() => void requestColorGrade()}
      onBack={() => navigate(`/r/${id}`)}
    />
  );
}
