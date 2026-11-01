import { renderToString } from "react-dom/server";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { CatalogSection } from "./catalog-section";

beforeEach(() => window.localStorage.clear());

describe("CatalogSection", () => {
  it("folds and unfolds, remembering the last choice where it has a key", async () => {
    render(
      <CatalogSection title="Agents (2)" defaultOpen storageKey="band">
        <p>cards</p>
      </CatalogSection>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Agents (2)" }));
    expect(screen.queryByText("cards")).toBeNull();
    expect(window.localStorage.getItem("band")).toBe("closed");
    await userEvent.click(screen.getByRole("button", { name: "Agents (2)" }));
    expect(screen.getByText("cards")).toBeInTheDocument();
    expect(window.localStorage.getItem("band")).toBe("open");
  });

  it("remembers nothing without a key", async () => {
    render(
      <CatalogSection title="Agents (2)" defaultOpen={false}>
        <p>cards</p>
      </CatalogSection>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Agents (2)" }));
    expect(screen.getByText("cards")).toBeInTheDocument();
    expect(window.localStorage.length).toBe(0);
  });

  it("renders the default on the server, which has no storage to read", () => {
    window.localStorage.setItem("band", "closed");

    const html = renderToString(
      <CatalogSection title="Agents (2)" defaultOpen storageKey="band">
        <p>cards</p>
      </CatalogSection>,
    );

    expect(html).toContain("cards");
  });
});
