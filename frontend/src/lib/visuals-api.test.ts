import { beforeEach, describe, expect, it, vi } from "vitest";

const { post, raw } = vi.hoisted(() => ({ post: vi.fn(), raw: vi.fn() }));
vi.mock("./api-client", () => ({ apiClient: { post, raw } }));

import { getVisualImage, publishVisual } from "./visuals-api";

describe("visuals API", () => {
  beforeEach(() => {
    post.mockReset();
    raw.mockReset();
  });

  it("saves a visual of a conversation under a name", async () => {
    post.mockResolvedValue({ version: 1 });
    await publishVisual("c1", "toolu/1", { name: "flow" });
    expect(post).toHaveBeenCalledWith("/conversations/c1/visuals/toolu%2F1/publish", {
      name: "flow",
    });
  });

  it("reads a picture as a data URI", async () => {
    raw.mockResolvedValue({ blob: async () => new Blob(["hi"], { type: "image/png" }) });
    const uri = await getVisualImage("c1", "v", "logo");
    expect(raw).toHaveBeenCalledWith("/conversations/c1/visuals/v/images/logo");
    expect(uri).toBe("data:image/png;base64,aGk=");
  });

  it("fails when the picture cannot be read", async () => {
    raw.mockResolvedValue({ blob: async () => new Blob(["x"]) });
    const failing = vi.spyOn(FileReader.prototype, "readAsDataURL").mockImplementation(function (
      this: FileReader,
    ) {
      this.onerror?.(new ProgressEvent("error") as ProgressEvent<FileReader>);
    });
    await expect(getVisualImage("c1", "v", "logo")).rejects.toBeTruthy();
    failing.mockRestore();
  });
});
