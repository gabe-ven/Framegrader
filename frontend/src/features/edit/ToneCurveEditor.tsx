import { useEffect, useMemo, useRef } from "react";
import ReactECharts from "echarts-for-react";
import type { ECharts, EChartsOption } from "echarts";
import type { Histogram } from "@/types/analysis";
import {
  CURVE_INPUTS,
  CURVE_LABELS,
  buildCurveLUT,
  normalizeCurve,
  type ToneCurve,
} from "./toneCurve";

interface ToneCurveEditorProps {
  curve: ToneCurve;
  onChange: (curve: ToneCurve) => void;
  histogram: Histogram | null;
}

// Tight grid so the 0–255 × 0–255 curve space fills the dark panel edge to edge.
const GRID = { left: 6, right: 6, top: 8, bottom: 8 };

export function ToneCurveEditor({ curve, onChange, histogram }: ToneCurveEditorProps) {
  const chartRef = useRef<ReactECharts>(null);
  // Captured for the imperative ECharts drag handlers, which must always read
  // and write the latest state even though they close over a single render.
  const curveRef = useRef(curve);
  const onChangeRef = useRef(onChange);
  curveRef.current = curve;
  onChangeRef.current = onChange;

  // Luminance histogram (Rec. 601) mapped into the curve's coordinate space:
  // bin index -> 0–255 input axis, normalized height -> 0–255 output axis.
  const lumData = useMemo(() => {
    if (!histogram) return null;
    const n = histogram.bins;
    const lum = Array.from(
      { length: n },
      (_, i) => 0.299 * histogram.r[i] + 0.587 * histogram.g[i] + 0.114 * histogram.b[i],
    );
    const max = Math.max(1, ...lum);
    return lum.map((v, i) => [(i / (n - 1)) * 255, (v / max) * 255]);
  }, [histogram]);

  const option = useMemo<EChartsOption>(() => {
    // Draw the line straight from the applied LUT, so what you see is exactly
    // the mapping the canvas uses — not an approximate ECharts smoothing.
    const lut = buildCurveLUT(curve);
    const curveLine = Array.from({ length: 256 }, (_, x) => [x, lut[x]]);

    const series: Record<string, unknown>[] = [];
    if (lumData) {
      series.push({
        type: "line",
        data: lumData,
        showSymbol: false,
        silent: true,
        lineStyle: { width: 0 },
        areaStyle: { color: "rgba(255,255,255,0.14)" },
        z: 1,
      });
    }
    series.push({
      type: "line",
      data: curveLine,
      showSymbol: false,
      silent: true,
      lineStyle: { color: "#ffffff", width: 1.5 },
      z: 2,
    });

    return {
      animation: false,
      grid: GRID,
      xAxis: { type: "value", min: 0, max: 255, show: false },
      yAxis: { type: "value", min: 0, max: 255, show: false },
      series,
    } as EChartsOption;
  }, [curve, lumData]);

  // Handles live as ECharts `graphic` elements positioned in pixel space, which
  // depends on the laid-out grid — so they're set imperatively here and kept in
  // sync on curve change and container resize. Stable ids let ECharts update
  // them in place rather than recreate them, so an in-flight drag isn't dropped.
  useEffect(() => {
    const chart = chartRef.current?.getEchartsInstance() as ECharts | undefined;
    if (!chart) return;

    // echarts-for-react can hand back an instance whose internal model hasn't
    // been built yet — this effect can run before the chart has applied its own
    // setOption. convertToPixel dereferences that model, so calling it early
    // throws ("Cannot read properties of undefined (reading 'queryComponents')")
    // and took the whole editor down with it. Every conversion is gated on the
    // model existing; `finished` below is the retry for the not-yet-ready case.
    const isReady = () => !chart.isDisposed() && chart.getOption() != null;

    const position = () => {
      if (!isReady()) return;
      const handles = CURVE_INPUTS.map((inX, i) => {
        const [px, py] = chart.convertToPixel({ gridIndex: 0 }, [inX, curveRef.current[i]]);
        return {
          id: `handle-${i}`,
          type: "circle",
          x: px,
          y: py,
          shape: { cx: 0, cy: 0, r: 5 },
          style: { fill: "#ffffff", stroke: "#111111", lineWidth: 1 },
          draggable: true,
          cursor: "ns-resize",
          z: 100,
          ondrag: function (this: { x: number; y: number }) {
            // zrender drag callbacks run outside React, so a throw here escapes
            // every error boundary — guard rather than rely on one.
            if (!isReady()) return;
            // Lock x to the anchor's column — only vertical drags change output.
            this.x = chart.convertToPixel({ gridIndex: 0 }, [inX, 0])[0];
            const dataY = chart.convertFromPixel({ gridIndex: 0 }, [this.x, this.y])[1];
            const y = Math.max(0, Math.min(255, dataY));
            const next = normalizeCurve(curveRef.current.map((v, j) => (j === i ? y : v)));
            onChangeRef.current(next);
          },
        };
      });
      chart.setOption({ graphic: handles });
    };

    let observer: ResizeObserver | undefined;

    const start = () => {
      position();
      const dom = chart.getDom();
      if (!dom) return;
      observer = new ResizeObserver(position);
      observer.observe(dom);
    };

    // Fires after the first render pass, by which point the model exists.
    // Detached on entry so the setOption inside position() can't re-trigger it.
    const onFinished = () => {
      chart.off("finished", onFinished);
      start();
    };

    if (isReady()) {
      start();
    } else {
      chart.on("finished", onFinished);
    }

    return () => {
      if (!chart.isDisposed()) chart.off("finished", onFinished);
      observer?.disconnect();
    };
  }, [curve, lumData]);

  return (
    <div className="mt-4">
      <span className="font-mono text-[10px] uppercase tracking-widest text-muted">
        Tone curve
      </span>
      <div className="mt-2 border border-[#e0e0e0]" style={{ background: "#111111" }}>
        <ReactECharts
          ref={chartRef}
          option={option}
          notMerge={false}
          style={{ height: 240, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[8px] uppercase tracking-widest text-muted">
        {CURVE_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
    </div>
  );
}
