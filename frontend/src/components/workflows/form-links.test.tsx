import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FormLinks } from "./form-links";
const state = vi.hoisted(() => ({ url: null as string | null }));
vi.mock("@/hooks", () => ({ useWorkflowExposure: () => ({ exposure: { form_url: state.url } }) }));
vi.mock("./triggers/copyable-value", () => ({
  CopyableValue: ({ value }: { value: string }) => <span>{value}</span>,
}));
describe("FormLinks", () => {
  it("links an editor to the exact draft entry and explains publishing", () => {
    state.url = null;
    render(<FormLinks workflowId="w1" entryId="e1" saving={false} canTest />);
    expect(screen.getByRole("link", { name: "Test form" })).toHaveAttribute(
      "href",
      "/workflows/w1/form-preview?entry=e1",
    );
    expect(screen.getByText(/Publish the workflow/)).toBeVisible();
  });
  it("hides testing from readers and shows the published link", () => {
    state.url = "/f/example";
    render(<FormLinks workflowId="w1" entryId="e1" saving={false} canTest={false} />);
    expect(screen.queryByRole("link", { name: "Test form" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open published form" })).toHaveAttribute(
      "href",
      "/f/example",
    );
  });
  it("waits for draft saving before offering a test URL", () => {
    render(<FormLinks workflowId="w1" entryId="e1" saving canTest />);
    expect(screen.queryByRole("link", { name: "Test form" })).toBeNull();
  });
});
