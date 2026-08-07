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
      className="space-y-16 py-16"
    >
      <PhotographSection
        file={file}
        previewUrl={previewUrl}
        exif={result?.exif ?? null}
        composition={result?.composition ?? null}
        recipe={ai?.fujifilm_recipe?.applicable === true ? ai.fujifilm_recipe : null}
        canEdit={status === "success"}
        onChooseAnother={onChooseAnother}
        onEditPhoto={onEditPhoto}
      />

      <div className="space-y-16">
        {status === "success" && (
          <CritiqueSection
            ai={ai}
            exif={result?.exif ?? null}
            loading={false}
            error={aiStatus === "error" ? aiError : null}
            delay={0}
          />
        )}
        <MeasurementsSection
          vision={result?.vision ?? null}
          composition={result?.composition ?? null}
          semantic={ai?.semantic_composition ?? null}
          imageUrl={previewUrl}
          loading={false}
          error={status === "error" ? error : null}
          delay={0.2}
        />
      </div>
    </motion.div>
  );
}
