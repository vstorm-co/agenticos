import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { makeDefinition } from "@/components/workflows/validation/fixtures";
import { makeMediaOperation } from "@/test-utils/workflow-media";
import type { WorkflowNodeRunRead } from "@/lib/workflows/types";

import { StepAttentionDialog } from "./step-attention-dialog";

const step = (patch: Partial<WorkflowNodeRunRead> = {}): WorkflowNodeRunRead => ({
  id: "n1",
  node_instance_id: "a",
  scope_path: [],
  status: "needs_attention",
  waiting_reason: null,
  attempts: 1,
  cost: 0,
  error: null,
  output: null,
  last_attempt_status: null,
  late_output: null,
  started_at: null,
  ended_at: null,
  ...patch,
});

function setup(
  patch: Partial<WorkflowNodeRunRead> = {},
  options: { effect?: "pure" | "write"; routed?: boolean; inLoop?: boolean } = {},
) {
  const onResolve = vi.fn();
  render(
    <StepAttentionDialog
      node={step(patch)}
      stepName="Send email"
      definition={makeDefinition({ id: "mail.send", effect_kind: options.effect ?? "pure" })}
      routesErrors={options.routed ?? false}
      inLoop={options.inLoop ?? false}
      open
      onOpenChange={vi.fn()}
      onResolve={onResolve}
    />,
  );
  return onResolve;
}

describe("StepAttentionDialog", () => {
  it("warns that an uncertain write may be done twice", () => {
    setup({ last_attempt_status: "uncertain" }, { effect: "write" });
    expect(
      screen.getByText("Send email may already have happened; running it again can do it twice."),
    ).toBeInTheDocument();
  });

  it("says a step that stopped waiting has nothing left to wake it", () => {
    setup({ last_attempt_status: "completed" });
    expect(
      screen.getByText("Send email stopped waiting with nothing left to wake it."),
    ).toBeInTheDocument();
  });

  it("is neutral for an uncertain step that only reads", () => {
    setup({ last_attempt_status: "uncertain" }, { effect: "pure" });
    expect(
      screen.getByText("Send email needs attention. Choose what happens to it."),
    ).toBeInTheDocument();
  });

  it("is neutral for a step with no definition left", () => {
    render(
      <StepAttentionDialog
        node={step({ last_attempt_status: "uncertain" })}
        stepName="Gone"
        definition={undefined}
        routesErrors={false}
        inLoop={false}
        open
        onOpenChange={vi.fn()}
        onResolve={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Gone needs attention. Choose what happens to it."),
    ).toBeInTheDocument();
  });

  it("offers a result that arrived late, and takes it", () => {
    const onResolve = setup({ late_output: { id: 1 } });
    expect(screen.getByText("It finished after it was marked uncertain.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use that result" }));
    expect(onResolve).toHaveBeenCalledWith("use_late_result");
  });

  it("offers no late result when none arrived", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Use that result" })).toBeNull();
    expect(screen.queryByText("It finished after it was marked uncertain.")).toBeNull();
  });

  it("hides the error route for a step that neither routes errors nor sits in a loop", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Take its error route" })).toBeNull();
    expect(screen.getByRole("button", { name: "Fail the run" })).toBeInTheDocument();
  });

  it("takes the error route for a routed step", () => {
    const routed = setup({}, { routed: true });
    fireEvent.click(screen.getByRole("button", { name: "Take its error route" }));
    expect(routed).toHaveBeenCalledWith("use_error_route");
  });

  it("offers the error route for a step in a loop", () => {
    setup({}, { inLoop: true });
    expect(screen.getByRole("button", { name: "Take its error route" })).toBeInTheDocument();
  });

  it("runs again, or fails the run, as chosen", () => {
    const onResolve = setup();
    fireEvent.click(screen.getByRole("button", { name: "Run it again" }));
    fireEvent.click(screen.getByRole("button", { name: "Fail the run" }));
    expect(onResolve.mock.calls).toEqual([["run_again"], ["fail_run"]]);
  });

  it("disables every choice while one is being sent", () => {
    render(
      <StepAttentionDialog
        node={step()}
        stepName="X"
        definition={undefined}
        routesErrors
        inLoop={false}
        open
        onOpenChange={vi.fn()}
        onResolve={vi.fn()}
        busy
      />,
    );
    expect(screen.getByRole("button", { name: "Run it again" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Fail the run" })).toBeDisabled();
  });

  it.each([
    ["collect_existing", "Collect existing output"],
    ["recover_output", "Recover output"],
  ] as const)("labels %s as recovery without asking for a new charge", (retry_effect, label) => {
    const onResolve = setup({ media_operation: makeMediaOperation({ retry_effect }) });
    expect(screen.queryByRole("checkbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(onResolve).toHaveBeenCalledWith("run_again");
  });

  it.each(["none", "reconciliation_required"] as const)(
    "cannot use run_again when the server reports %s",
    (retry_effect) => {
      const onResolve = setup({ media_operation: makeMediaOperation({ retry_effect }) });
      expect(screen.getByRole("button", { name: "Run it again" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Run it again" }));
      expect(onResolve).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Fail the run" }));
      expect(onResolve).toHaveBeenCalledWith("fail_run");
    },
  );

  it("requires an explicit charge acknowledgement before a replacement submission", () => {
    const onResolve = setup({
      media_operation: makeMediaOperation({ retry_effect: "new_billable_submission" }),
    });
    const submit = screen.getByRole("button", { name: "Send a new request" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(onResolve).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(submit).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(submit);
    expect(onResolve).toHaveBeenCalledWith("run_again");
  });

  it("clears a charge acknowledgement when the operation or dialog lifetime changes", () => {
    const onResolve = vi.fn();
    const props = {
      stepName: "Generate image",
      definition: undefined,
      routesErrors: false,
      inLoop: false,
      open: true,
      onOpenChange: vi.fn(),
      onResolve,
    };
    const operation = makeMediaOperation({ retry_effect: "new_billable_submission" });
    const view = render(
      <StepAttentionDialog {...props} node={step({ media_operation: operation })} />,
    );
    fireEvent.click(screen.getByRole("checkbox"));
    view.rerender(
      <StepAttentionDialog
        {...props}
        node={step({ media_operation: { ...operation, operation_id: "operation-b" } })}
      />,
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox"));
    view.rerender(
      <StepAttentionDialog {...props} open={false} node={step({ media_operation: operation })} />,
    );
    view.rerender(<StepAttentionDialog {...props} node={step({ media_operation: operation })} />);
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(onResolve).not.toHaveBeenCalled();
  });
});
