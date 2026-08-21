"use client";

import { useMemo, useState } from "react";
import { Plug, RefreshCw, Sparkles, Webhook } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { Monogram } from "@/components/icons/monogram";
import { PortalTriggerDialog } from "@/components/triggers/portal-trigger-dialog";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  ListCard,
  ListCardEmpty,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useListControls,
} from "@/components/ui";
import { usePortals, type PortalWithState } from "@/hooks";
import { startGithubOrgOAuth, startMcpOAuth } from "@/lib/mcp-connections-api";
import { getErrorMessage } from "@/lib/api-error";

/**
 * A backend category slug as a heading - hyphens read as a machine field, and
 * the slug is lower case, so "lead-gen" becomes "Lead Gen". Title-cased at the
 * data level so both the card and the filter dropdown read the same; these are
 * catalog slugs, not translatable copy, so no message key stands behind them.
 */
function categoryLabel(category: string): string {
  return category.replace(/-/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

interface PortalCatalogProps {
  /** Whether the caller may run agents - the floor for creating any trigger. */
  canRun: boolean;
  /** Whether the caller may connect the organization's accounts. */
  canManageConnections: boolean;
}

/**
 * Every trigger portal, as a grid of branded cards with their presets.
 *
 * Mirrors the MCP server list: a search box, a category filter, and one card per
 * portal whose primary action follows its connection state - connect the account,
 * re-authorize it, or create a trigger. A control the caller may not use is not
 * rendered rather than disabled: creating needs `agents:run`, connecting the
 * organization's account needs `mcp:manage` (what the org MCP-connection and
 * GitHub OAuth routes require), and both are false while
 * permissions load, so the grid reveals actions rather than flashing ones that
 * would 403.
 *
 * The raw source-and-secret form is still reachable, as "Advanced: API
 * trigger" - the escape hatch for a provider no portal covers.
 */
export function PortalCatalog({ canRun, canManageConnections }: PortalCatalogProps) {
  const t = useTranslations("portals");
  const tErrors = useTranslations("errors");
  const { items, isLoading, error } = usePortals();

  const [category, setCategory] = useState("all");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [dialog, setDialog] = useState<PortalWithState | null>(null);
  const [advanced, setAdvanced] = useState(false);

  const categories = useMemo(
    () => [...new Set(items.map((item) => item.portal.category))].sort(),
    [items],
  );
  const narrowed = useMemo(
    () => items.filter((item) => category === "all" || item.portal.category === category),
    [items, category],
  );
  const list = useListControls({
    items: narrowed,
    matches: (item, query) =>
      item.portal.name.toLowerCase().includes(query) ||
      item.portal.description.toLowerCase().includes(query),
  });

  async function connect(item: PortalWithState) {
    setBusyKey(item.portal.key);
    try {
      // GitHub cannot be discovered like a generic MCP server, so its consent
      // URL is built from the organization's own OAuth App secret keyed by the
      // portal; every other portal follows the discovery-and-registration flow.
      const { authorization_url } =
        item.portal.event_source === "github"
          ? await startGithubOrgOAuth(item.portal.key)
          : await startMcpOAuth(
              { name: item.serverName ?? item.portal.name, url: item.serverUrl ?? "" },
              "organization",
            );
      window.location.assign(authorization_url);
    } catch (caught) {
      toast.error(getErrorMessage(caught, tErrors, t("couldNotConnect")));
      setBusyKey(null);
    }
    // On success the browser navigates away - leave the card busy.
  }

  if (isLoading) {
    return <LoadingState variant="skeleton-table" columns={1} rows={4} />;
  }
  if (error) {
    return <ErrorState description={getErrorMessage(error, tErrors, t("loadError"))} />;
  }

  return (
    <>
      <ListCard
        title={t("title")}
        counted={t("portalCount", { count: items.length })}
        controls={
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("searchPlaceholder")}
          />
        }
        contentClassName="space-y-4 p-4"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-auto min-w-40" aria-label={t("category")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allCategories")}</SelectItem>
              {categories.map((entry) => (
                <SelectItem key={entry} value={entry}>
                  {categoryLabel(entry)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {items.length === 0 && (
          <ListCardEmpty
            icon={Sparkles}
            title={t("emptyTitle")}
            description={t("emptyDescription")}
          />
        )}
        {items.length > 0 && list.matched === 0 && (
          // The catalog holds portals, but the search or category filter matched
          // none - a distinct message so a fruitless search does not read as an
          // empty catalog under a control that says there are some. Said *above*
          // the grid rather than instead of it, because the API card below is not
          // a catalog row and a filter must not take away the one way to make a
          // trigger for a provider no portal covers.
          <ListCardEmpty
            icon={Sparkles}
            title={t("noMatchesTitle")}
            description={t("noMatchesDescription")}
          />
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.visible.map((item) => (
            <Card
              key={item.portal.key}
              role="group"
              aria-label={item.portal.name}
              className="h-full"
            >
              <CardContent className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-start gap-2.5">
                  {item.portal.icon && isBrandName(item.portal.icon) ? (
                    <BrandIcon
                      name={item.portal.icon}
                      aria-hidden
                      className="mt-0.5 h-6 w-6 shrink-0"
                    />
                  ) : (
                    <Monogram label={item.portal.name} className="mt-0.5 h-6 w-6" />
                  )}
                  <div className="min-w-0 flex-1 space-y-1">
                    <span className="truncate text-sm font-medium">{item.portal.name}</span>
                    <p className="text-muted-foreground text-[11px] font-medium tracking-wide">
                      {categoryLabel(item.portal.category)}
                    </p>
                    <p className="text-muted-foreground line-clamp-2 text-sm">
                      {item.portal.description}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1">
                  {item.portal.presets.map((preset) => (
                    <Badge key={preset.key} variant="outline" className="text-[11px]">
                      {preset.label}
                    </Badge>
                  ))}
                </div>

                <div className="mt-auto">
                  <div className="border-border mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                    {item.action === "create" && canRun && (
                      <Button size="sm" variant="outline" onClick={() => setDialog(item)}>
                        <Sparkles className="mr-1 h-3.5 w-3.5" />
                        {t("createAction")}
                      </Button>
                    )}
                    {item.action === "connect" && canManageConnections && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyKey === item.portal.key}
                        onClick={() => connect(item)}
                      >
                        <Plug className="mr-1 h-3.5 w-3.5" />
                        {busyKey === item.portal.key ? t("redirecting") : t("connectAction")}
                      </Button>
                    )}
                    {item.action === "reauthorize" && canManageConnections && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyKey === item.portal.key}
                        onClick={() => connect(item)}
                      >
                        <RefreshCw className="mr-1 h-3.5 w-3.5" />
                        {busyKey === item.portal.key ? t("redirecting") : t("reauthorizeAction")}
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}

          {/* The API trigger, as a member of this grid rather than a ghost button
              in the toolbar above it: it is one of the ways to make an event
              trigger, so it belongs beside the others (#1071). A lucide glyph
              rather than a brand mark, because it stands for nobody's brand - it
              is your own code posting signed JSON. Outside the search, the
              category filter and the pager, since it is not a catalog row. */}
          {canRun && (
            <Card role="group" aria-label={t("advancedWebhook")} className="h-full border-dashed">
              <CardContent className="flex h-full flex-col gap-3 p-4">
                <div className="flex items-start gap-2.5">
                  <Webhook className="text-muted-foreground mt-0.5 h-6 w-6 shrink-0" aria-hidden />
                  <div className="min-w-0 flex-1 space-y-1">
                    <span className="truncate text-sm font-medium">{t("advancedWebhook")}</span>
                    <p className="text-muted-foreground text-[11px] font-medium tracking-wide">
                      {t("apiCategory")}
                    </p>
                    <p className="text-muted-foreground line-clamp-2 text-sm">
                      {t("apiDescription")}
                    </p>
                  </div>
                </div>
                <div className="mt-auto">
                  <div className="border-border mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                    <Button size="sm" variant="outline" onClick={() => setAdvanced(true)}>
                      <Sparkles className="mr-1 h-3.5 w-3.5" />
                      {t("createAction")}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <Pager
          page={list.page}
          pageCount={list.pageCount}
          matched={list.matched}
          total={list.total}
          onPage={list.setPage}
          counted={t("portalCount", { count: list.total })}
        />
      </ListCard>

      {dialog !== null && (
        <PortalTriggerDialog
          portal={dialog.portal}
          connectionId={dialog.connectionId}
          open
          onOpenChange={(next) => !next && setDialog(null)}
        />
      )}

      {advanced && (
        <TriggerFormDialog
          agentId={null}
          open
          initialType="event"
          onOpenChange={(next) => !next && setAdvanced(false)}
        />
      )}
    </>
  );
}
