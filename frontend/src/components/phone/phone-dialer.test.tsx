import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PhoneDialer } from "./phone-dialer";
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "voice",
        name: "Voice assistant",
        can_run: true,
        status: "published",
        current_version_id: "version",
        workflow_id: null,
      },
      {
        id: "draft",
        name: "Draft assistant",
        can_run: true,
        status: "draft",
        current_version_id: null,
        workflow_id: null,
      },
      {
        id: "workflow",
        name: "Workflow assistant",
        can_run: true,
        status: "published",
        current_version_id: "version",
        workflow_id: "workflow",
      },
      {
        id: "denied",
        name: "Private assistant",
        can_run: false,
        status: "published",
        current_version_id: "version",
        workflow_id: null,
      },
    ],
  }),
}));
it("queues an explicit report to an endpoint with a stable retry key", async () => {
  const call = vi.fn();
  render(
    <PhoneDialer
      endpoints={[{ id: "route", label: "Work phone" }]}
      pending={false}
      onCall={call}
    />,
  );
  expect(screen.getByRole("button", { name: "Queue call to me" })).toBeDisabled();
  await userEvent.click(screen.getByRole("combobox", { name: "Telephone route" }));
  await userEvent.click(screen.getByRole("option", { name: "Work phone" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Read a spoken report" }));
  await userEvent.type(
    screen.getByRole("textbox", { name: "Report to read" }),
    "The review is ready.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Queue call to me" }));
  await userEvent.click(screen.getByRole("button", { name: "Queue call to me" }));
  expect(call.mock.calls[0]?.[0]).toEqual(
    expect.objectContaining({
      endpoint_id: "route",
      mode: "report",
      report: "The review is ready.",
      agent_id: null,
    }),
  );
  expect(call.mock.calls[0]?.[0].request_key).toBe(call.mock.calls[1]?.[0].request_key);
});

it("selects a runnable published agent for a conversation and sends no report text", async () => {
  const call = vi.fn();
  render(
    <PhoneDialer
      endpoints={[{ id: "route", label: "Work phone" }]}
      pending={false}
      onCall={call}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Telephone route" }));
  await userEvent.click(screen.getByRole("option", { name: "Work phone" }));
  await userEvent.click(screen.getByRole("combobox", { name: "Voice agent" }));
  expect(screen.queryByRole("option", { name: "Draft assistant" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Workflow assistant" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "Private assistant" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Voice assistant" }));
  await userEvent.click(screen.getByRole("button", { name: "Queue call to me" }));
  expect(call).toHaveBeenCalledWith(
    expect.objectContaining({
      endpoint_id: "route",
      agent_id: "voice",
      mode: "conversation",
      report: null,
    }),
  );
});
