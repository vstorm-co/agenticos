import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeptImage } from "./kept-image";

const kept = vi.hoisted(() => ({ file: vi.fn(async (): Promise<Blob | null> => null) }));
vi.mock("@/lib/offline/device-cache", () => ({ keptFile: kept.file }));

const revoke = vi.fn();

beforeEach(() => {
  kept.file.mockReset();
  revoke.mockReset();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:kept-photo", revokeObjectURL: revoke }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("KeptImage", () => {
  it("shows the server's picture, and the kept copy once that fails", async () => {
    kept.file.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
    const { unmount } = render(<KeptImage fileId="f-1" alt="photo.png" width={320} height={256} />);
    const image = screen.getByAltText("photo.png");
    expect(image.getAttribute("src")).toContain("/api/files/f-1");

    fireEvent.error(image);

    await waitFor(() => expect(image.getAttribute("src")).toBe("blob:kept-photo"));
    expect(kept.file).toHaveBeenCalledWith("f-1");
    // The copy failing as well is not asked for again.
    fireEvent.error(image);
    expect(kept.file).toHaveBeenCalledTimes(1);

    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:kept-photo");
  });

  it("stays the broken picture it was when nothing was kept", async () => {
    render(<KeptImage fileId="f-1" alt="photo.png" width={320} height={256} />);
    const image = screen.getByAltText("photo.png");

    await act(async () => {
      fireEvent.error(image);
    });

    expect(image.getAttribute("src")).toContain("/api/files/f-1");
  });
});
