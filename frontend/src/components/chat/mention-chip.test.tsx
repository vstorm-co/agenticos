import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MCP_LOGOS } from "@/lib/mcp-logos.generated";
import type { Mentionable } from "@/types/mention";
import { LinkFavicon } from "./link-favicon";
import { MentionChip, RichText } from "./mention-chip";

vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ slug }: { slug: string }) => <span data-testid="face">{slug}</span>,
}));
vi.mock("@/components/branding/brand-mark", () => ({
  BrandMark: () => <span data-testid="brand-mark" />,
}));

describe("a mention chip", () => {
  it.each<[Mentionable, string]>([
    [{ kind: "collection", id: "k", name: "Contracts" }, "lucide-database"],
    [{ kind: "skill", id: "s", name: "refunds" }, "lucide-book-open"],
    [{ kind: "context", id: "c", name: "glossary" }, "lucide-file-text"],
    [{ kind: "project", id: "p", name: "Launch" }, "lucide-folder-kanban"],
  ])("draws what kind of thing %o is", (item, icon) => {
    const { container } = render(<MentionChip item={item} />);
    expect(container.querySelector(`.${icon}`)).not.toBeNull();
    expect(screen.getByTitle(item.name)).toHaveTextContent(item.name);
  });

  it("draws the platform's own server in the deployment's mark, not a monogram", () => {
    render(
      <MentionChip
        item={{ kind: "mcp", id: "platform", name: "agenticos", detail: "agenticos_*" }}
      />,
    );

    expect(screen.getByTestId("brand-mark")).toBeInTheDocument();
  });

  it("draws a server in its brand's colours, from the host it is reached on", () => {
    const { container } = render(
      <MentionChip item={{ kind: "mcp", id: "c", name: "Linear", host: "mcp.linear.app" }} />,
    );

    expect(container.querySelector("img")).toHaveAttribute("src", MCP_LOGOS["mcp.linear.app"]);
  });

  it("draws an agent's face, by its handle or its name", () => {
    render(
      <>
        <MentionChip item={{ kind: "agent", id: "a", name: "Writer", slug: "writer" }} />
        <MentionChip item={{ kind: "agent", id: "b", name: "Reviewer" }} />
      </>,
    );
    expect(screen.getAllByTestId("face").map((face) => face.textContent)).toEqual([
      "writer",
      "Reviewer",
    ]);
  });

  it("draws a capability in its own hue, by the icon of what it does", () => {
    const { container } = render(
      <>
        <MentionChip
          item={{
            kind: "capability",
            id: "web_research",
            name: "Web research",
            icon: "web_search",
          }}
        />
        <MentionChip item={{ kind: "capability", id: "unknown_cap", name: "Unknown" }} />
      </>,
    );
    const [known, unknown] = [...container.querySelectorAll("span.grid")] as HTMLElement[];
    expect(known!.style.background).toContain("oklch");
    expect(unknown!.getAttribute("style")).toBeNull();
    expect(container.querySelector(".lucide-wrench")).not.toBeNull();
  });

  it("names what it is for on hover", () => {
    render(<MentionChip item={{ kind: "mcp", id: "g", name: "GitHub", detail: "github_*" }} />);
    expect(screen.getByTitle("github_*")).toHaveTextContent("GitHub");
  });
});

describe("a mention in the text", () => {
  const NOTION: Mentionable = { kind: "mcp", id: "n", name: "Notion", detail: "notion_*" };

  it("shows a sent mention as its mark and name, where it was written", () => {
    const { container } = render(
      <p>
        <RichText text="ask @Notion please" mentions={[NOTION]} />
      </p>,
    );
    // The server's mark (its monogram, with no logo) and its name, in the sentence.
    expect(container.firstElementChild).toHaveTextContent(/^ask N?Notion please$/);
    expect(screen.getByTitle("notion_*")).toHaveTextContent("Notion");
  });
});

describe("an address in the text", () => {
  it("is a card with the site's mark, its host and its path once sent", () => {
    render(
      <p>
        <RichText
          text="see https://github.com/vstorm-co/agenticos and https://example.org/"
          mentions={[]}
        />
      </p>,
    );
    const [github, example] = screen.getAllByRole("link");
    expect(github).toHaveAttribute("href", "https://github.com/vstorm-co/agenticos");
    expect(github).toHaveTextContent("github.com/vstorm-co/agenticos");
    expect(github).toHaveAttribute("rel", "noopener noreferrer");
    // A site with no bundled mark asks for its own favicon, and shows a globe when it has none.
    const icon = example!.querySelector("img")!;
    expect(icon).toHaveAttribute("src", "https://example.org/favicon.ico");
    expect(icon).toHaveAttribute("referrerpolicy", "no-referrer");
    fireEvent.error(icon);
    expect(example!.querySelector("img")).toBeNull();
    expect(example!.querySelector(".lucide-globe")).not.toBeNull();
    expect(example).toHaveTextContent(/^example\.org$/);
  });
});

describe("a site's mark", () => {
  it("is a globe for an address that cannot be read", () => {
    const { container } = render(<LinkFavicon url="https://[not-a-host" />);
    expect(container.querySelector(".lucide-globe")).not.toBeNull();
  });
});
