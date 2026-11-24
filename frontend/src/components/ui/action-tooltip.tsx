import type { ReactElement } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "./tooltip";

/** Names an icon-only action on hover; a disabled button is wrapped so it still gets hover. */
export function ActionTooltip({
  label,
  children,
  disabled = false,
}: {
  label: string;
  children: ReactElement;
  disabled?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {disabled ? <span className="inline-flex">{children}</span> : children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
