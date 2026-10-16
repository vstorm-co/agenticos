import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SourceItem } from "@/lib/chat-sources";

import { MessageSources } from "./message-sources";

vi.mock("@/hooks/use-knowledge-bases", () => ({
  useKnowledgeBaseFor: () => (collection: string | undefined) =>
    collection === "support_aa" ? { id: "kb-1", name: "Support handbook" } : undefined,
}));
vi.mock("@/components/kb/source-viewer", () => ({
  SourceViewer: ({ cited, onClose }: { cited: { filename: string }; onClose: () => void }) => (
    <button type="button" onClick={onClose}>
      close {cited.filename}
    </button>
  ),
}));

const passage = (index: number, title: string, collection = "support_aa"): SourceItem => ({
  index,
  type: "rag",
  title,
  collection,
});

const page = (index: number, url: string, title = "A page"): SourceItem => ({
  index,
  type: "web",
  title,
  url,
});

async function expand(sources: SourceItem[], onOpen = vi.fn()) {
  render(<MessageSources sources={sources} onOpen={onOpen} />);
  await userEvent.click(screen.getByRole("button", { expanded: false }));
  return onOpen;
}

/**
 * What an answer drew on, under it.
 *
 * Counted by document - five passages of a handbook are one source to whoever
 * reads the answer - and opening onto the documents, each of which opens the
 * panel on its passages or, for a file, the file itself.
 */
describe("the sources under an answer", () => {
  it("stacks no more than four marks, however many documents there are", () => {
    const sources = [1, 2, 3, 4, 5].map((i) => page(i, `https://site${i}.example/`));
    const { container } = render(<MessageSources sources={sources} onOpen={vi.fn()} />);

    expect(screen.getByRole("button", { name: /5 sources/ })).toBeInTheDocument();
    expect(container.querySelectorAll(".lucide-globe")).toHaveLength(4);
  });

  it("shows one of each kind of source before a second of any", () => {
    const sources = [
      passage(1, "a.md"),
      passage(2, "b.md"),
      passage(3, "c.md"),
      page(4, "https://github.com/acme/api"),
      page(5, "https://blog.example/"),
      page(6, "https://github.com/acme/web"),
    ];
    const { container } = render(<MessageSources sources={sources} onOpen={vi.fn()} />);

    // A file, GitHub and the web all make the cut ahead of a second file.
    const marks = container.querySelectorAll("button > span:first-child > span");
    expect(marks).toHaveLength(4);
    expect(container.querySelectorAll("button .lucide-globe")).toHaveLength(1);
  });

  it("names where each document is, and how many of its passages were cited", async () => {
    await expand([
      passage(1, "refunds.md"),
      passage(2, "refunds.md"),
      page(3, "https://www.notion.so/x", "Roadmap"),
    ]);

    expect(screen.getByText("Support handbook · 2 passages")).toBeInTheDocument();
    expect(screen.getByText("notion.so")).toBeInTheDocument();
  });

  it("opens the panel on a document's first passage", async () => {
    const onOpen = await expand([passage(1, "a.md"), passage(4, "b.md")]);

    await userEvent.click(screen.getByRole("button", { name: /^b\.md/ }));

    expect(onOpen).toHaveBeenCalledWith(4);
  });

  it("opens a file whole from its base, and closes it again", async () => {
    await expand([passage(1, "refunds.md")]);

    await userEvent.click(screen.getByRole("button", { name: "Open the original of refunds.md" }));
    await userEvent.click(screen.getByRole("button", { name: "close refunds.md" }));

    expect(screen.queryByRole("button", { name: "close refunds.md" })).toBeNull();
  });

  it("offers no original for a file in a base the reader cannot see", async () => {
    await expand([passage(1, "secret.md", "elsewhere")]);

    expect(screen.queryByRole("button", { name: /Open the original/ })).toBeNull();
    expect(screen.getByText("secret.md")).toBeInTheDocument();
  });

  it("links a web page out, in a tab that cannot reach back", async () => {
    await expand([page(1, "https://github.com/acme/api", "acme/api")]);

    const link = screen.getByRole("link", { name: "Open acme/api" });
    expect(link).toHaveAttribute("href", "https://github.com/acme/api");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("names no site for a page the search returned without an address", async () => {
    await expand([{ index: 1, type: "web", title: "Untitled hit" }]);

    expect(screen.getByText("Untitled hit")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("folds the list away again", async () => {
    await expand([passage(1, "a.md")]);

    await userEvent.click(screen.getByRole("button", { expanded: true }));

    expect(screen.queryByRole("list")).toBeNull();
  });
});
