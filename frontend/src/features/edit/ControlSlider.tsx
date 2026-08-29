interface ControlSliderProps {
  label: string;
  value: number;
  aiValue: number;
  min: number;
  max: number;
  step: number;
  trackGradient: string;
  onChange: (value: number) => void;
}

export function ControlSlider({
  label,
  value,
  aiValue,
  min,
  max,
  step,
  trackGradient,
  onChange,
}: ControlSliderProps) {
  const isDirty = value !== aiValue;
  const decimals = step < 1 ? 1 : 0;

  return (
    <div className="py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="group/reset relative flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-muted">
          {label}
          {isDirty && (
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title="Differs from AI suggestion" />
          )}
          <span className="pointer-events-none absolute left-0 top-full z-10 mt-1 whitespace-nowrap font-mono text-[10px] normal-case tracking-normal text-subtle opacity-0 transition-opacity group-hover/reset:opacity-100">
            double-click to reset
          </span>
        </span>
        <span className="font-mono text-sm text-ink">{formatSigned(value, decimals)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onDoubleClick={() => onChange(aiValue)}
        style={{ "--slider-gradient": trackGradient } as React.CSSProperties}
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
