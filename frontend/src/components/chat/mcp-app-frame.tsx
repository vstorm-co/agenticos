"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ARTIFACT_SANDBOX, LinkRequestDialog } from "@/components/artifacts/artifact-frame";
import { PreviewSkeleton } from "@/components/ui/preview-skeleton";
import { useAskingGate } from "@/hooks/use-artifact-actions";
import { answer, asMessage, hostContext, type HostContext } from "@/lib/mcp-app-host";
import { mcpAppCallTool, mcpAppFrameUrl, mcpAppReadResource } from "@/lib/mcp-apps-api";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/types/chat";
import { getResolvedTheme, useThemeStore } from "@/stores/theme-store";
import { useConversationOnScreen } from "./visual-panel";

/** Where a page starts before it reports its own height. */
const INITIAL_HEIGHT = 320;
/** The tallest a page stands under the message; past this it scrolls inside its frame. */
const MAX_HEIGHT = 900;
const MIN_HEIGHT = 80;
/** How often a page's address is asked for before the frame gives up, and the first wait. */
const FRAME_ATTEMPTS = 4;
const FRAME_RETRY_MS = 750;

/**
 * One MCP Apps page under the message whose tool call it belongs to (#3450).
 *
 * The page is the server's own HTML, served from a signed content address under
 * the app sandbox: an opaque origin, no network. It talks to this host alone, over
 * `postMessage`, and only messages from its own frame are read. Its tool calls and
 * resource reads go to the backend, which relays them with the connection's
 * credential; a link it asks to open is put to the person first.
 */
export function McpAppFrame({ conversationId, call }: { conversationId: string; call: ToolCall }) {
  const t = useTranslations("chat.mcpApp");
  const locale = useLocale();
  const theme = getResolvedTheme(useThemeStore((state) => state.theme));
  const frame = useRef<HTMLIFrameElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [height, setHeight] = useState(INITIAL_HEIGHT);
  const [shown, setShown] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const asking = useAskingGate();
  const app = call.mcp_app;
  // The page answered once. A frame that loads again, or a page that introduces
  // itself again, has navigated away from the server's page: whatever runs there
  // now is not the page this host relays for, so the frame is taken down.
  const loads = useRef(0);
  const introduced = useRef(false);
  const gone = useRef(false);
  const leave = () => {
    gone.current = true;
    setFailed(true);
  };

  // The turn's end reaches the browser a moment before its row is saved, so an
  // address asked for at once can be refused: ask again a few times before
  // saying the page cannot be had.
  useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = (attempt: number) => {
      mcpAppFrameUrl(conversationId, call.id).then(
        (address) => current && setUrl(address),
        () => {
          if (!current) return;
          if (attempt + 1 >= FRAME_ATTEMPTS) setFailed(true);
          else timer = setTimeout(() => ask(attempt + 1), FRAME_RETRY_MS * (attempt + 1));
        },
      );
    };
    ask(0);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [conversationId, call.id]);

  const context: HostContext = useMemo(
    () => ({ theme, locale, toolName: call.name }),
    [theme, locale, call.name],
  );
  // Read by the listener, which is set up once per page.
  const latest = useRef({ context, app });
  useEffect(() => {
    latest.current = { context, app };
  });

  useEffect(() => {
    if (url === null) return;
    const post = (message: unknown) => frame.current?.contentWindow?.postMessage(message, "*");
    const listen = (event: MessageEvent) => {
      if (gone.current) return;
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      const message = asMessage(event.data);
      if (message === null) return;
      const { method, id, params = {} } = message;
      if (method === "ui/initialize") {
        if (introduced.current) {
          gone.current = true;
          setFailed(true);
          return;
        }
        introduced.current = true;
      }
      if (method === "ui/notifications/initialized") {
        const data = latest.current.app;
        if (!data) return;
        setShown(true);
        post({
          jsonrpc: "2.0",
          method: "ui/notifications/tool-input",
          params: { arguments: data.tool_input },
        });
        post({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: data.result });
      } else if (method === "ui/notifications/size-changed") {
        if (typeof params.height === "number" && Number.isFinite(params.height)) {
          setHeight(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.ceil(params.height))));
        }
      } else if (method !== undefined && id !== undefined) {
        void answer({ ...message, id, method }, latest.current.context, {
          callTool: (name, args) => mcpAppCallTool(conversationId, call.id, name, args),
          readResource: (uri) => mcpAppReadResource(conversationId, call.id, uri),
          openLink: (href) => {
            // Dropped while the console is already asking about something else.
            if (asking.take("link")) setLink(href);
          },
        }).then((reply) => {
          if (!gone.current) post(reply);
        });
      }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, [url, conversationId, call.id, asking]);

  useEffect(() => {
    if (!shown) return;
    frame.current?.contentWindow?.postMessage(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/host-context-changed",
        params: hostContext(context),
      },
      "*",
    );
  }, [shown, context]);

  if (failed) {
    return <p className="text-muted-foreground text-xs">{t("unavailable")}</p>;
  }
  return (
    <div className="relative w-full overflow-hidden rounded-md border" style={{ height }}>
      {url !== null && (
        <iframe
          ref={frame}
          src={url}
          onLoad={() => {
            loads.current += 1;
            if (loads.current > 1) leave();
          }}
          title={t("title", { tool: call.name })}
          sandbox={ARTIFACT_SANDBOX}
          referrerPolicy="no-referrer"
          style={{ colorScheme: theme }}
          className={cn(
            "block h-full w-full border-0 transition-opacity duration-300 motion-reduce:transition-none",
            shown ? "opacity-100" : "opacity-0",
          )}
        />
      )}
      {!shown && <PreviewSkeleton />}
      <LinkRequestDialog
        pending={link}
        onDone={() => {
          asking.release("link");
          setLink(null);
        }}
      />
    </div>
  );
}

/** A turn's MCP Apps pages, each under the answer, once the turn is saved to read them from. */
export function TurnMcpApps({
  calls,
  saved,
}: {
  calls: ToolCall[];
  /** The turn has ended and is stored: a page is read through its stored call. */
  saved: boolean;
}) {
  const shown = calls.filter((call) => call.mcp_app && call.status === "completed");
  if (!saved || shown.length === 0) return null;
  return <McpAppPages calls={shown} />;
}

/** The pages themselves, read through the conversation on screen. */
function McpAppPages({ calls }: { calls: ToolCall[] }) {
  // Null on a surface that cannot read a stored call - a hosted page, the widget.
  const conversationId = useConversationOnScreen();
  if (conversationId === null) return null;
  return (
    <div className="flex w-full min-w-0 flex-col gap-4 py-2.5">
      {calls.map((call) => (
        <McpAppFrame key={call.id} conversationId={conversationId} call={call} />
      ))}
    </div>
  );
}
