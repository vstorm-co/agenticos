import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SandboxConnectionPicker } from "./sandbox-connection-picker";

const connections = vi.fn();
const mayView = vi.fn(() => true);

vi.mock("@/hooks", () => ({
  useSandboxConnections: (enabled: boolean) => connections(enabled),
  usePermissions: () => ({ can: () => mayView() }),
}));

const HOSTS = [
  { id: "h1", name: "Build host", kind: "docker", is_default: true, is_active: true },
  { id: "h2", name: "Old host", kind: "docker", is_default: false, is_active: false },
  { id: "d1", name: "Daytona", kind: "daytona", is_default: false, is_active: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  mayView.mockReturnValue(true);
  connections.mockReturnValue({ connections: HOSTS, isLoading: false });
});

describe("SandboxConnectionPicker", () => {
  it("offers the default and every sandboxd host, never a Daytona one", async () => {
    const onChange = vi.fn();
    render(<SandboxConnectionPicker value={null} onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Sandbox host" }));
    expect(screen.getByRole("option", { name: /Build host.*default/ })).toBeTruthy();
    expect(screen.getByRole("option", { name: /Old host.*off/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Daytona/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /Old host/ }));
    expect(onChange).toHaveBeenCalledWith("h2");
    expect(connections).toHaveBeenCalledWith(true);
  });

  it("is called what its field is called, when the field names itself", () => {
    render(<SandboxConnectionPicker value={null} onChange={vi.fn()} label="Build host" />);
    expect(screen.getByRole("combobox", { name: "Build host" })).toBeTruthy();
  });

  it("goes back to the default, which the step stores as no host at all", async () => {
    const onChange = vi.fn();
    render(<SandboxConnectionPicker value="h1" onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Sandbox host" }));
    await userEvent.click(screen.getByRole("option", { name: "The organization's default host" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says where to connect a host, and names one that is gone", () => {
    connections.mockReturnValue({ connections: [], isLoading: false });
    const { rerender } = render(<SandboxConnectionPicker value={null} onChange={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Connect one" }).getAttribute("href")).toBe(
      "/sandboxes",
    );

    rerender(<SandboxConnectionPicker value="gone" onChange={vi.fn()} error="Pick a host" />);
    expect(screen.getByText(/The host this step names is gone/)).toBeTruthy();
    expect(screen.getByText("Pick a host")).toBeTruthy();
  });

  it("tells a member without connections:view why, and asks for no list", () => {
    mayView.mockReturnValue(false);
    connections.mockReturnValue({ connections: [], isLoading: false });
    render(<SandboxConnectionPicker value={null} onChange={vi.fn()} />);

    expect(screen.getByText(/needs connections:view/)).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(connections).toHaveBeenCalledWith(false);
  });
});
