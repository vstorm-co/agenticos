import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HttpAuthField } from "./http-auth-field";

const picker = vi.hoisted(() => vi.fn());
vi.mock("@/components/workflows/pickers/secret-picker", () => ({
  SecretPicker: (props: { disabled?: boolean; onChange: (id: string) => void }) => {
    picker(props);
    return (
      <button disabled={props.disabled} onClick={() => props.onChange("vault-id")}>
        Choose saved credential
      </button>
    );
  },
}));

function mount(
  initial: unknown = {},
  url: unknown = "https://api.example.com/v1/items?key=ignored",
) {
  const changed = vi.fn();
  function Example() {
    const [value, setValue] = useState<unknown>(initial);
    return (
      <HttpAuthField
        value={value}
        url={url}
        onChange={(next) => {
          changed(next);
          setValue(next);
        }}
      />
    );
  }
  render(<Example />);
  return changed;
}
async function choose(name: string) {
  await userEvent.click(screen.getByRole("combobox", { name: "Authentication method" }));
  await userEvent.click(screen.getByRole("option", { name }));
}

describe("HTTP authentication", () => {
  it("starts without credentials and offers only fields needed by the chosen method", async () => {
    const changed = mount();
    expect(screen.queryByRole("button", { name: "Choose saved credential" })).toBeNull();
    await choose("API key in a header");
    expect(screen.getByLabelText("Header name")).toHaveValue("X-API-Key");
    expect(screen.queryByLabelText("Query parameter name")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Choose saved credential" }));
    expect(changed).toHaveBeenLastCalledWith({
      kind: "header",
      header_name: "X-API-Key",
      secret_id: "vault-id",
    });
    expect(picker).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "http_credential",
        initialValue: { origins: ["https://api.example.com"] },
      }),
    );
    await choose("API key in the URL");
    expect(screen.getByLabelText("Query parameter name")).toHaveValue("api_key");
    expect(changed).toHaveBeenLastCalledWith({
      kind: "query",
      query_name: "api_key",
      secret_id: "vault-id",
    });
    expect(screen.queryByLabelText("Header name")).toBeNull();
    await choose("No authentication");
    expect(changed).toHaveBeenLastCalledWith({ kind: "none" });
  });
  it("keeps a saved reference while switching to Bearer or Basic Auth", async () => {
    const changed = mount({
      kind: "header",
      secret_id: "saved",
      header_name: "Authorization",
      header_prefix: "Token",
    });
    expect(screen.getByLabelText("Header prefix (optional)")).toHaveValue("Token");
    await choose("Bearer token");
    expect(changed).toHaveBeenLastCalledWith({ kind: "bearer", secret_id: "saved" });
    expect(screen.queryByLabelText("Header prefix (optional)")).toBeNull();
    await choose("Basic Auth");
    expect(changed).toHaveBeenLastCalledWith({ kind: "basic", secret_id: "saved" });
    expect(screen.getByText(/Basic Auth username and password/)).toBeInTheDocument();
  });
  it("leaves bound URLs without a guessed origin and respects read-only state and field errors", () => {
    render(
      <HttpAuthField
        value={{ kind: "header", secret_id: "saved" }}
        url={{ node_id: "previous" }}
        disabled
        errors={new Map([["auth.secret_id", "Access revoked"]])}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Authentication method" })).toBeDisabled();
    expect(screen.getByLabelText("Header name")).toBeDisabled();
    expect(picker).toHaveBeenLastCalledWith(
      expect.objectContaining({ initialValue: undefined, disabled: true, error: "Access revoked" }),
    );
  });
});

it("edits custom header and query conventions while keeping only the vault reference", async () => {
  const changed = mount({ kind: "header", secret_id: "saved", header_name: "X-Key" });
  await userEvent.clear(screen.getByLabelText("Header name"));
  await userEvent.type(screen.getByLabelText("Header name"), "Authorization");
  await userEvent.type(screen.getByLabelText("Header prefix (optional)"), "Token");
  expect(changed).toHaveBeenLastCalledWith({
    kind: "header",
    secret_id: "saved",
    header_name: "Authorization",
    header_prefix: "Token",
  });
  await userEvent.clear(screen.getByLabelText("Header prefix (optional)"));
  expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ header_prefix: undefined }));
  await choose("API key in the URL");
  await userEvent.clear(screen.getByLabelText("Query parameter name"));
  await userEvent.type(screen.getByLabelText("Query parameter name"), "access_token");
  expect(changed).toHaveBeenLastCalledWith({
    kind: "query",
    secret_id: "saved",
    query_name: "access_token",
  });
});

it.each(["not a URL", "ftp://files.example.com"])(
  "does not suggest a credential origin for %s",
  (url) => {
    mount({ kind: "bearer", secret_id: "saved" }, url);
    expect(picker).toHaveBeenLastCalledWith(expect.objectContaining({ initialValue: undefined }));
  },
);

it("shows server and local field errors beside the corresponding controls", () => {
  const { rerender } = render(
    <HttpAuthField
      value={{ kind: "header" }}
      url=""
      errors={
        new Map([
          ["auth", "Check authentication"],
          ["auth/header_name", "Choose a header"],
          ["auth.header_prefix", "Invalid prefix"],
        ])
      }
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText("Check authentication")).toBeVisible();
  expect(screen.getByText("Choose a header")).toBeVisible();
  expect(screen.getByText("Invalid prefix")).toBeVisible();
  rerender(
    <HttpAuthField
      value={{ kind: "query" }}
      url=""
      errors={new Map([["auth/query_name", "Choose a parameter"]])}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText("Choose a parameter")).toBeVisible();
});
