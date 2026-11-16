import * as React from "react";

import { cn } from "@/lib/utils";
import { ContextHelp } from "./context-help";
import { Label } from "./label";

interface InjectableProps {
  id?: string;
  "aria-invalid"?: boolean;
  "aria-required"?: boolean;
  "aria-describedby"?: string;
}

export interface FormFieldProps {
  /** Visible label text. */
  label?: React.ReactNode;
  /** id of the control - used for the label's `htmlFor` and injected onto the child. */
  htmlFor: string;
  /** Helper text shown below the control when there's no error. */
  description?: React.ReactNode;
  /** Optional explanation behind a help button; requirements stay in description. */
  help?: React.ReactNode;
  /** Error message - when set, the control is marked invalid + described by it. */
  error?: string | null;
  required?: boolean;
  className?: string;
  /** Switches put the control beside their label and explanatory text. */
  layout?: "stacked" | "switch";
  /** The control (Input, Textarea, Select trigger, …). A single element. */
  children: React.ReactNode;
}

/**
 * Label + control + description/error, with accessible wiring done for you:
 * the label's `htmlFor` matches the control `id`, and `aria-describedby` /
 * `aria-invalid` are injected onto the control. Replaces the repeated
 * label+input+error markup across auth, settings, and dialog forms.
 */
export function FormField({
  label,
  htmlFor,
  description,
  help,
  error,
  required,
  className,
  layout = "stacked",
  children,
}: FormFieldProps) {
  const descId = `${htmlFor}-desc`;
  const errId = `${htmlFor}-err`;
  const describedBy = [error ? errId : description || help ? descId : null]
    .filter(Boolean)
    .join(" ");

  const controlId = React.isValidElement<InjectableProps>(children)
    ? (children.props.id ?? htmlFor)
    : htmlFor;
  const control = React.isValidElement<InjectableProps>(children)
    ? React.cloneElement(children, {
        id: controlId,
        "aria-required": required || children.props["aria-required"],
        "aria-invalid": error ? true : children.props["aria-invalid"],
        "aria-describedby":
          [children.props["aria-describedby"], describedBy].filter(Boolean).join(" ") || undefined,
      })
    : children;

  return (
    <div
      className={cn(
        layout === "switch"
          ? "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-1"
          : "space-y-2",
        className,
      )}
    >
      {(label || help) && (
        <div
          className={cn(
            "touch:min-h-11 flex min-h-6 items-center gap-1",
            layout === "switch" && "col-start-1 row-start-1",
          )}
        >
          {label && (
            <Label
              htmlFor={controlId}
              className={layout === "switch" ? "col-start-1 row-start-1" : "block"}
            >
              {label}
              {required && (
                <span className="text-destructive ml-0.5" aria-hidden="true">
                  *
                </span>
              )}
            </Label>
          )}
          {help && <ContextHelp>{help}</ContextHelp>}
        </div>
      )}
      {layout === "switch" ? (
        <div className="col-start-2 row-span-2 row-start-1 self-center">{control}</div>
      ) : (
        control
      )}
      {description && !error && (
        <p
          id={descId}
          className={cn(
            "text-muted-foreground text-xs leading-5",
            layout === "switch" && "col-start-1 row-start-2",
          )}
        >
          {description}
        </p>
      )}
      {help && !description && !error && (
        <p id={descId} className="sr-only">
          {help}
        </p>
      )}
      {error && (
        <p
          id={errId}
          role="alert"
          className={cn(
            "text-destructive-ink text-[13px] leading-5",
            layout === "switch" && "col-start-1 row-start-2",
          )}
        >
          {error}
        </p>
      )}
    </div>
  );
}
