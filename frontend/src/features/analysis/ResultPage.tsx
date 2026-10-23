import { useNavigate, useParams } from "react-router";
import { ResultsView } from "@/features/results/ResultsView";
import { apiUrl } from "@/lib/api";
import { getOriginal } from "@/lib/sessionOriginals";
import { AnalyzingView } from "./AnalyzingView";
import { MessagePage } from "./MessagePage";
import { ShareBar } from "./ShareBar";
import { useAnalysis } from "./useAnalysis";

/**
 * /r/:id — one analysis, from first byte to finished report.
 *
 * While the job runs this is the progress view; once it settles it is the
 * report. The report still appears only when the critique is in, as before:
 * a complete report rather than one that fills in piecewise. The difference
 * is that the wait is now visibly real — stage by stage — and survives a
 * refresh, because the state lives on the server.
 */
export function ResultPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { snapshot, error, notFound, applySnapshot } = useAnalysis(id);
  const original = getOriginal(id);

  if (notFound) {
    return (
      <MessagePage
        title="Analysis not found"
        body="It may have been deleted, or it's private to the browser that created it."
      />
    );
  }
  if (error && !snapshot) {
    return <MessagePage title="Couldn't load this analysis" body={error} retry />;
  }

  const fileName = snapshot?.filename ?? original?.file.name ?? "photo";
  const previewUrl =
    original?.previewUrl ?? (snapshot?.image_url ? apiUrl(snapshot.image_url) : null);

  if (!snapshot || snapshot.status === "queued" || snapshot.status === "running") {
    return (
      <AnalyzingView
        previewUrl={previewUrl}
        fileName={fileName}
        job={snapshot?.jobs.analyze ?? null}
      />
    );
  }

  const measurements = snapshot.measurements;
  const failed = measurements === null;
  return (
    <ResultsView
      fileName={fileName}
      previewUrl={previewUrl}
      status={failed ? "error" : "success"}
      error={failed ? (snapshot.error ?? "Analysis failed.") : null}
      result={measurements}
      aiStatus={snapshot.ai ? "success" : failed ? "idle" : "error"}
      aiError={snapshot.ai ? null : (snapshot.jobs.analyze?.error ?? "The critique didn't finish.")}
      ai={snapshot.ai}
      onChooseAnother={() => navigate("/")}
      onEditPhoto={() => navigate(`/r/${id}/edit`)}
      toolbar={failed ? undefined : <ShareBar snapshot={snapshot} onChange={applySnapshot} />}
    />
  );
}
