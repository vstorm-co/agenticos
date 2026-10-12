import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { McpCatalogCheck, McpCatalogEntry } from "@/types/mcp";

import { CatalogCheck } from "./catalog-check";

function entry(check: Partial<McpCatalogCheck> | null, verified = true): McpCatalogEntry {
  return {
    key: "github",
    name: "GitHub",
    description: "",
    category: "development",
    auth: "oauth",
    url: "https://mcp.example.com",
    docs_url: null,
    token_hint: null,
    icon: null,
    verified,
    check:
      check === null
        ? null
        : {
            outcome: "sign_in",
            checked_at: "2026-10-12T17:50:00Z",
            tools: null,
            read_only_tools: null,
            ...check,
          },
  };
}

describe("what the catalog check found, on a server's card (#2103)", () => {
  it("says a server answered, and when", () => {
    render(<CatalogCheck entry={entry({})} />);

    expect(screen.getByText(/^Checked Oct 12$/)).toBeInTheDocument();
    expect(screen.getByTitle(/Checked Oct 12, 2026/)).toBeInTheDocument();
  });

  it("counts the tools it listed, and those that only read", () => {
    render(<CatalogCheck entry={entry({ outcome: "open", tools: 9, read_only_tools: 7 })} />);

    expect(screen.getByTitle(/9 tools, 7 read-only/)).toBeInTheDocument();
  });

  it("counts none read-only when the server marks none", () => {
    render(<CatalogCheck entry={entry({ outcome: "open", tools: 1, read_only_tools: null })} />);

    expect(screen.getByTitle(/1 tool, 0 read-only/)).toBeInTheDocument();
  });

  it("warns about a server that did not answer", () => {
    render(<CatalogCheck entry={entry({ outcome: "unreachable" }, false)} />);

    expect(screen.getByText(/^No answer Oct 12$/)).toBeInTheDocument();
    expect(screen.getByTitle(/Did not answer the catalog check/)).toBeInTheDocument();
  });

  it("says nothing of a server never checked, or with nothing to call", () => {
    const { container, rerender } = render(<CatalogCheck entry={entry(null)} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<CatalogCheck entry={entry({ outcome: "self_hosted" }, false)} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<CatalogCheck entry={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
