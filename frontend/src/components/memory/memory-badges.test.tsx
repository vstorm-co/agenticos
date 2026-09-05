import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { OriginBadge, OwnerBadge } from "./memory-badges";

describe("OriginBadge", () => {
  it("names an operator file, which is the trusted one", () => {
    render(<OriginBadge origin="operator" />);
    expect(screen.getByText("Operator")).toBeInTheDocument();
  });

  it("names an agent file, which is the untrusted one", () => {
    render(<OriginBadge origin="agent" />);
    expect(screen.getByText("Agent")).toBeInTheDocument();
  });
});

describe("OwnerBadge", () => {
  it("labels the organisation's store rather than showing an empty key", () => {
    render(<OwnerBadge ownerKey={null} />);
    expect(screen.getByText("Organisation")).toBeInTheDocument();
  });

  it("shows the raw partition key for a private store", () => {
    render(<OwnerBadge ownerKey="person:0f3a91b2" />);
    expect(screen.getByText("person:0f3a91b2")).toBeInTheDocument();
  });

  it("shows the resolved name and keeps the raw key on hover", () => {
    render(<OwnerBadge ownerKey="person:0f3a91b2" ownerLabel="dana@acme.example" />);
    const badge = screen.getByText("dana@acme.example");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", "person:0f3a91b2");
  });

  it("falls back to the raw key when the label did not resolve", () => {
    render(<OwnerBadge ownerKey="person:0f3a91b2" ownerLabel={null} />);
    expect(screen.getByText("person:0f3a91b2")).toBeInTheDocument();
  });
});
