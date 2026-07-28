"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRightLeft, Building2, Check, Plus } from "lucide-react";

import { CreateOrgDialog } from "@/components/teams";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
} from "@/components/ui";
import { useOrganizations } from "@/hooks";
import { ROUTES } from "@/lib/constants";

/** How many workspaces the account belongs to, in words rather than a bare digit. */
function storedCount(count: number): string {
  return count === 1 ? "1 workspace" : `${count} workspaces`;
}

/**
 * The list's frame, drawn whether or not there is anything in it - the same
 * always-visible container the vault draws around its keys. Same header, same
 * border, in every state: what changes is what is inside it.
 */
function WorkspacesCard({ count, children }: { count: number | null; children: ReactNode }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">Workspaces</CardTitle>
          <CardDescription className="text-xs">
            {/* `null` is "the request has not answered". Rendering "0 workspaces"
                there would state something nothing has said yet. */}
            {count === null ? <Skeleton className="h-3 w-24" /> : storedCount(count)}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-4">{children}</CardContent>
    </Card>
  );
}

export default function OrgsPage() {
  const { orgs, activeOrgId, fetchOrgs, switchOrg } = useOrganizations();
  const [createOpen, setCreateOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await fetchOrgs();
      if (!cancelled) setIsLoading(false);
    })();
    if (searchParams.get("create") === "1") setCreateOpen(true);
    return () => {
      cancelled = true;
    };
  }, [fetchOrgs, searchParams]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Organizations"
        description="Switch between workspaces, manage members, and spin up new organizations to collaborate with your team."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            New organization
          </Button>
        }
      />

      <WorkspacesCard count={isLoading ? null : orgs.length}>
        {isLoading ? (
          // The same tiles the populated grid draws, as skeletons - a skeleton
          // that draws a different shape is a layout jump on every load.
          <div className="grid gap-3 sm:grid-cols-2">
            {[0, 1].map((tile) => (
              <div key={tile} className="border-border flex flex-col gap-4 rounded-xl border p-5">
                <div className="flex items-start gap-3">
                  <Skeleton className="h-11 w-11 shrink-0 rounded-xl" />
                  <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
                <Skeleton className="h-8 w-full" />
              </div>
            ))}
          </div>
        ) : orgs.length === 0 ? (
          // Inline rather than an `EmptyState`: that component draws its own
          // bordered box, and inside a card it would frame one message twice.
          <div className="px-6 py-12 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <Building2 className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">No organizations yet</p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
              Create your first workspace to invite teammates and share access to conversations and
              knowledge bases.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-5"
              onClick={() => setCreateOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" />
              Create organization
            </Button>
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {orgs.map((org) => {
              const isActive = org.id === activeOrgId;
              return (
                <li
                  key={org.id}
                  className="border-border bg-card hover:border-foreground/30 relative flex flex-col gap-4 rounded-xl border p-5 transition-colors"
                >
                  {/* Whole-row link, under the one real control. The link is an
                      absolute overlay at z-10, so static content beneath it
                      clicks through to the detail page; the Switch button sits
                      in a z-20 wrapper above it and handles its own click - a
                      sibling of the link, so nothing bubbles into a navigation.
                      The wrapper (not the button) carries the z-index because a
                      disabled button is `pointer-events-none`: without it, a
                      click on "Current" would fall through to the link and
                      navigate, and a control that reads as inert must be inert.
                      Changing the avatar lives on that detail page, not here. */}
                  <Link
                    href={ROUTES.ORG_MEMBERS(org.id)}
                    className="focus-visible:ring-ring absolute inset-0 z-10 rounded-[inherit] focus-visible:ring-2 focus-visible:outline-none"
                    aria-label={`Open ${org.name}`}
                  />

                  <div className="flex items-start gap-3">
                    <span className="bg-muted text-foreground flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl">
                      {org.avatar_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={`/api/orgs/${org.id}/avatar?v=${org.updated_at ?? ""}`}
                          alt={org.name}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <Building2 className="h-5 w-5" />
                      )}
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-foreground truncate text-sm font-semibold">
                          {org.name}
                        </h2>
                        {org.is_personal && (
                          <span className="border-border text-muted-foreground rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                            Personal
                          </span>
                        )}
                        {isActive && (
                          <span className="border-border bg-muted text-foreground inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase">
                            <Check className="h-2.5 w-2.5" />
                            Active
                          </span>
                        )}
                      </div>
                      <p className="text-muted-foreground mt-0.5 truncate text-xs">
                        <span className="capitalize">{org.subscription_tier}</span>
                        {org.slug && <> · {org.slug}</>}
                      </p>
                    </div>
                  </div>

                  <div className="relative z-20">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      disabled={isActive}
                      onClick={() => {
                        switchOrg(org.id);
                        router.push(ROUTES.DASHBOARD);
                      }}
                    >
                      <ArrowRightLeft className="h-3.5 w-3.5" />
                      {isActive ? "Current" : "Switch"}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </WorkspacesCard>

      <CreateOrgDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => fetchOrgs(true)}
      />
    </div>
  );
}
