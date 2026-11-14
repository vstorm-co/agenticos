import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { useMotionStore } from "@/stores/motion-store";
import { SetupIndicator } from "./setup-indicator";

it("explains the missing configuration on keyboard focus without changing it", async () => {
  render(<SetupIndicator hints={["voiceModel"]} />);
  const indicator = screen.getByRole("button", { name: /Voice has no default/ });
  expect(indicator).toHaveAttribute("tabindex", "0");
  await userEvent.tab();
  expect(indicator).toHaveFocus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent("Workspace → Voice");
});
it("renders nothing after configuration is complete", () => {
  const { container } = render(<SetupIndicator hints={[]} />);
  expect(container).toBeEmptyDOMElement();
});
it("lets a tab describe its marker without adding a second tab stop", () => {
  const { container } = render(<SetupIndicator hints={["memoryModel"]} focusable={false} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  expect(container.querySelector(".bg-amber-500")).not.toBeNull();
});

it("opens its explanation on tap without requiring hover", async () => {
  render(<SetupIndicator hints={["memoryModel"]} />);
  await userEvent.click(screen.getByRole("button", { name: /Memory maintenance/ }));
  expect(await screen.findByRole("dialog")).toHaveTextContent(
    "AI & services → Background services",
  );
});

it("stops pulsing when the app's Reduce setting is selected, while retaining the hint", () => {
  const saved = useMotionStore.getState().motion;
  try {
    useMotionStore.setState({ motion: "full" });
    const { container } = render(<SetupIndicator hints={["voiceModel"]} />);
    expect(container.querySelector(".animate-ping")).not.toBeNull();
    act(() => useMotionStore.getState().setMotion("reduce"));
    expect(container.querySelector(".animate-ping")).toBeNull();
    expect(screen.getByRole("button", { name: /Voice has no default/ })).toBeVisible();
  } finally {
    act(() => useMotionStore.setState({ motion: saved }));
  }
});
