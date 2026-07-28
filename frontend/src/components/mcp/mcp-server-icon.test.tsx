import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { McpServerIcon } from "./mcp-server-icon";

describe("McpServerIcon", () => {
  it("renders the brand mark the catalog names", () => {
    const { container } = render(<McpServerIcon icon="sentry" name="Sentry" />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("draws a different mark per service, because that is the only reason to have marks", () => {
    // The regression this page had was one generic icon on every row, which is
    // indistinguishable from no icon at all when you are scanning for Sentry.
    const github = render(<McpServerIcon icon="github" name="GitHub" />);
    const postgres = render(<McpServerIcon icon="postgres" name="PostgreSQL" />);

    const path = (result: { container: HTMLElement }) =>
      result.container.querySelector("path")?.getAttribute("d");

    expect(path(github)).toBeTruthy();
    expect(path(postgres)).toBeTruthy();
    expect(path(github)).not.toBe(path(postgres));
  });

  it("renders a monogram for a server nobody curated, rather than nothing", () => {
    // A connection somebody added by URL has no catalog key and no mark
    // anywhere. This is the normal case, not the error case: a blank gap or a
    // broken image would read as a logo that failed to load.
    const { container } = render(<McpServerIcon icon={null} name="internal-crm" />);

    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toBe("i");
  });

  it("takes the monogram from the name, never from the icon", () => {
    // An uncurated row has no icon at all, and its key is a uuid. A monogram
    // reading "3" is the bug, not the fallback.
    const { container } = render(
      <McpServerIcon icon={null} name="acme-billing-abcdef01-2345-6789" />,
    );
    expect(container.textContent).toBe("a");
  });

  it("falls back for a mark no icon set carries", () => {
    // The backend catalog is hand-maintained and can name a brand this icon set
    // does not draw. That has to degrade to the monogram, not to a gap.
    const { container } = render(<McpServerIcon icon="some-new-server" name="Newcomer" />);

    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toBe("N");
  });

  it("stays out of the accessibility tree either way", () => {
    // Every card prints the server's name beside the mark, and the card itself
    // is labelled with it. A mark that named itself would be said twice.
    const { container: known } = render(<McpServerIcon icon="notion" name="Notion" />);
    const { container: unknown } = render(<McpServerIcon icon={null} name="internal-crm" />);

    expect(known.firstElementChild).toHaveAttribute("aria-hidden");
    expect(unknown.firstElementChild).toHaveAttribute("aria-hidden");
  });

  it("fetches nothing to draw a mark", () => {
    // The point of compiling the glyphs in, and the reason the favicon-service
    // fallback this replaces was not acceptable: a self-hosted deployment must
    // not make an outbound request, keyed on a brand domain, to render a logo.
    for (const key of ["github", "linear", "notion", "sentry", "postgres", "mcp", null]) {
      const { container } = render(<McpServerIcon icon={key} name="Whatever" />);
      expect(container.querySelector("img")).toBeNull();
      expect(container.querySelector("[src]")).toBeNull();
    }
  });
});
