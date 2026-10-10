import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { captureThisTab } from "./assistant-screenshot";

const stop = vi.fn();
const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
let getDisplayMedia: ReturnType<typeof vi.fn>;
let blob: Blob | null;

beforeEach(() => {
  stop.mockReset();
  blob = new Blob(["png"], { type: "image/png" });
  getDisplayMedia = vi.fn().mockResolvedValue(stream);
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getDisplayMedia },
    configurable: true,
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((done) => done(blob));
});

afterEach(() => vi.restoreAllMocks());

describe("captureThisTab", () => {
  it("takes one frame as a PNG and stops capturing at once", async () => {
    const file = await captureThisTab();

    expect(file?.type).toBe("image/png");
    expect(file?.name).toMatch(/^screenshot-.*\.png$/);
    expect(stop).toHaveBeenCalled();
    expect(getDisplayMedia).toHaveBeenCalledWith(
      expect.objectContaining({ preferCurrentTab: true }),
    );
  });

  it("is nothing when the person declines to share", async () => {
    getDisplayMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));

    await expect(captureThisTab()).resolves.toBeNull();
  });

  it("lets any other failure through, for the caller to report", async () => {
    getDisplayMedia.mockRejectedValue(new Error("no capture here"));

    await expect(captureThisTab()).rejects.toThrow("no capture here");
  });

  it("is nothing when the frame cannot be encoded, and still stops", async () => {
    blob = null;

    await expect(captureThisTab()).resolves.toBeNull();
    expect(stop).toHaveBeenCalled();
  });
});
