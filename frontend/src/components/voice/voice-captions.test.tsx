import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VoiceCaptions } from "./voice-captions";

describe("VoiceCaptions", () => {
  it("shows the words to sighted readers and announces whole sentences to screen readers", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        captions={[
          { turnId: "t1", part: 0, role: "user", text: "Weather in Warsaw?", final: true },
          { turnId: "t2", part: 0, role: "assistant", text: "It is eigh", final: false },
        ]}
      />,
    );
    const visible = screen.getByTestId("voice-captions-visible");
    expect(visible).toHaveAttribute("aria-hidden", "true");
    expect(visible).toHaveTextContent("It is eigh");
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent("You: Weather in Warsaw?");
    expect(live).not.toHaveTextContent("It is eigh");
  });

  it("names the agent when its line is finished", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        captions={[
          { turnId: "t2", part: 0, role: "assistant", text: "It is eight degrees.", final: true },
        ]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Support: It is eight degrees.");
  });

  it("announces nothing before a line is finished", () => {
    render(<VoiceCaptions agentName="Support" captions={[]} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows each part of one answer as a line of its own", () => {
    render(
      <VoiceCaptions
        agentName="Support"
        captions={[
          { turnId: "a1", part: 0, role: "assistant", text: "Let me check.", final: true },
          { turnId: "a1", part: 1, role: "assistant", text: "Eight degrees.", final: false },
        ]}
      />,
    );
    const lines = screen.getByTestId("voice-captions-visible").querySelectorAll("p");
    expect([...lines].map((line) => line.textContent)).toEqual(["Let me check.", "Eight degrees."]);
  });
});
