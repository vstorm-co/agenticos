import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Beam } from "./beam";

describe("Beam", () => {
  it("renders what it wraps", () => {
    render(
      <Beam>
        <button>Publish</button>
      </Beam>,
    );

    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
  });

  it("keeps what it wraps mounted when it is not running", () => {
    // A beam that mounted on hover would remount the card under the mouse.
    render(
      <Beam active={false}>
        <button>Publish</button>
      </Beam>,
    );

    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
  });
});
