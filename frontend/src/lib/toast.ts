import { toast } from "sonner";

/**
 * A routine confirmation - "Run started", "Published version 2", "Record added" -
 * that must not sit on what the person does next. The app's toasts open top-right,
 * which is where a workflow editor and a table keep their header buttons; these
 * go bottom-center instead - bottom-right holds the assistant launcher and the
 * canvas zoom controls - and leave sooner, since they report what the person
 * just did and need no reading. The Toaster's bottom offset (providers.tsx)
 * lifts them over the canvas's own bottom-center bars. Failures and anything
 * that asks for a decision stay on `toast` and its defaults.
 */
export function toastDone(message: string): string | number {
  return toast.success(message, { position: "bottom-center", duration: 3000 });
}
