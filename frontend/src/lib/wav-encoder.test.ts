import { describe, expect, it } from "vitest";

import {
  createResampler,
  mixToMono,
  toPcm16,
  WAV_HEADER_BYTES,
  wavBlob,
  wavHeader,
} from "./wav-encoder";

function ascii(view: DataView, offset: number, length: number): string {
  return String.fromCharCode(...Array.from({ length }, (_, i) => view.getUint8(offset + i)));
}

/** Every chunk through one resampler, joined, as plain numbers. */
function resampleAll(fromRate: number, chunks: Float32Array[]): number[] {
  const resample = createResampler(fromRate);
  return chunks.flatMap((chunk) => Array.from(resample(chunk)));
}

describe("mixToMono", () => {
  it("averages the channels into one, sample by sample", () => {
    const left = Float32Array.from([1, 0.5, -1]);
    const right = Float32Array.from([0, 0.5, 1]);

    expect(Array.from(mixToMono([left, right]))).toEqual([0.5, 0.5, 0]);
  });

  it("copies a single channel rather than handing back a view of it", () => {
    const only = Float32Array.from([0.25, -0.25]);

    const mono = mixToMono([only]);
    only.fill(0);

    expect(Array.from(mono)).toEqual([0.25, -0.25]);
  });

  it("stops at the shortest channel", () => {
    expect(mixToMono([new Float32Array(4), new Float32Array(3)])).toHaveLength(3);
  });
});

describe("createResampler", () => {
  it("passes 16 kHz through unchanged", () => {
    expect(resampleAll(16_000, [Float32Array.from([0.5, -0.5, 0.25])])).toEqual([0.5, -0.5, 0.25]);
  });

  it("averages each window of three when downsampling from 48 kHz", () => {
    const input = Float32Array.from([0, 0.3, 0.6, 1, 1, 1, -1, -1, -1]);

    const output = resampleAll(48_000, [input]);

    expect(output).toHaveLength(3);
    expect(output[0]).toBeCloseTo(0.3);
    expect(output[1]).toBeCloseTo(1);
    expect(output[2]).toBeCloseTo(-1);
  });

  it("carries a window split across two chunks into the next call", () => {
    const resample = createResampler(48_000);

    const first = resample(Float32Array.from([1, 1, 1, 0.5]));
    const second = resample(Float32Array.from([0.5, 0.5]));

    expect(Array.from(first)).toEqual([1]);
    expect(Array.from(second)).toEqual([0.5]);
  });

  it("keeps the rate exact over many odd-sized chunks from 44.1 kHz", () => {
    // One second of input in chunks that never line up with a window.
    const chunks = Array.from({ length: 30 }, () => new Float32Array(1470).fill(0.1));

    const output = resampleAll(44_100, chunks);

    expect(output.length).toBeGreaterThanOrEqual(15_999);
    expect(output.length).toBeLessThanOrEqual(16_000);
    for (const sample of output) expect(sample).toBeCloseTo(0.1);
  });

  it("repeats the nearest sample when upsampling from 8 kHz", () => {
    expect(resampleAll(8_000, [Float32Array.from([0.5, -0.5])])).toEqual([0.5, 0.5, -0.5, -0.5]);
  });

  it("returns nothing for a chunk too short to fill a window", () => {
    expect(resampleAll(48_000, [Float32Array.from([1, 1])])).toEqual([]);
  });
});

describe("toPcm16", () => {
  it("writes each sample as a little-endian 16-bit integer over the full range", () => {
    const view = new DataView(toPcm16(Float32Array.from([0, 1, -1, 0.5])));

    expect(view.byteLength).toBe(8);
    expect(view.getInt16(0, true)).toBe(0);
    expect(view.getInt16(2, true)).toBe(32_767);
    expect(view.getInt16(4, true)).toBe(-32_768);
    expect(view.getInt16(6, true)).toBe(16_383);
    // Little-endian: the low byte of 32767 (0xff) comes first.
    expect(view.getUint8(2)).toBe(0xff);
    expect(view.getUint8(3)).toBe(0x7f);
  });

  it("clips a sample louder than full scale instead of wrapping it", () => {
    const view = new DataView(toPcm16(Float32Array.from([1.7, -3])));

    expect(view.getInt16(0, true)).toBe(32_767);
    expect(view.getInt16(2, true)).toBe(-32_768);
  });
});

describe("wavHeader", () => {
  it("is the canonical 44-byte RIFF/WAVE header for 16 kHz mono 16-bit PCM", () => {
    const view = new DataView(wavHeader(32_000));

    expect(view.byteLength).toBe(WAV_HEADER_BYTES);
    expect(ascii(view, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + 32_000);
    expect(ascii(view, 8, 4)).toBe("WAVE");
    expect(ascii(view, 12, 4)).toBe("fmt ");
    expect(view.getUint32(16, true)).toBe(16);
    expect(view.getUint16(20, true)).toBe(1);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint32(28, true)).toBe(32_000);
    expect(view.getUint16(32, true)).toBe(2);
    expect(view.getUint16(34, true)).toBe(16);
    expect(ascii(view, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(32_000);
  });
});

describe("wavBlob", () => {
  it("is the header followed by every chunk, typed audio/wav", async () => {
    const chunks = [toPcm16(Float32Array.from([1, 0])), toPcm16(Float32Array.from([-1]))];

    const blob = wavBlob(chunks);

    expect(blob.type).toBe("audio/wav");
    expect(blob.size).toBe(WAV_HEADER_BYTES + 6);
    const view = new DataView(await blob.arrayBuffer());
    expect(view.getUint32(4, true)).toBe(36 + 6);
    expect(view.getUint32(40, true)).toBe(6);
    expect(view.getInt16(44, true)).toBe(32_767);
    expect(view.getInt16(46, true)).toBe(0);
    expect(view.getInt16(48, true)).toBe(-32_768);
  });

  it("is a header alone, with no data, for no audio", () => {
    expect(wavBlob([]).size).toBe(WAV_HEADER_BYTES);
  });
});
