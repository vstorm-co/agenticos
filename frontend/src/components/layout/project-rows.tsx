"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useProjects } from "@/hooks/use-projects";
import { usePermissions } from "@/hooks/use-permissions";
import { stripLocale } from "@/lib/active-route";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";

/** How many projects the column lists before "All projects" takes over. */
const SHOWN = 5;

/**
 * The reader's most recent projects, one row each, above "All projects".
 *
 * Each is a tile with its initial and its name - the tile alone on the rail,
 * where the row keeps its height so the column and the rail line up.
 */
export function ProjectRows({
  onNavigate,
  collapsed,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
}) {
  const { can } = usePermissions();
  const pathname = stripLocale(usePathname());
  const { projects } = useProjects({ limit: SHOWN, enabled: can(Perm.projectsView) });

  return projects.map((project) => {
    const href = ROUTES.PROJECT_DETAIL(project.id);
    const active = pathname === href || pathname.startsWith(`${href}/`);
    return (
      <Link
        key={project.id}
        href={href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        title={collapsed ? project.name : undefined}
        aria-label={collapsed ? project.name : undefined}
        className={cn(
          "flex h-8 items-center rounded-lg text-sm font-medium transition-colors",
          collapsed ? "w-9 justify-center" : "gap-2.5 px-2.5",
          active
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
        )}
      >
        <span
          aria-hidden
          className="bg-foreground/[0.07] text-foreground flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] text-[10px] leading-none font-semibold"
        >
          {project.name.trim().charAt(0).toUpperCase()}
        </span>
        {collapsed ? null : <span className="truncate">{project.name}</span>}
      </Link>
    );
  });
}
