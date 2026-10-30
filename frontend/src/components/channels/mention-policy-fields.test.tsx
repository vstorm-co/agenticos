import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MentionPolicyFields } from "./mention-policy-fields";
import type { ChannelPlatform } from "@/types/channels";

describe("group mention participation", () => {
  it.each<ChannelPlatform>(["mattermost", "slack", "teams", "telegram"])(
    "starts disabled and lets an operator enable %s broadcasts",
    async (platform) => {
      const onChange = vi.fn();
      render(
        <MentionPolicyFields
          idPrefix="b"
          platform={platform}
          enabled={false}
          onChange={onChange}
        />,
      );
      const toggle = screen.getByRole("switch", { name: "Respond to group mentions" });
      expect(toggle).not.toBeChecked();
      await userEvent.click(toggle);
      expect(onChange).toHaveBeenCalledWith(true);
    },
  );

  it("explains Teams installation consent", () => {
    render(<MentionPolicyFields idPrefix="b" platform="teams" enabled onChange={vi.fn()} />);
    expect(screen.getByText(/owner must consent/)).toBeInTheDocument();
  });

  it("explains Telegram delivery and literal aliases", () => {
    render(<MentionPolicyFields idPrefix="b" platform="telegram" enabled onChange={vi.fn()} />);
    expect(screen.getByText(/privacy mode in BotFather/)).toBeInTheDocument();
  });
});
