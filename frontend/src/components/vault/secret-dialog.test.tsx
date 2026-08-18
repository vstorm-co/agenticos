import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { render as baseRender, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";

import { AddSecretDialog, RotateSecretDialog } from "./secret-dialog";
import { ApiError, parseErrorMessage } from "@/lib/api-error";
import type { Secret, SecretKindInfo } from "@/types/secrets";

/** What a deployment offers, as three families with something in each. */
const PURPOSES = {
  items: [
    {
      id: "openai",
      label: "OpenAI",
      category: "model_provider",
      kind: "api_key",
      help_url: null,
      description: "Run models on OpenAI.",
    },
    {
      id: "tavily",
      label: "Tavily",
      category: "search",
      kind: "api_key",
      help_url: "https://tavily.com",
      description: "Web search summarised for a model to read.",
    },
    {
      id: "custom",
      label: "Something else",
      category: "other",
      kind: "api_key",
      help_url: null,
      description: "A key for a service this deployment does not know about yet.",
    },
    {
      id: "github_oauth_app",
      label: "GitHub OAuth App",
      category: "other",
      kind: "github_oauth_app",
      help_url: "https://github.com/settings/developers",
      description: "A GitHub OAuth App's client id and secret.",
    },
  ],
  total: 4,
};

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      get: vi
        .fn()
        .mockImplementation(async (path: string) =>
          path === "/secrets/purposes" ? PURPOSES : { items: [], total: 0 },
        ),
    },
  };
});

/** The dialog fetches the purpose catalog, so it needs a query client. */
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return baseRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API_KEY: SecretKindInfo = {
  kind: "api_key",
  name: "API key",
  description: "A single token, sent as-is to the service.",
  json_schema: {
    type: "object",
    properties: {
      kind: { const: "api_key", type: "string" },
      api_key: { type: "string", format: "password", title: "Api Key" },
    },
    required: ["api_key"],
  },
};

const GCP: SecretKindInfo = {
  kind: "gcp_service_account",
  name: "Google service account",
  description: "The service account JSON downloaded from the Google Cloud console.",
  json_schema: {
    type: "object",
    properties: {
      kind: { const: "gcp_service_account", type: "string" },
      service_account_json: {
        type: "string",
        format: "password",
        title: "Service Account Json",
      },
      location: { anyOf: [{ type: "string" }, { type: "null" }], title: "Location" },
    },
    required: ["service_account_json"],
  },
};

const GITHUB_OAUTH_APP: SecretKindInfo = {
  kind: "github_oauth_app",
  name: "GitHub OAuth App",
  description: "A GitHub OAuth App's client id and secret.",
  json_schema: {
    type: "object",
    properties: {
      kind: { const: "github_oauth_app", type: "string" },
      client_id: { type: "string", title: "Client ID" },
      client_secret: { type: "string", format: "password", title: "Client secret" },
    },
    required: ["client_id", "client_secret"],
  },
};

const KINDS = [API_KEY, GCP, GITHUB_OAUTH_APP];

const STORED: Secret = {
  id: "s1",
  name: "Zendesk API token",
  description: "Used by the ticketing capability.",
  kind: "api_key",
  hint: "4Q2X",
};

describe("AddSecretDialog", () => {
  function open(onSubmit = vi.fn().mockResolvedValue({})) {
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );
    return onSubmit;
  }

  const store = () => screen.getByRole("button", { name: "Store secret" });

  it("generates the value fields from the kind's published schema", () => {
    open();
    expect(screen.getByLabelText(/Api Key/, { selector: "input" })).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("refuses to submit without a name", async () => {
    // The name is how a capability binding picks this secret in the Builder.
    // An unnamed one could be stored and never found again. Cleared first,
    // because the field carries the chosen service's name until somebody
    // replaces it - blank is now a state you have to ask for.
    open();
    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText(/Api Key/, { selector: "input" }), "sk-x");
    expect(store()).toBeDisabled();
  });

  it("refuses to submit without a value", async () => {
    open();
    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Zendesk");
    expect(store()).toBeDisabled();
  });

  it("sends the name, the description and a payload carrying its own kind", async () => {
    const onSubmit = open();

    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Zendesk");
    await userEvent.type(screen.getByLabelText(/Note/), "Ticketing");
    await userEvent.type(screen.getByLabelText(/Api Key/, { selector: "input" }), "sk-x");
    await userEvent.click(store());

    expect(onSubmit).toHaveBeenCalledWith({
      name: "Zendesk",
      description: "Ticketing",
      value: { kind: "api_key", api_key: "sk-x" },
      // What it is for, and how far it reaches - both sent explicitly, so the
      // server never has to guess what an older client meant. The form opens
      // on the first model provider because that is what most keys are; the
      // two questions above it are what change it.
      purpose: "openai",
      visibility: "org",
    });
  });

  it("sends no description rather than an empty one", async () => {
    // `null` is "nobody said", which is what the backend stores. An empty
    // string would render as a blank line under every such row.
    const onSubmit = open();
    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Zendesk");
    await userEvent.type(screen.getByLabelText(/Api Key/, { selector: "input" }), "sk-x");
    await userEvent.click(store());

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ description: null }));
  });

  it("puts a name already in use under the name, not in a toast", async () => {
    // The refusal people actually hit here, because the obvious name for a
    // secret is the service it belongs to and somebody already used it. It is
    // fixable in the field they are looking at.
    const body = {
      error: {
        code: "ALREADY_EXISTS",
        message: "A secret with this name already exists",
        details: {},
      },
    };
    open(vi.fn().mockRejectedValue(new ApiError(409, parseErrorMessage(body), body)));

    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Zendesk");
    await userEvent.type(screen.getByLabelText(/Api Key/, { selector: "input" }), "sk-x");
    await userEvent.click(store());

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });

  it("wires every label to the control it names", () => {
    const { container } = render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={vi.fn()}
        isPending={false}
      />,
    );
    const labels = Array.from(container.ownerDocument.querySelectorAll<HTMLLabelElement>("label"));

    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label.htmlFor, `"${label.textContent}" names no control`).not.toBe("");
      expect(document.getElementById(label.htmlFor)).not.toBeNull();
    }
  });
});

describe("RotateSecretDialog", () => {
  function open(onSubmit = vi.fn().mockResolvedValue({}), secret: Secret | null = STORED) {
    render(
      <RotateSecretDialog
        secret={secret}
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );
    return onSubmit;
  }

  it("stays shut when nothing is being rotated", () => {
    open(vi.fn(), null);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says the old value is gone and the id is not", () => {
    // Both halves matter: somebody who has not written the old key down
    // elsewhere needs the warning, and somebody worried about their agents
    // needs the reassurance.
    open();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/the old one is gone/i);
    expect(dialog).toHaveTextContent(/keeps working/i);
  });

  it("names the value being replaced by the four characters it ends with", () => {
    open();
    expect(screen.getByText(/····4Q2X/)).toBeInTheDocument();
  });

  it("asks only for a new value, because the kind cannot change", () => {
    // The server refuses a change of shape with a 400: a capability bound to an
    // api_key cannot be handed an AWS key pair by whoever rotated it.
    open();
    expect(screen.getByLabelText(/Api Key/, { selector: "input" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Kind")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("rotates against the id, keeping the kind the secret already has", async () => {
    const onSubmit = open();

    await userEvent.type(screen.getByLabelText(/Api Key/, { selector: "input" }), "sk-new");
    await userEvent.click(screen.getByRole("button", { name: "Rotate" }));

    expect(onSubmit).toHaveBeenCalledWith({
      id: "s1",
      value: { kind: "api_key", api_key: "sk-new" },
    });
  });

  it("refuses an empty rotation", async () => {
    // Saving nothing would be a request the server rejects, and on a control
    // labelled "Rotate" it reads as having replaced the key with nothing.
    open();
    expect(screen.getByRole("button", { name: "Rotate" })).toBeDisabled();
  });

  it("puts a refusal about the value beside the field it was pasted into", async () => {
    // The refusal this exists for: a truncated paste or the wrong kind of
    // Google credential is otherwise indistinguishable from a working one until
    // a run fails hours later with nothing pointing back at the paste. The
    // server names the field under `value.`, and it has to reach the input the
    // form calls by its leaf name.
    const vertex: Secret = {
      id: "s2",
      name: "Vertex",
      description: null,
      kind: "gcp_service_account",
      hint: "com",
    };
    const body = {
      error: {
        code: "VALIDATION_ERROR",
        message: "Validation failed",
        details: {
          fields: [
            {
              field: "value.service_account_json",
              message: "This is not a service account key - its 'type' is not service_account",
            },
          ],
        },
      },
    };
    open(vi.fn().mockRejectedValue(new ApiError(422, parseErrorMessage(body), body)), vertex);

    await userEvent.type(
      screen.getByLabelText(/Service Account Json/, { selector: "input" }),
      "{{}",
    );
    await userEvent.click(screen.getByRole("button", { name: "Rotate" }));

    expect(await screen.findByText(/not a service account key/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Service Account Json/, { selector: "input" })).toBeInvalid();
  });
});

describe("AddSecretDialog · choosing what a key is for", () => {
  it("asks for the family first, and narrows the list to it", async () => {
    // Thirty-one services in one select is a scroll. Three answers rule out
    // most of it: picking "Web search" turns the second question into a choice
    // between three, not a hunt through every model provider.
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={vi.fn()}
        isPending={false}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Web search/ }));
    await userEvent.click(screen.getByLabelText("Which one"));

    expect(screen.getByRole("option", { name: "Tavily" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "OpenAI" })).toBeNull();
  });

  it("stores what was chosen, not what the form opened on", async () => {
    const onSubmit = vi.fn();
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Web search/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Tavily prod");
    await userEvent.type(screen.getByLabelText(/API key/i, { selector: "input" }), "tvly-abc");
    await userEvent.click(screen.getByRole("button", { name: "Store secret" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ purpose: "tavily" }));
  });

  it("only asks which shape the credential is for a service it does not know", async () => {
    // Every named service declares its own shape. Asking twice is asking
    // somebody to disagree with the server, which then refuses the pair.
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={vi.fn()}
        isPending={false}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Model provider/ }));
    expect(screen.queryByLabelText("Kind")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));
    expect(screen.getByLabelText("Kind")).toBeInTheDocument();
  });

  it("stores a GitHub OAuth App as a client id and a masked secret", async () => {
    // A named service carries its own shape, so no Kind picker appears: choosing
    // it renders the two fields the kind declares - the public client id as text
    // and the client secret masked.
    const onSubmit = vi.fn().mockResolvedValue({});
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: /Something else/ }));
    await userEvent.click(screen.getByLabelText("Service"));
    await userEvent.click(screen.getByRole("option", { name: /GitHub OAuth App/ }));

    expect(screen.queryByLabelText("Kind")).toBeNull();
    expect(screen.getByLabelText(/Client ID/, { selector: "input" })).toHaveValue("");
    expect(screen.getByLabelText(/Client secret/, { selector: "input" })).toHaveAttribute(
      "type",
      "password",
    );

    await userEvent.type(
      screen.getByLabelText(/Client ID/, { selector: "input" }),
      "Iv1.0123456789abcdef",
    );
    await userEvent.type(
      screen.getByLabelText(/Client secret/, { selector: "input" }),
      "ghs-live-4242",
    );
    await userEvent.click(screen.getByRole("button", { name: "Store secret" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        value: {
          kind: "github_oauth_app",
          client_id: "Iv1.0123456789abcdef",
          client_secret: "ghs-live-4242",
        },
        purpose: "github_oauth_app",
      }),
    );
  });
});

describe("AddSecretDialog · the name that follows the service", () => {
  const open = () =>
    render(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={KINDS}
        onSubmit={vi.fn()}
        isPending={false}
      />,
    );

  it("renames along with the service while the name is still a suggestion", async () => {
    // Switching provider used to leave the field reading "OpenAI" on an
    // Anthropic key - and this is a list people scan by name.
    open();
    expect(await screen.findByDisplayValue("OpenAI")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Web search/ }));

    expect(screen.getByLabelText("Name")).toHaveValue("Tavily");
  });

  it("never overwrites a name somebody typed", async () => {
    open();
    // The suggestion arrives with the purpose catalog. Clearing before it lands
    // clears nothing, and what is typed then gets appended to it.
    await screen.findByDisplayValue("OpenAI");
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.type(screen.getByLabelText("Name"), "Prod billing key");

    await userEvent.click(screen.getByRole("button", { name: /Web search/ }));

    expect(screen.getByLabelText("Name")).toHaveValue("Prod billing key");
  });

  it("clears the suggestion for a service it cannot name", async () => {
    // "Something else" has no label worth pre-filling; leaving "OpenAI" there
    // would store a custom key called after a provider it has nothing to do with.
    open();
    await screen.findByDisplayValue("OpenAI");
    await userEvent.click(screen.getByRole("button", { name: /Something else/ }));

    expect(screen.getByLabelText("Name")).toHaveValue("");
  });
});
