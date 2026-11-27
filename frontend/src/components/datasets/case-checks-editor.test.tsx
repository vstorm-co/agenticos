import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CurrencyProvider } from "@/components/providers/currency-provider";
vi.mock("@/hooks/use-currencies", () => ({ useCurrencies: () => ({ data: undefined }) }));
import { CaseChecksEditor } from "./case-checks-editor";

it("keeps an invalid cost criterion visible instead of silently retaining a valid amount", () => {
  const onChange = vi.fn();
  render(
    <CaseChecksEditor
      checks={[{ type: "max_cost_usd", value: "1", rest: {} }]}
      onChange={onChange}
    />,
  );
  const input = screen.getByLabelText("Check 1: what it checks (USD)");
  fireEvent.change(input, { target: { value: "invalid" } });
  expect(input).toBeInvalid();
  expect(onChange).toHaveBeenCalledWith([
    { type: "max_cost_usd", value: "invalid", rest: {}, currencyInvalid: true },
  ]);
});

it("edits the lower bound of a length criterion without dropping its unit or JSON path", () => {
  const onChange = vi.fn();
  render(
    <CaseChecksEditor
      checks={[
        { type: "length", value: "100", rest: { unit: "words", min: "10", path: "answer" } },
      ]}
      onChange={onChange}
    />,
  );
  fireEvent.change(screen.getByLabelText("Check 1: at least"), { target: { value: "20" } });
  expect(onChange).toHaveBeenCalledWith([
    { type: "length", value: "100", rest: { unit: "words", min: "20", path: "answer" } },
  ]);
});

it("keeps unknown reporting currency unavailable instead of labeling an editable USD criterion", () => {
  render(
    <CurrencyProvider>
      <CaseChecksEditor
        checks={[{ type: "max_cost_usd", value: "1", rest: {} }]}
        onChange={vi.fn()}
      />
    </CurrencyProvider>,
  );
  expect(screen.getByLabelText("Check 1: what it checks (—)")).toBeDisabled();
});

it("edits a latency criterion as a decimal field", () => {
  const onChange = vi.fn();
  render(
    <CaseChecksEditor
      checks={[{ type: "max_latency_ms", value: "100", rest: {} }]}
      onChange={onChange}
    />,
  );
  const input = screen.getByLabelText("Check 1: what it checks");
  expect(input).toHaveAttribute("inputmode", "decimal");
  fireEvent.change(input, { target: { value: "200" } });
  expect(onChange).toHaveBeenCalledWith([{ type: "max_latency_ms", value: "200", rest: {} }]);
});
