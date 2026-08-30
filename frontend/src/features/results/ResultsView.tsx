import { motion } from "framer-motion";
import type { AIAnalysis, AnalysisResponse } from "@/types/analysis";
import { CritiqueSection } from "./CritiqueSection";
import { MeasurementsSection } from "./MeasurementsSection";
import { PhotographSection } from "./PhotographSection";

type Status = "idle" | "loading" | "success" | "error";

interface ResultsViewProps {
  file: File;
  previewUrl: string | null;
  status: Status;
  error: string | null;
  result: AnalysisResponse | null;
  aiStatus: Status;
  aiError: string | null;
  ai: AIAnalysis | null;
  onChooseAnother: () => void;
  onEditPhoto: () => void;
}

/** Orchestrates the results report — this is where section order lives. */
export function ResultsView({
  file,
  previewUrl,
  status,
  error,
  result,
  aiStatus,
  aiError,
  ai,
  onChooseAnother,
  onEditPhoto,
}: ResultsViewProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="theme-comic relative left-1/2 w-screen -translate-x-1/2 bg-bg py-16"
    >
      {/* Re-establish the max-5xl reading width App.tsx would otherwise
          provide — the full-bleed wrapper above is only there to paint the
          background edge-to-edge, not to let the report's own content
          stretch past its normal width. */}
      <div className="mx-auto max-w-5xl space-y-16 px-6">
        <PhotographSection
          file={file}
          previewUrl={previewUrl}
          exif={result?.exif ?? null}
          composition={result?.composition ?? null}
          recipe={result?.recipe?.applicable === true ? result.recipe : null}
          canEdit={status === "success"}
          onChooseAnother={onChooseAnother}
          onEditPhoto={onEditPhoto}
        />

        {/* Each section owns its own loading state: measurements track the CV
            request, the critique tracks the (much slower) AI request. They fill
            in independently rather than the whole report waiting on the slowest. */}
        <div className="space-y-16">
          {status === "success" && (
            <CritiqueSection
              ai={ai}
              exif={result?.exif ?? null}
              loading={aiStatus === "loading"}
              error={aiStatus === "error" ? aiError : null}
              delay={0}
            />
          )}
          <MeasurementsSection
            vision={result?.vision ?? null}
            composition={result?.composition ?? null}
            semantic={ai?.semantic_composition ?? null}
            imageUrl={previewUrl}
            loading={status === "loading"}
            error={status === "error" ? error : null}
            delay={0.2}
          />
        </div>
      </div>
    </motion.div>
  );
}
