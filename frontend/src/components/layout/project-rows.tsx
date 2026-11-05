"use client";

import { ProjectAvatar } from "@/components/projects/project-avatar";

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
          "touch:min-h-11 flex h-8 items-center rounded-xl text-sm font-medium transition-colors",
          collapsed ? "touch:min-w-11 w-8 justify-center" : "gap-2.5 px-2.5",
          active
            ? "bg-foreground/8 text-foreground"
            : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
        )}
      >
        <ProjectAvatar name={project.name} />
        {collapsed ? null : <span className="truncate">{project.name}</span>}
      </Link>
    );
  });
}
