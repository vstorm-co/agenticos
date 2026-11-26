import type { Metadata } from "next";
import { Bot, Lock, UserRound } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { DraftCardView } from "@/components/chat/draft-card";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { SharedVisuals, type SharedVisual } from "@/components/chat/shared-visuals";
import { ChatIcon } from "@/components/icons/product-icons";
import { AgenticosAttribution } from "@/components/shared/agenticos-attribution";
import type { DraftCard } from "@/lib/drafts";
import { BackendApiError, backendFetch } from "@/lib/server-api";
import { cn, formatDateTime } from "@/lib/utils";

/** A secret share address is not an indexable document or an outbound referrer. */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

interface SharedConversationPageProps {
  params: Promise<{ token: string; locale: string }>;
}

interface SharedMessage {
  id: string;
  role: string;
  content: string | null;
  created_at: string | null;
  visuals?: SharedVisual[];
  drafts?: DraftCard[];
}

interface SharedConversation {
  conversation: { title: string | null; messages: SharedMessage[] };
  show_agenticos_attribution?: boolean;
}

async function fetchSharedConversation(token: string): Promise<SharedConversation | null> {
  if (!/^[A-Za-z0-9_-]+$/.test(token)) return null;
  try {
    return await backendFetch<SharedConversation>(
      `/api/v1/conversations/shared/${encodeURIComponent(token)}`,
      { cache: "no-store" },
    );
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) return null;
    throw error;
  }
}

export default async function SharedConversationPage({ params }: SharedConversationPageProps) {
  const { token, locale } = await params;
  const [t, chat, data] = await Promise.all([
    getTranslations({ locale, namespace: "pages.root" }),
    getTranslations({ locale, namespace: "chat.rail" }),
    fetchSharedConversation(token),
  ]);

  if (!data?.conversation) {
    return (
      <main id="main" className="grid min-h-dvh place-items-center px-5 py-12">
        <section className="bg-card border-border w-full max-w-sm rounded-2xl border p-6 text-center sm:p-8">
          <span className="bg-muted text-muted-foreground mx-auto grid size-11 place-items-center rounded-xl">
            <ChatIcon className="size-5" aria-hidden />
          </span>
          <h1 className="mt-4 text-xl font-semibold tracking-tight">{t("shareLinkNotFound")}</h1>
          <p className="text-muted-foreground mt-2 text-sm leading-6">{t("shareLinkExpired")}</p>
        </section>
      </main>
    );
  }

  const { conversation } = data;
  const title = conversation.title?.trim() || t("sharedConversation");
  const messages = conversation.messages.filter(
    (message) => message.content?.trim() || message.visuals?.length || message.drafts?.length,
  );

  return (
    <main id="main" className="bg-background text-foreground min-h-dvh">
      <header className="border-border border-b">
        <div className="mx-auto flex w-full max-w-3xl items-start gap-3 px-5 py-6 sm:gap-4 sm:px-8 sm:py-9">
          <span className="bg-muted text-muted-foreground grid size-10 shrink-0 place-items-center rounded-xl sm:size-12">
            <ChatIcon className="size-4 sm:size-5" aria-hidden />
          </span>
          <div className="min-w-0 space-y-2">
            <h1 className="text-xl leading-tight font-semibold tracking-tight wrap-anywhere sm:text-3xl">
              {title}
            </h1>
            <p className="text-muted-foreground flex items-center gap-1.5 text-xs sm:text-sm">
              <Lock className="size-3 shrink-0" aria-hidden />
              {t("sharedConversationReadOnly")}
            </p>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-3xl px-5 pt-6 pb-10 sm:px-8 sm:pt-9 sm:pb-14">
        {messages.length > 0 ? (
          <ol className="min-w-0 space-y-6 sm:space-y-8">
            {messages.map((msg) => {
              const isUser = msg.role === "user";
              const Speaker = isUser ? UserRound : Bot;
              return (
                <li
                  key={msg.id}
                  className={cn("flex min-w-0 flex-col gap-2.5", isUser && "items-end")}
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="bg-muted text-muted-foreground grid size-7 shrink-0 place-items-center rounded-full">
                      <Speaker className="size-3.5" aria-hidden />
                    </span>
                    <span className="text-sm font-medium">
                      {isUser ? t("sharedConversationUser") : chat("agent")}
                    </span>
                    {msg.created_at && (
                      <time dateTime={msg.created_at} className="text-muted-foreground text-xs">
                        {formatDateTime(msg.created_at, locale)}
                      </time>
                    )}
                  </div>
                  {msg.content?.trim() && (
                    <div
                      className={cn(
                        "max-w-full min-w-0 text-sm leading-relaxed wrap-anywhere sm:text-[15px]",
                        isUser
                          ? "bg-muted w-fit rounded-2xl rounded-se-sm px-4 py-3 whitespace-pre-wrap sm:max-w-[85%]"
                          : "w-full",
                      )}
                    >
                      {isUser ? msg.content : <MarkdownContent content={msg.content} inertImages />}
                    </div>
                  )}
                  {(!!msg.visuals?.length || !!msg.drafts?.length) && (
                    <div className="w-full min-w-0">
                      {!!msg.visuals?.length && <SharedVisuals visuals={msg.visuals} />}
                      {msg.drafts?.map((draft) => (
                        <DraftCardView key={draft.id} card={draft} />
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="text-muted-foreground py-10 text-center text-sm">{t("noMessagesYet")}</p>
        )}

        {data.show_agenticos_attribution !== false && (
          <div className="border-border mt-10 flex justify-end border-t pt-6">
            <AgenticosAttribution />
          </div>
        )}
      </div>
    </main>
  );
}
