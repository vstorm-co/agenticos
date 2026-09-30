"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, type ComponentProps } from "react";

import { Button } from "@/components/ui";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { readTable, tableToHtml, tableToMarkdown } from "@/lib/table-copy";

/**
 * A table from an answer, with a copy button that appears on hover.
 *
 * The button reads the table as it is drawn rather than the markdown it came
 * from, so what is copied is what somebody sees - citations resolved, a
 * streamed answer's words joined back up - and it copies both forms a
 * destination might want (see `table-copy.ts`).
 */
export function MarkdownTable({ children, ...props }: ComponentProps<"table">) {
  const t = useTranslations("chat.copy");
  const table = useRef<HTMLTableElement>(null);
  const { copy, copied } = useCopyToClipboard();

  const copyTable = async () => {
    /* v8 ignore next -- the button is only clickable once the table is mounted */
    if (table.current === null) return;
    const text = readTable(table.current);
    await copy(tableToMarkdown(text), tableToHtml(text));
  };

  return (
    <div className="group/table relative my-3">
      <div className="border-foreground/10 overflow-x-auto rounded-lg border">
        <table
          ref={table}
          className="w-full border-collapse text-sm [&_th:last-child]:pr-11"
          {...props}
        >
          {children}
        </table>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={copyTable}
        title={copied ? t("copied") : t("copyTable")}
        aria-label={copied ? t("copiedToClipboard") : t("copyTable")}
        // Inside the frame: on its corner it was clipped by the message column,
        // which hides what overflows it. The last header keeps room for it. On
        // hover or focus, and always where nothing can hover: a control a phone
        // can never reveal is a control a phone does not have.
        className="bg-popover border-foreground/10 hover:bg-muted touch:opacity-100 absolute top-1.5 right-1.5 h-7 w-7 border p-0 opacity-0 shadow-sm transition-opacity group-focus-within/table:opacity-100 group-hover/table:opacity-100"
      >
        {copied ? (
          <Check className="text-success h-3.5 w-3.5" aria-hidden />
        ) : (
          <Copy className="h-3.5 w-3.5" aria-hidden />
        )}
      </Button>
    </div>
  );
}
