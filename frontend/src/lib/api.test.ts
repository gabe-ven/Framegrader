import { describe, expect, it } from "vitest";
import type { AnalysisSnapshot, JobView } from "@/types/analysis";
import { isSettled, readEventStream } from "./api";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>) {
  const out = [];
  for await (const e of readEventStream(body)) out.push(e);
  return out;
}

describe("readEventStream", () => {
  it("parses events split across arbitrary chunk boundaries", async () => {
    const events = await collect(
      streamOf("event: snap", 'shot\ndata: {"a"', ":1}\n\n: keep-alive\n\nevent: end\ndata: {}\n\n"),
    );
    expect(events).toEqual([
      { type: "snapshot", data: '{"a":1}' },
      { type: "end", data: "{}" },
    ]);
  });

  it("handles CRLF line endings and multi-line data", async () => {
    const events = await collect(streamOf("data: one\r\ndata: two\r\n\r\n"));
    expect(events).toEqual([{ type: "message", data: "one\ntwo" }]);
  });

  it("keeps a multi-byte character split between chunks intact", async () => {
    const bytes = new TextEncoder().encode("data: café\n\n");
    const split = bytes.indexOf(0xc3) + 1; // inside the two-byte "é"
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, split));
        c.enqueue(bytes.slice(split));
        c.close();
      },
    });
    expect(await collect(body)).toEqual([{ type: "message", data: "café" }]);
  });
});

describe("isSettled", () => {
  const job = (status: JobView["status"]): JobView => ({
    id: "j", kind: "analyze", status, stage: null, progress: 0, stages: [], error: null, queue_position: null,
  });
  const snap = (status: AnalysisSnapshot["status"], jobs: AnalysisSnapshot["jobs"]) =>
    ({ status, jobs }) as AnalysisSnapshot;

  it("waits for every job, including a later color grade", () => {
    expect(isSettled(snap("succeeded", { analyze: job("succeeded") }))).toBe(true);
    expect(isSettled(snap("running", { analyze: job("running") }))).toBe(false);
    expect(
      isSettled(snap("succeeded", { analyze: job("succeeded"), color_grade: job("queued") })),
    ).toBe(false);
  });
});
