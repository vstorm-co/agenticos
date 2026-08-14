"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Badge,
  DataTable,
  ListCard,
  ListCardControlsRow,
  ListCardFootRow,
  PaginationBar,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@/components/ui";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ConversationAgents } from "@/components/agents/conversation-agents";
import { ErrorState } from "@/components/states";
import { useAdminConversations, useAgents, useUrlSort } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";
import { useChanged } from "@/hooks/use-changed";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
// Keys the backend can sort on (route → service → repo).
const SORT_KEYS = ["title", "owner", "messages", "created_at", "updated_at"] as const;
type Status = "active" | "archived" | "all";

type Conversation = ReturnType<typeof useAdminConversations>["conversations"][number];

function getInitials(nameOrEmail: string): string {
  return nameOrEmail
    .split(/[\s@]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");
}

function UserAvatar({
  userId,
  label,
  size = "md",
}: {
  userId: string | null | undefined;
  label: string;
  size?: "sm" | "md";
}) {
  const cls = size === "sm" ? "h-6 w-6 text-[10px]" : "h-7 w-7 text-[11px]";
  return (
    <Avatar className={cls}>
      {userId && <AvatarImage src={`/api/users/avatar/${userId}`} alt={label} />}
      <AvatarFallback>{getInitials(label)}</AvatarFallback>
    </Avatar>
  );
}

export default function AdminConversationsPage() {
  const t = useTranslations("admin");
  const tAdminPages = useTranslations("pages.admin");
  const tc = useTranslations("common");
  const locale = useLocale();
  const {
    conversations,
    conversationsTotal,
    users,
    isLoading,
    error,
    fetchConversations,
    fetchUsers,
  } = useAdminConversations();
  // Archived included: a thread answered by an agent that has since been
  // retired is exactly the one somebody comes here looking for.
  const { agents } = useAgents({ includeArchived: true });
  const [search, setSearch] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("active");
  const [pageSize, setPageSize] = useState<number>(50);
  const [page, setPage] = useState(0);
  const { sort, setSort } = useUrlSort(SORT_KEYS, { by: "updated_at", dir: "desc" });

  // Back to the first page whenever the filters move: page 4 of a list that
  // now has one page shows nothing. During render, so the empty page is never
  // painted on the way.
  if (
    useChanged(
      `${search}|${selectedUserId}|${selectedAgentId}|${status}|${pageSize}|${sort.by}|${sort.dir}`,
    )
  ) {
    setPage(0);
  }

  // Load owners list for the dropdown - once on mount, independent of any tab.
  useEffect(() => {
    fetchUsers({ limit: 200, sort_by: "email", sort_dir: "asc" });
  }, [fetchUsers]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchConversations({
        search: search || undefined,
        user_id: selectedUserId || undefined,
        agent_id: selectedAgentId || undefined,
        status,
        sort_by: sort.by,
        sort_dir: sort.dir,
        skip: page * pageSize,
        limit: pageSize,
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [
    search,
    selectedUserId,
    selectedAgentId,
    status,
    sort.by,
    sort.dir,
    page,
    pageSize,
    fetchConversations,
  ]);

  const userOptions = useMemo(
    () => users.map((u) => ({ id: u.id, email: u.email, fullName: u.full_name })),
    [users],
  );

  const columns: Column<Conversation>[] = useMemo(
    () => [
      {
        key: "title",
        header: t("title"),
        sortable: true,
        cell: (conv) => (
          <span className="text-foreground font-medium">{conv.title || t("untitled")}</span>
        ),
      },
      {
        key: "owner",
        hideBelow: "md",
        header: t("owner"),
        sortable: true,
        cell: (conv) =>
          conv.user_email ? (
            <span className="flex items-center gap-2">
              <UserAvatar userId={conv.user_id ?? null} label={conv.user_email} size="sm" />
              <span className="text-muted-foreground truncate">{conv.user_email}</span>
            </span>
          ) : (
            <span className="text-muted-foreground">-</span>
          ),
      },
      {
        key: "agents",
        hideBelow: "lg",
        header: t("agentsColumn"),
        // Not sortable: the value is a set, and "sorted by which agents took
        // part" has no meaning a reader could predict.
        cell: (conv) =>
          conv.agents && conv.agents.length > 0 ? (
            <ConversationAgents agents={conv.agents} />
          ) : (
            <span className="text-muted-foreground">{t("generalAssistant")}</span>
          ),
      },
      {
        key: "messages",
        align: "right",
        hideBelow: "sm",
        header: t("messages"),
        sortable: true,
        cell: (conv) => <span className="tabular-nums">{conv.message_count}</span>,
      },
      {
        key: "created_at",
        hideBelow: "md",
        header: t("created"),
        sortable: true,
        cell: (conv) => (
          <span className="text-muted-foreground">{formatDate(conv.created_at, locale)}</span>
        ),
      },
      {
        key: "status",
        header: t("status"),
        cell: (conv) =>
          conv.is_archived ? (
            <Badge variant="secondary">{t("archived")}</Badge>
          ) : (
            <Badge variant="default">{t("active")}</Badge>
          ),
      },
      {
        key: "actions",
        align: "right",
        header: "",
        cell: (conv) => (
          <Link
            href={`${ROUTES.CHAT}?id=${conv.id}`}
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 font-mono text-[11px] tracking-wider uppercase transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
            {t("view")}
          </Link>
        ),
      },
    ],
    [t, locale],
  );

  return (
    <div className="space-y-4">
      <ListCard
        title={tAdminPages("conversationsCard")}
        counted={t("total", { count: conversationsTotal })}
        controls={<SearchInput value={search} onChange={setSearch} placeholder={t("search")} />}
        contentClassName="p-0"
      >
        <ListCardControlsRow>
          <Select value={status} onValueChange={(v) => setStatus(v as Status)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">{t("active")}</SelectItem>
              <SelectItem value="archived">{t("archived")}</SelectItem>
              <SelectItem value="all">{t("all")}</SelectItem>
            </SelectContent>
          </Select>

          <Select
            value={selectedUserId ?? "all"}
            onValueChange={(v) => setSelectedUserId(v === "all" ? null : v)}
          >
            <SelectTrigger className="w-[260px]">
              <SelectValue placeholder={t("allOwners")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allOwners")}</SelectItem>
              {userOptions.map((u) => (
                <SelectItem key={u.id} value={u.id}>
                  <span className="flex items-center gap-2">
                    <UserAvatar userId={u.id} label={u.fullName || u.email} size="sm" />
                    <span className="truncate">{u.email}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* By agent, not only by owner. "Which threads did the support agent
            answer in" is the question an operator has after a bad answer, and
            an agent is not a property of a thread - the picker can be changed
            mid-conversation, so this matches threads it *answered in*. */}
          <Select
            value={selectedAgentId ?? "all"}
            onValueChange={(v) => setSelectedAgentId(v === "all" ? null : v)}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder={t("allAgents")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allAgents")}</SelectItem>
              {agents.map((agent) => (
                <SelectItem key={agent.id} value={agent.id}>
                  <span className="flex items-center gap-2">
                    <AgentAvatar agentId={agent.id} name={agent.name} size="sm" />
                    <span className="truncate">{agent.name}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
            <SelectTrigger className="w-[110px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {tc("perPage", { count: n })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </ListCardControlsRow>

        {/* "No conversations found" and "the request was refused" are the same
            pixels, and this screen fans out to two lists - the threads and the
            owners the filter above is built from. Whichever failed, say so here
            rather than leaving an empty table to be read as an empty deployment. */}
        <DataTable<Conversation>
          columns={columns}
          rows={conversations}
          getRowKey={(conv) => conv.id}
          loading={isLoading && conversations.length === 0}
          sort={sort}
          onSort={setSort}
          error={
            error ? (
              <ErrorState title={t("couldnTLoadThisScreen")} description={error} className="m-5" />
            ) : null
          }
          empty={t("noConversations")}
          skeletonRows={5}
          className="rounded-none border-0 bg-transparent"
        />

        <ListCardFootRow>
          <PaginationBar
            page={page}
            pageSize={pageSize}
            total={conversationsTotal}
            isLoading={isLoading}
            onPage={setPage}
          />
        </ListCardFootRow>
      </ListCard>
    </div>
  );
}
