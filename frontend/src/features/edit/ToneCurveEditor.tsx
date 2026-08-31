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
        areaStyle: { color: "rgba(0,0,0,0.16)" },
        z: 1,
      });
    }
    series.push({
      type: "line",
      data: curveLine,
      showSymbol: false,
      silent: true,
      lineStyle: { color: "#000000", width: 4 },
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
    let cancelled = false;
    let raf = 0;
    let observer: ResizeObserver | undefined;

    // Resolve the instance on every use rather than capturing it once.
    // echarts-for-react disposes and recreates its instance across React's
    // double-mount, so an effect that closes over the first one holds a dead
    // reference forever — isReady() then fails on every call and the drag
    // handles are never added, leaving a curve that renders but cannot be
    // moved. Re-reading the ref means we always talk to the live chart.
    const liveChart = (): ECharts | null => {
      const c = chartRef.current?.getEchartsInstance() as ECharts | undefined;
      if (!c || c.isDisposed()) return null;
      // echarts-for-react can hand back an instance whose internal model has
      // not been built yet; convertToPixel dereferences that model and throws
      // ("Cannot read properties of undefined (reading 'queryComponents')").
      return c.getOption() != null ? c : null;
    };

    const position = () => {
      const chart = liveChart();
      if (!chart) return;
      const handles = CURVE_INPUTS.map((inX, i) => {
        const [px, py] = chart.convertToPixel({ gridIndex: 0 }, [inX, curveRef.current[i]]);
        return {
          id: `handle-${i}`,
          type: "circle",
          x: px,
          y: py,
          shape: { cx: 0, cy: 0, r: 7 },
          style: { fill: "#facc15", stroke: "#000000", lineWidth: 3 },
          draggable: true,
          cursor: "ns-resize",
          z: 100,
          ondrag: function (this: { x: number; y: number }) {
            // zrender drag callbacks run outside React, so a throw here escapes
            // every error boundary — resolve and guard rather than rely on one.
            const c = liveChart();
            if (!c) return;
            // Lock x to the anchor's column — only vertical drags change output.
            this.x = c.convertToPixel({ gridIndex: 0 }, [inX, 0])[0];
            const dataY = c.convertFromPixel({ gridIndex: 0 }, [this.x, this.y])[1];
            const y = Math.max(0, Math.min(255, dataY));
            const next = normalizeCurve(curveRef.current.map((v, j) => (j === i ? y : v)));
            onChangeRef.current(next);
          },
        };
      });
      chart.setOption({ graphic: handles });
    };

    // Poll a frame at a time until a live, initialised instance exists. This
    // replaces waiting on the chart's "finished" event, which fired on the
    // instance that then got disposed.
    const startWhenReady = () => {
      if (cancelled) return;
      const chart = liveChart();
      if (!chart) {
        raf = requestAnimationFrame(startWhenReady);
        return;
      }
      position();
      const dom = chart.getDom();
      if (dom) {
        observer = new ResizeObserver(position);
        observer.observe(dom);
      }
    };
    startWhenReady();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      observer?.disconnect();
    };
  }, [curve, lumData]);

  return (
    <div className="mt-6">
      <span className="inline-block border-4 border-black bg-yellow-400 px-3 py-1 font-mono text-[10px] font-black uppercase tracking-widest text-black shadow-[4px_4px_0_0_#000]">
        Tone curve
      </span>
      <div className="mt-3 border-4 border-black" style={{ background: "#ffffff" }}>
        <ReactECharts
          ref={chartRef}
          option={option}
          notMerge={false}
          style={{ height: 240, width: "100%" }}
          opts={{ renderer: "canvas" }}
        />
      </div>
      <div className="mt-2 flex justify-between font-mono text-[9px] font-black uppercase tracking-widest text-black">
        {CURVE_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
    </div>
  );
}
