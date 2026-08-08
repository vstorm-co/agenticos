"use client";
import type { ToolCall } from "@/types";
import { MarkdownContent } from "../markdown-content";
import { CollapsibleBlock } from "../collapsible-block";
import { useTranslations } from "next-intl";

interface Parsed {
  stdout: string | null;
  result: string | null;
  error: string | null;
}

function parseResult(text: string): Parsed {
  if (!text || text === "(code ran successfully with no output)") {
    return { stdout: null, result: null, error: null };
  }
  // i18n-exempt: matches the tool's own output prefix, which is not translated
  if (text.startsWith("Execution failed:")) {
    return { stdout: null, result: null, error: text };
  }

  // Format: "stdout:\n<text>" optionally followed by "\n\nresult: <value>"
  if (text.startsWith("stdout:\n")) {
    const body = text.slice("stdout:\n".length);
    const sep = body.indexOf("\n\nresult: ");
    if (sep !== -1) {
      return {
        stdout: body.slice(0, sep).trim(),
        result: body.slice(sep + "\n\nresult: ".length).trim(),
        error: null,
      };
    }
    return { stdout: body.trim(), result: null, error: null };
  }

  // Format: "result: <value>"
  if (text.startsWith("result: ")) {
    return { stdout: null, result: text.slice("result: ".length).trim(), error: null };
  }

  // Fallback: treat entire text as stdout
  return { stdout: text, result: null, error: null };
}

/**
 * A snippet the agent ran, and what running it printed.
 *
 * Two halves of one call, and only one of them is worth reading at a time. The code is
 * the content while there is no output - which is while it runs, and afterwards if it
 * failed, because then the code is the thing being debugged. Once output arrives the
 * code becomes context: it closes to its header, one click from being back.
 *
 * Both halves collapse independently, which is why neither is derived from `status` at
 * the point of render - see `CollapsibleBlock`, whose `open` is a starting state that a
 * click outlives.
 */
export function RunPythonResult({
  toolCall,
  resultText,
}: {
  toolCall: ToolCall;
  resultText: string;
}) {
  const t = useTranslations("chat.tools");
  const code = typeof toolCall.args?.code === "string" ? toolCall.args.code.trim() : null;
  const isRunning = toolCall.status !== "completed" && toolCall.status !== "error" && !resultText;

  const { stdout, result, error } = parseResult(resultText);
  const outputText = [stdout, result ? `result: ${result}` : null].filter(Boolean).join("\n\n");
  // Open until there is something better to read, and open again when the run failed
  // because then the code is what is being read. "Nothing better" covers the whole of
  // the rest: a call still running has no output yet, a failure's message is not
  // output, and code that printed nothing would otherwise close onto a bare header.
  const codeOpen = outputText === "" || toolCall.status === "error";

  return (
    <div className="space-y-2 pt-1">
      {code !== null && (
        // i18n-exempt: the language token the fenced block labels itself with
        <CollapsibleBlock label="python" copyText={code} open={codeOpen}>
          <MarkdownContent content={"```python\n" + code + "\n```"} bareCode />
        </CollapsibleBlock>
      )}

      {/* Only when the arguments never reached us, which a replayed conversation can
          do. With the code in hand there is something better to show while it runs. */}
      {isRunning && code === null && (
        <p className="text-muted-foreground py-2 text-xs italic">{t("running")}</p>
      )}

      {error && (
        <div className="bg-destructive/8 text-destructive rounded-lg p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
          {error}
        </div>
      )}

      {outputText && (
        <CollapsibleBlock label={t("output")} copyText={outputText} open>
          <pre className="text-foreground/85 max-h-80 scrollbar-thin overflow-y-auto p-3.5 font-mono text-[12.5px] leading-relaxed whitespace-pre-wrap">
            {outputText}
          </pre>
        </CollapsibleBlock>
      )}

      {!code && !error && !outputText && resultText && (
        <p className="text-muted-foreground py-2 text-xs italic">{resultText}</p>
      )}
    </div>
  );
}
