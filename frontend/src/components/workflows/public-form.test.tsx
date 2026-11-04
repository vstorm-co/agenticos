import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicForm, type PublicFormPage } from "./public-form";

const PAGE: PublicFormPage = {
  title: "Talk to our team",
  description: "We answer within a day.",
  submit_label: "Send request",
  fields: [
    {
      name: "name",
      label: "Your name",
      type: "text",
      required: true,
      description: null,
      options: [],
    },
    {
      name: "seats",
      label: "Team size",
      type: "integer",
      required: false,
      description: null,
      options: [],
    },
  ],
};

function answer(status: number, body: unknown = {}) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("PublicForm", () => {
  it("sends draft answers through the authenticated test adapter", async () => {
    const submit = vi.fn().mockResolvedValue("Run started");
    const publicRequest = vi.fn();
    vi.stubGlobal("fetch", publicRequest);
    render(<PublicForm page={PAGE} onSubmitValues={submit} />);
    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Run started");
    expect(submit).toHaveBeenCalledWith({ name: "Ada" });
    expect(publicRequest).not.toHaveBeenCalled();
  });
  it("keeps the appearance preview inert", () => {
    render(<PublicForm page={PAGE} preview />);
    expect(screen.getByLabelText("Your name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send request" })).toBeDisabled();
  });

  it("names a missing answer before sending anything", async () => {
    const fetchMock = answer(201);
    render(<PublicForm page={PAGE} token="tok" />);

    expect(screen.getByRole("heading", { name: "Talk to our team" })).toBeVisible();
    expect(await screen.findByText("We answer within a day.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Your name")).toHaveAttribute("aria-invalid", "true");
  });

  it("sends typed answers with the empty trap, and shows the form's thanks", async () => {
    const fetchMock = answer(201, { message: "Thanks - we will call you." });
    render(<PublicForm page={PAGE} token="tok_1" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.type(screen.getByLabelText(/Team size/), "12");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Thanks - we will call you.");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/forms/tok_1");
    expect(JSON.parse(init.body)).toEqual({ values: { name: "Ada", seats: 12 }, website: null });
  });

  it("sends whatever a script typed into the trap", async () => {
    const fetchMock = answer(201, { message: "Thanks" });
    render(<PublicForm page={{ ...PAGE, description: null }} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Bot");
    await userEvent.type(screen.getByLabelText("Leave this empty"), "spam.example");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body).website).toBe("spam.example");
  });

  it("marks the answer the server refused, and drops the mark once it is changed", async () => {
    answer(422, {
      error: { details: { problems: [{ field: "seats", message: "x", type: "int_type" }] } },
    });
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.type(screen.getByLabelText(/Team size/), "12");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByText("This has to be a whole number.")).toBeVisible();
    expect(screen.getByLabelText(/Team size/)).toHaveAttribute("aria-invalid", "true");
    await userEvent.type(screen.getByLabelText(/Team size/), "3");
    expect(screen.getByLabelText(/Team size/)).toHaveAttribute("aria-invalid", "false");
  });

  it("shows a local check over a stale server mark, and clears the mark on the next send", async () => {
    answer(422, {
      error: { details: { problems: [{ field: "name", message: "x", type: "string_too_long" }] } },
    });
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText("This answer does not fit - check it.")).toBeVisible();

    await userEvent.clear(screen.getByLabelText("Your name"));
    expect(screen.getByText("Fill this in.")).toBeVisible();
    expect(screen.queryByText("This answer does not fit - check it.")).toBeNull();

    answer(201, { message: "Thanks" });
    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Thanks");
  });

  it.each([
    [
      422,
      { error: { details: { problems: [{ field: "extra", type: "extra_forbidden" }] } } },
      "This form has changed",
    ],
    [
      422,
      { error: { details: { fields: [{ field: "values", message: "x" }] } } },
      "could not be read",
    ],
    [413, {}, "too long to send"],
  ])("says why a %s refused the whole form", async (status, body, words) => {
    answer(status, body);
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(words);
  });

  it("reads a refusal whose body is not JSON as a plain refusal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 422 })));
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Some answers do not fit this form");
  });

  it.each([
    [422, "Some answers do not fit this form"],
    [429, "taking a lot of answers"],
    [402, "not taking answers right now"],
    [404, "This form is closed."],
    [500, "could not be sent"],
  ])("says why the form refused a %s", async (status, words) => {
    answer(status);
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(words);
  });

  it("says the answers could not be sent when the network fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<PublicForm page={PAGE} token="tok" />);

    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be sent");
  });
});
