import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ArtifactThumbnail } from "./artifact-thumbnail";

const thumbnail = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifactThumbnail: (...args: unknown[]) => thumbnail(...args),
}));
let intersect: IntersectionObserverCallback;
class Visibility {
  constructor(callback: IntersectionObserverCallback) {
    intersect = callback;
  }
  observe() {}
  disconnect() {}
}
beforeEach(() => {
  thumbnail.mockReset();
  vi.stubGlobal("IntersectionObserver", Visibility);
});
afterEach(() => vi.unstubAllGlobals());
function show() {
  act(() =>
    intersect([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver),
  );
}
describe("static App thumbnails", () => {
  it("loads only near the viewport and never executes an App in an iframe", () => {
    thumbnail.mockReturnValue({ isPending: true });
    const { container } = render(
      <ArtifactThumbnail artifactId="a" title="Report" versionId="v1" />,
    );
    expect(thumbnail).toHaveBeenLastCalledWith("a", "v1", false);
    expect(container.querySelector("iframe")).toBeNull();
    show();
    expect(thumbnail).toHaveBeenLastCalledWith("a", "v1", true);
    expect(container.querySelector("[data-preview-skeleton]")).not.toBeNull();
  });
  it("shows a cached version immediately on returning to the listing", async () => {
    thumbnail.mockReturnValue({
      data: { state: "ready", image: "data:image/jpeg;base64,aGVsbG8=" },
    });
    const first = render(<ArtifactThumbnail artifactId="a" title="Report" versionId="v1" />);
    expect(screen.getByTitle("Report")).toHaveAttribute("src", "data:image/jpeg;base64,aGVsbG8=");
    first.unmount();
    const { container } = render(
      <ArtifactThumbnail artifactId="a" title="Report" versionId="v1" />,
    );
    fireEvent.load(screen.getByTitle("Report"));
    expect(screen.getByTitle("Report")).toBeVisible();
    await waitFor(() => expect(container.querySelector("[data-preview-skeleton]")).toBeNull());
    expect(container.querySelector("iframe")).toBeNull();
  });
  it("keeps the placeholder until the image loads and settles on a broken image", () => {
    thumbnail.mockReturnValue({ data: { state: "ready", image: "data:image/jpeg;base64,aA==" } });
    const { container } = render(<ArtifactThumbnail artifactId="a" title="Report" />);
    expect(container.querySelector("[data-preview-skeleton]")).not.toBeNull();
    fireEvent.error(screen.getByTitle("Report"));
    expect(container.querySelector("[data-preview-skeleton]")).toBeNull();
    expect(container.querySelector("[data-unavailable=true]")).not.toBeNull();
  });
  it("selects a new cache entry when the publication version changes", () => {
    thumbnail.mockReturnValue({ data: { state: "ready", image: "data:image/jpeg;base64,aA==" } });
    const { rerender } = render(<ArtifactThumbnail artifactId="a" title="Report" versionId="v1" />);
    show();
    thumbnail.mockReturnValue({ isPending: true });
    rerender(<ArtifactThumbnail artifactId="a" title="Report" versionId="v2" />);
    expect(thumbnail).toHaveBeenLastCalledWith("a", "v2", true);
    expect(screen.queryByTitle("Report")).toBeNull();
  });
  it.each([{ isError: true }, { data: { state: "unavailable", image: null } }])(
    "does not pulse forever when a preview is unavailable",
    (result) => {
      thumbnail.mockReturnValue(result);
      const { container } = render(<ArtifactThumbnail artifactId="a" title="Report" />);
      show();
      expect(container.querySelector("[data-unavailable=true]")).not.toBeNull();
      expect(container.querySelector("[data-preview-skeleton]")).toBeNull();
    },
  );
  it("defers work where visibility observation is unavailable", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    thumbnail.mockReturnValue({});
    render(<ArtifactThumbnail artifactId="a" title="Report" />);
    expect(thumbnail).toHaveBeenLastCalledWith("a", null, false);
  });
});
