import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SandboxPreparingNotice } from "./sandbox-preparing-notice";

describe("SandboxPreparingNotice", () => {
  it("says why nothing is happening yet, as a live status", () => {
    // Minutes with no token and no tool step read as a broken chat; a reload then
    // cancels the turn that was about to start (#2222).
    render(<SandboxPreparingNotice />);

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(/Preparing the sandbox/);
  });
});
