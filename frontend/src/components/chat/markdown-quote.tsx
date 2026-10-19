"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, type ComponentProps } from "react";

import { Button } from "@/components/ui";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";

/** The quote's paragraphs, a blank line apart, as a reply box expects them. */
function quoteText(quote: HTMLElement): string {
  return (
    Array.from(quote.children)
      // An element's text is never null; only a document or a doctype has none.
      .map((block) => (block.textContent as string).trim())
      .filter((text) => text !== "")
      .join("\n\n")
  );
}

/**
 * A quotation from an answer, with a copy button that appears on hover.
 *
 * What an agent quotes is most often something to send on - a suggested reply,
 * a paragraph for an email - so it gets the button a table has, and copies the
 * quote as it is drawn: the words, without the markdown or the citation markers'
 * markup around them.
 */
export function MarkdownQuote({ children, ...props }: ComponentProps<"blockquote">) {
  const t = useTranslations("chat.copy");
  const quote = useRef<HTMLQuoteElement>(null);
  const { copy, copied } = useCopyToClipboard();

  const copyQuote = async () => {
    /* v8 ignore next -- the button is only clickable once the quote is mounted */
    if (quote.current === null) return;
    await copy(quoteText(quote.current), quote.current.innerHTML);
  };

  return (
    <div className="group/quote relative my-3">
      <blockquote
        ref={quote}
        className="border-brand/40 text-foreground/75 border-l-2 pr-10 pl-4 italic"
        {...props}
      >
        {children}
      </blockquote>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={copyQuote}
        title={copied ? t("copied") : t("copyQuote")}
        aria-label={copied ? t("copiedToClipboard") : t("copyQuote")}
        // As on a table: on hover or focus, and always where nothing can hover.
        className="bg-popover border-foreground/10 hover:bg-muted touch:opacity-100 absolute top-0 right-0 h-7 w-7 border p-0 opacity-0 shadow-sm transition-opacity group-focus-within/quote:opacity-100 group-hover/quote:opacity-100"
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
