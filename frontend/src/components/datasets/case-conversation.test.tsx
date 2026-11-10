import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { CaseConversation } from "./case-conversation";

it("leads with the question and labelled reference, with earlier context available on demand", async () => {
  render(
    <CaseConversation
      content={{
        input: "**A literal question**",
        history: [
          { role: "user", content: "Earlier question" },
          { role: "assistant", content: "Earlier **answer**" },
        ],
        reference_answer:
          "**30 days**\n\n- Keep the receipt.\n\n![private image](https://example.com/private.png)",
      }}
    />,
  );
  expect(screen.getByText("**A literal question**")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Reference answer" })).toBeVisible();
  expect(await screen.findByText("30 days")).toHaveProperty("tagName", "STRONG");
  expect(screen.getByText("Keep the receipt.")).toBeVisible();
  expect(screen.queryByRole("img")).toBeNull();
  expect(screen.getByText("Earlier question")).not.toBeVisible();
  await userEvent.click(screen.getByText("2 earlier turns"));
  expect(screen.getByText("Earlier question")).toBeVisible();
  expect(await screen.findByText("answer")).toBeVisible();
  expect(screen.queryByText("You")).toBeNull();
});
