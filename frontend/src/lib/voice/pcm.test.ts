import { describe, expect, it, vi } from "vitest";

import { createPcmCapture, createPcmPlayer } from "./pcm";

/**
 * A fake `AudioContext`: enough of Web Audio to see what is scheduled and when.
 * Gemini, xAI and Azure are not verified live; this is the browser half, faked.
 */
function fakeContext(sampleRate = 48_000) {
  const sources: {
    buffer: { length: number; data: Float32Array } | null;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    onended: (() => void) | null;
  }[] = [];
  let processor: {
    listener: ((event: { inputBuffer: unknown }) => void) | null;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  } | null = null;
  const node = () => ({ connect: vi.fn(), disconnect: vi.fn() });
  const destination = { ...node(), stream: { id: "agent" } };
  const context = {
    sampleRate,
    currentTime: 0,
    destination: {},
    createBuffer: (_channels: number, length: number) => {
      const data = new Float32Array(length);
      return { length, data, getChannelData: () => data };
    },
    createBufferSource: () => {
      const source = { buffer: null, ...node(), start: vi.fn(), stop: vi.fn(), onended: null };
      sources.push(source);
      return source;
    },
    createMediaStreamDestination: () => destination,
    createMediaStreamSource: vi.fn(node),
    createGain: () => ({ ...node(), gain: { value: 1 } }),
    createScriptProcessor: () => {
      processor = {
        listener: null,
        ...node(),
      };
      return {
        ...processor,
        addEventListener: (_type: string, listener: (event: { inputBuffer: unknown }) => void) => {
          processor!.listener = listener;
        },
      };
    },
  };
  return {
    context: context as unknown as AudioContext & { currentTime: number },
    raw: context,
    sources,
    destination,
    process: (channels: Float32Array[]) =>
      processor!.listener!({
        inputBuffer: {
          numberOfChannels: channels.length,
          getChannelData: (i: number) => channels[i],
        },
      }),
  };
}

/** `samples` of 16-bit PCM, every sample `value`. */
function pcm(samples: number, value = 0x4000): ArrayBuffer {
  const view = new DataView(new ArrayBuffer(samples * 2));
  for (let i = 0; i < samples; i += 1) view.setInt16(i * 2, value, true);
  return view.buffer;
}

describe("createPcmPlayer", () => {
  it("schedules chunks back to back at the model's rate and decodes them", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);

    player.enqueue(pcm(2400));
    player.enqueue(pcm(2400, -0x8000));

    expect(fake.sources.map((source) => source.start.mock.calls[0]![0])).toEqual([0, 0.1]);
    expect(fake.sources[0]!.buffer!.data[0]).toBe(0.5);
    expect(fake.sources[1]!.buffer!.data[0]).toBe(-1);
    expect(fake.sources[0]!.connect).toHaveBeenCalledWith(fake.destination);
    expect(player.stream).toBe(fake.destination.stream);
  });

  it("counts what was played, in whole samples of the bytes it was sent", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);
    player.enqueue(pcm(2400));
    player.enqueue(pcm(2400));

    expect(player.playedBytes()).toBe(0);
    fake.raw.currentTime = 0.05;
    expect(player.playedBytes()).toBe(2400);
    fake.raw.currentTime = 0.1;
    expect(player.playedBytes()).toBe(4800);
    fake.raw.currentTime = 0.3;
    expect(player.playedBytes()).toBe(9600);
  });

  it("starts a chunk that arrives after a silence when it arrives, not in the past", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);
    player.enqueue(pcm(2400));
    fake.raw.currentTime = 1;
    player.enqueue(pcm(2400));
    expect(fake.sources[1]!.start).toHaveBeenCalledWith(1);
  });

  it("drops what is queued on clear, counting it as passed, and plays on afterwards", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);
    player.enqueue(pcm(2400));
    player.enqueue(pcm(2400));
    fake.raw.currentTime = 0.05;

    player.clear();

    expect(fake.sources.every((source) => source.stop.mock.calls.length === 1)).toBe(true);
    // The server's coordinate: everything it sent is behind the playhead now.
    expect(player.playedBytes()).toBe(9600);
    player.enqueue(pcm(2400));
    expect(fake.sources[2]!.start).toHaveBeenCalledWith(0.05);
  });

  it("ignores an empty chunk, and closing stops everything and lets go of the stream", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);
    player.enqueue(new ArrayBuffer(1));
    expect(fake.sources).toHaveLength(0);
    player.enqueue(pcm(10));
    player.close();
    expect(fake.sources[0]!.stop).toHaveBeenCalled();
    expect(fake.destination.disconnect).toHaveBeenCalled();
  });
});

describe("createPcmPlayer's drain", () => {
  it("says so when the last chunk queued has played, and not for an earlier or a cleared one", () => {
    const fake = fakeContext();
    const drained = vi.fn();
    const player = createPcmPlayer(fake.context, 24_000, drained);
    player.enqueue(pcm(2400));
    player.enqueue(pcm(2400));

    fake.sources[0]!.onended!();
    expect(drained).not.toHaveBeenCalled();
    fake.sources[1]!.onended!();
    expect(drained).toHaveBeenCalledTimes(1);

    player.enqueue(pcm(2400));
    player.clear();
    fake.sources[2]!.onended!();
    expect(drained).toHaveBeenCalledTimes(1);
  });

  it("needs no listener", () => {
    const fake = fakeContext();
    const player = createPcmPlayer(fake.context, 24_000);
    player.enqueue(pcm(10));
    expect(() => fake.sources[0]!.onended!()).not.toThrow();
  });
});

describe("createPcmCapture", () => {
  it("sends the microphone as 16-bit mono PCM at the model's rate", () => {
    const fake = fakeContext(48_000);
    const chunks: ArrayBuffer[] = [];
    const stream = {} as MediaStream;

    const capture = createPcmCapture(fake.context, stream, 24_000, (chunk) => chunks.push(chunk));
    fake.process([new Float32Array(4096).fill(0.5), new Float32Array(4096).fill(0.5)]);

    expect(fake.raw.createMediaStreamSource).toHaveBeenCalledWith(stream);
    expect(chunks).toHaveLength(1);
    expect(chunks[0]!.byteLength).toBe(4096);
    expect(new DataView(chunks[0]!).getInt16(0, true)).toBe(16383);
    capture.stop();
  });
});
