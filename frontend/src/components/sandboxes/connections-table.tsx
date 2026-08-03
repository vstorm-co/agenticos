"use client";

import { Box, Cloud, Pencil, Star, Trash2 } from "lucide-react";

import {
  Badge,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface ConnectionsTableProps {
  connections: readonly SandboxConnectionRecord[];
  onEdit: (connection: SandboxConnectionRecord) => void;
  onInspect: (connection: SandboxConnectionRecord) => void;
  onDelete: (connection: SandboxConnectionRecord) => void;
}

/** What kind of host this is, in words and an icon rather than a stored string. */
function kindLabel(kind: string): string {
  return kind === "daytona" ? "Daytona cloud" : "Container service";
}

/**
 * Where a connection points, for someone comparing rows.
 *
 * Daytona has no address of ours to show, and printing an empty cell reads as a
 * misconfiguration rather than as the answer.
 */
function addressLabel(connection: SandboxConnectionRecord): string {
  if (connection.kind === "daytona") return "their API";
  return connection.base_url ?? "—";
}

/**
 * The hosts this organization's agents can be given a workspace on.
 *
 * A table because every question asked here compares rows: which is the default,
 * which is switched off, which has a credential attached. The credential itself
 * is never a column - only whether one is there, which is the part an operator
 * can act on.
 */
export function ConnectionsTable({
  connections,
  onEdit,
  onInspect,
  onDelete,
}: ConnectionsTableProps) {
  const t = useTranslations("sandboxes.table");
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("name")}</TableHead>
          <TableHead>{t("kind")}</TableHead>
          <TableHead>{t("address")}</TableHead>
          <TableHead>{t("credential")}</TableHead>
          <TableHead>{t("defaultRuntime")}</TableHead>
          <TableHead className="text-right">{t("actions")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connections.map((connection) => (
          <TableRow key={connection.id} data-testid={`connection-${connection.id}`}>
            <TableCell>
              <div className="flex items-center gap-2">
                {connection.kind === "daytona" ? (
                  <Cloud className="text-muted-foreground h-4 w-4" aria-hidden />
                ) : (
                  <Box className="text-muted-foreground h-4 w-4" aria-hidden />
                )}
                <span className="font-medium">{connection.name}</span>
                {connection.is_default && (
                  <Badge variant="secondary" className="gap-1">
                    <Star className="h-3 w-3" aria-hidden />
                    Default
                  </Badge>
                )}
                {!connection.is_active && <Badge variant="outline">{t("off")}</Badge>}
              </div>
            </TableCell>
            <TableCell className="text-muted-foreground">{kindLabel(connection.kind)}</TableCell>
            <TableCell className="text-muted-foreground font-mono text-xs">
              {addressLabel(connection)}
            </TableCell>
            <TableCell>
              {connection.secret_id === null ? (
                // Not cosmetic: a connection with no credential resolves and
                // then refuses every session, which surfaces inside somebody's
                // conversation rather than here.
                <Badge variant="destructive">{t("missing")}</Badge>
              ) : (
                <Badge variant="secondary">{t("inTheVault")}</Badge>
              )}
            </TableCell>
            <TableCell className="text-muted-foreground font-mono text-xs">
              {connection.default_runtime ?? "the service's own"}
            </TableCell>
            <TableCell className="text-right">
              <div className="flex justify-end gap-1">
                {connection.kind !== "daytona" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onInspect(connection)}
                    aria-label={`What ${connection.name} allows`}
                  >
                    What it allows
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onEdit(connection)}
                  aria-label={`Edit ${connection.name}`}
                >
                  <Pencil className="h-4 w-4" aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onDelete(connection)}
                  aria-label={`Delete ${connection.name}`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
