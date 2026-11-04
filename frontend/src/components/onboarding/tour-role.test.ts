import { describe, expect, it, vi } from "vitest";

import { appendRoleChoice } from "./tour-role";

describe("appendRoleChoice", () => {
  it("draws one button per role, with the account's own pressed", () => {
    const into = document.createElement("div");

    appendRoleChoice(into, "Sales", "What do you do?", ["Sales", "Finance"], vi.fn());

    expect(into.querySelector("p")?.textContent).toBe("What do you do?");
    const group = into.querySelector('[role="group"]');
    expect(group?.getAttribute("aria-label")).toBe("What do you do?");
    const pressed = [...into.querySelectorAll("button")].map((button) => [
      button.textContent,
      button.getAttribute("aria-pressed"),
    ]);
    expect(pressed).toEqual([
      ["Sales", "true"],
      ["Finance", "false"],
    ]);
  });

  it("chooses the role clicked, and moves the pressed state to it", () => {
    const into = document.createElement("div");
    const choose = vi.fn();
    appendRoleChoice(into, null, "What do you do?", ["Sales", "Finance"], choose);

    const [sales, finance] = into.querySelectorAll("button");
    finance!.click();

    expect(choose).toHaveBeenCalledWith("Finance");
    expect(finance!.getAttribute("aria-pressed")).toBe("true");
    expect(sales!.getAttribute("aria-pressed")).toBe("false");
  });
});
