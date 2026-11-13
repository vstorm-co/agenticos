import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { SourceItem } from "@/lib/chat-sources";
import { MessageSources } from "./message-sources";

const page = (index: number, url: string): SourceItem => ({
  index,
  type: "web",
  title: "A page",
  url,
});

describe("the sources under an answer", () => {
  it("opens all sources directly in the panel without expanding the transcript", async () => {
    const onOpen = vi.fn();
    render(<MessageSources sources={[page(1, "https://example.org/a")]} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("button", { name: /1 source/ }));
    expect(onOpen).toHaveBeenCalledWith(null);
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByText("A page")).toBeNull();
  });

  it("counts documents rather than passages and limits the icon stack to four", () => {
    const sources: SourceItem[] = [
      { index: 1, type: "rag", title: "handbook.pdf", collection: "support" },
      { index: 2, type: "rag", title: "handbook.pdf", collection: "support" },
      ...[3, 4, 5, 6, 7].map((index) => page(index, `https://site${index}.example/`)),
    ];
    const { container } = render(<MessageSources sources={sources} onOpen={vi.fn()} />);
    expect(screen.getByRole("button", { name: /6 sources/ })).toBeVisible();
    expect(container.querySelectorAll("button > span:first-child > span")).toHaveLength(4);
  });

  it("requests a site's favicon without a referrer and falls back if it fails", () => {
    const { container } = render(
      <MessageSources sources={[page(1, "https://example.org/story")]} onOpen={vi.fn()} />,
    );
    const image = container.querySelector("img")!;
    expect(image).toHaveAttribute("src", "/api/link-icon?host=example.org");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    fireEvent.error(image);
    expect(container.querySelector(".lucide-globe")).not.toBeNull();
  });

  it("shows distinct web hosts ahead of repeated pages from the same site", () => {
    const sources = [1, 2, 3, 4].map((index) => page(index, `https://a.example/${index}`));
    sources.push(page(5, "https://b.example/"));
    const { container } = render(<MessageSources sources={sources} onOpen={vi.fn()} />);
    const urls = Array.from(container.querySelectorAll("img")).map((image) =>
      image.getAttribute("src"),
    );
    expect(urls.slice(0, 2)).toEqual([
      "/api/link-icon?host=a.example",
      "/api/link-icon?host=b.example",
    ]);
  });
});
