import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Brain } from "lucide-react";
import { expect, it, vi } from "vitest";
import { Switch } from "@/components/ui";
import { ServiceCard } from "./service-card";

it("exposes the exact service title as a heading and disclosure, with its switch outside the button", async () => {
  const change = vi.fn();
  render(
    <ServiceCard
      title="Memory"
      description="Configure model and budget"
      icon={Brain}
      collapsible
      action={<Switch aria-label="Enable memory" checked={false} onCheckedChange={change} />}
    >
      <label>
        Budget
        <input defaultValue="3" />
      </label>
    </ServiceCard>,
  );
  const heading = screen.getByRole("button", { name: "Memory" });
  expect(screen.getByRole("heading", { name: "Memory" })).toContainElement(heading);
  expect(heading).not.toContainElement(screen.getByRole("switch"));
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("switch"));
  expect(change).toHaveBeenCalledWith(true);
  expect(heading).toHaveAttribute("aria-expanded", "false");
  heading.focus();
  await userEvent.keyboard("{Enter}");
  const budget = screen.getByRole("textbox", { name: "Budget" });
  await userEvent.clear(budget);
  await userEvent.type(budget, "8");
  heading.focus();
  await userEvent.keyboard(" ");
  expect(heading).toHaveAttribute("aria-expanded", "false");
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("textbox", { name: "Budget" })).toHaveValue("8");
});

it("supports controlled disclosures without letting its own state override the parent", async () => {
  const change = vi.fn();
  const view = render(
    <ServiceCard
      title="Voice"
      description="Audio"
      icon={Brain}
      action={<span>Enabled</span>}
      collapsible
      open={false}
      onOpenChange={change}
    >
      <button>Save</button>
    </ServiceCard>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Voice" }));
  expect(change).toHaveBeenCalledWith(true);
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  view.rerender(
    <ServiceCard
      title="Voice"
      description="Audio"
      icon={Brain}
      action={<span>Enabled</span>}
      collapsible
      open
      onOpenChange={change}
    >
      <button>Save</button>
    </ServiceCard>,
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeVisible();
});

it("opens when a settings deep link arrives without discarding its draft", () => {
  const view = render(
    <ServiceCard title="Voice" description="Audio" icon={Brain} action={null} collapsible>
      <input aria-label="Model" defaultValue="saved" />
    </ServiceCard>,
  );
  view.rerender(
    <ServiceCard
      title="Voice"
      description="Audio"
      icon={Brain}
      action={null}
      collapsible
      defaultOpen
    >
      <input aria-label="Model" defaultValue="saved" />
    </ServiceCard>,
  );
  expect(screen.getByRole("textbox", { name: "Model" })).toHaveValue("saved");
});

it("keeps noncollapsible content visible and does not offer an empty disclosure", () => {
  render(
    <>
      <ServiceCard title="Open form" description="Visible" icon={Brain} action={null}>
        <input aria-label="Provider" />
      </ServiceCard>
      <ServiceCard
        title="Disabled welcome"
        description="Enable it first"
        icon={Brain}
        action={null}
        collapsible
      />
    </>,
  );
  expect(screen.getByRole("textbox", { name: "Provider" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Open form" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Disabled welcome" })).not.toBeInTheDocument();
});
