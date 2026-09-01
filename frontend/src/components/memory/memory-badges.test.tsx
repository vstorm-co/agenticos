import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { OriginBadge, PartitionBadge } from "./memory-badges";

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

describe("PartitionBadge", () => {
  it("labels the shared store rather than showing an empty key", () => {
    render(<PartitionBadge scopeKey={null} />);
    expect(screen.getByText("Shared")).toBeInTheDocument();
  });

  it("shows the raw partition key for a private store", () => {
    render(<PartitionBadge scopeKey="user:0f3a91b2" />);
    expect(screen.getByText("user:0f3a91b2")).toBeInTheDocument();
  });
});
