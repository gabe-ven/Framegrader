// Node has no ImageData. The pixel pipeline only needs the constructor shape
// (data, width, height), so a minimal stand-in is enough to test it for real.
if (typeof globalThis.ImageData === "undefined") {
  class NodeImageData {
    readonly data: Uint8ClampedArray;
    readonly width: number;
    readonly height: number;
    readonly colorSpace = "srgb" as const;

    constructor(data: Uint8ClampedArray, width: number, height?: number) {
      this.data = data;
      this.width = width;
      this.height = height ?? data.length / 4 / width;
    }
  }
  (globalThis as unknown as { ImageData: unknown }).ImageData = NodeImageData;
}
