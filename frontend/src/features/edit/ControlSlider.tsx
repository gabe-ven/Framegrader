interface ControlSliderProps {
  label: string;
  value: number;
  aiValue: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}

export function ControlSlider({
  label,
  value,
  aiValue,
  min,
  max,
  step,
  onChange,
}: ControlSliderProps) {
  const isDirty = value !== aiValue;
  const decimals = step < 1 ? 1 : 0;

  return (
    <div className="py-3">
      <div className="mb-2 flex items-center justify-between gap-4">
        <span className="group/reset relative flex items-center gap-2 font-mono text-[11px] font-black uppercase tracking-widest text-black">
          {label}
          {/* A hard square, not a soft dot — same vocabulary as the borders. */}
          {isDirty && (
            <span
              className="h-2.5 w-2.5 border-2 border-black bg-red-500"
              title="Differs from AI suggestion"
            />
          )}
          <span className="pointer-events-none absolute left-0 top-full z-10 mt-1 whitespace-nowrap border-2 border-black bg-yellow-400 px-1.5 py-0.5 font-mono text-[9px] font-bold normal-case tracking-normal text-black opacity-0 transition-opacity group-hover/reset:opacity-100">
            double-click to reset
          </span>
        </span>
        {/* Raw-data readout: monospace, heavy, tight. */}
        <span className="font-mono text-lg font-black tracking-tighter text-black">
          {formatSigned(value, decimals)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onDoubleClick={() => onChange(aiValue)}
        className="control-slider cursor-pointer"
      />
    </div>
  );
}

function formatSigned(value: number, decimals: number): string {
  const rounded = Number(value.toFixed(decimals));
  const fixed = rounded.toFixed(decimals);
  return rounded > 0 ? `+${fixed}` : fixed;
}
