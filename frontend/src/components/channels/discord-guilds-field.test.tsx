import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DiscordGuildsField, parseDiscordGuilds, validDiscordGuilds } from "./discord-guilds-field";

function Editor() {
  const [value, setValue] = useState("");
  return <DiscordGuildsField idPrefix="test" value={value} onChange={setValue} />;
}

describe("explicit Discord server approvals", () => {
  it("keeps separators while typing and explains the DM-only default", async () => {
    render(<Editor />);
    const input = screen.getByRole("textbox", { name: "Approved Discord server IDs" });
    expect(screen.getByText(/An empty list permits DMs only/)).toBeVisible();
    await userEvent.type(input, "100, 200");
    expect(input).toHaveValue("100, 200");
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    await userEvent.type(input, "{enter}300");
    expect(input).toHaveValue("100, 200\n300");
  });

  it("marks names as invalid and clears the error after an ID is supplied", async () => {
    render(<Editor />);
    const input = screen.getByRole("textbox", { name: "Approved Discord server IDs" });
    await userEvent.type(input, "my-server");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/Enter decimal server IDs/)).toBeVisible();
    await userEvent.clear(input);
    await userEvent.type(input, "100");
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Enter decimal server IDs/)).toBeNull();
  });

  it("normalizes pasted, repeated IDs and keeps an empty list empty", () => {
    expect(parseDiscordGuilds("200, 100 200\n300")).toEqual(["100", "200", "300"]);
    expect(parseDiscordGuilds(" , \n")).toEqual([]);
    expect(validDiscordGuilds("")).toBe(true);
    for (const value of ["0", "-1", "100abc", "123456789012345678901"]) {
      expect(validDiscordGuilds(value)).toBe(false);
    }
  });

  it("does not accept more servers than a single Gateway supports", () => {
    const ids = Array.from({ length: 2500 }, (_, i) => String(i + 1));
    expect(validDiscordGuilds(ids.join(" "))).toBe(true);
    expect(validDiscordGuilds([...ids, "2501"].join(" "))).toBe(false);
  });
});
