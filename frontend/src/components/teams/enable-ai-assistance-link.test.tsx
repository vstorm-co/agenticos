import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AI_ASSISTANCE_ANCHOR, EnableAiAssistanceLink } from "./enable-ai-assistance-link";

const pointAt = vi.hoisted(() => vi.fn().mockResolvedValue(true));
vi.mock("@/lib/assistant-highlight", () => ({ pointAt }));

describe("EnableAiAssistanceLink", () => {
  it("opens the organization page on the switch and points at it", async () => {
    render(<EnableAiAssistanceLink orgId="o1">Enable</EnableAiAssistanceLink>);

    const link = screen.getByRole("link", { name: "Enable" });
    expect(link).toHaveAttribute("href", `/orgs/o1/members?tab=governance#${AI_ASSISTANCE_ANCHOR}`);
    await userEvent.click(link);
    expect(pointAt).toHaveBeenCalledWith(AI_ASSISTANCE_ANCHOR);
  });
});
