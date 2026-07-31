"use client";

import { useState } from "react";
import { Check, Copy, Link2 } from "lucide-react";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAssignableRoles, useInvitations } from "@/hooks";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import type { OrgRole } from "@/types";

interface InviteLinkDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
}

/**
 * A link that admits whoever holds it.
 *
 * The flow it replaces is twenty individual invitations, each needing an
 * address somebody has to collect first. This is one URL to paste into a
 * channel.
 *
 * That convenience is exactly the risk, so the two guards are on the same
 * screen as the button rather than buried in settings: how many people it
 * admits, and whose addresses. A link with neither only holds while the URL
 * itself is treated as a secret - which a link in a channel is not - and the
 * dialog says so instead of leaving it to be worked out later.
 */
export function InviteLinkDialog({ open, onOpenChange, orgId }: InviteLinkDialogProps) {
  const { createLink } = useInvitations(orgId);
  const { copy, copied } = useCopyToClipboard();
  const assignable = useAssignableRoles();

  const [role, setRole] = useState<OrgRole>("member");
  const [maxUses, setMaxUses] = useState("25");
  const [domain, setDomain] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const close = () => {
    onOpenChange(false);
    // Cleared on the way out: reopening should not show a link somebody may
    // already have revoked, and the token is not fetchable again anyway.
    setLink(null);
    setDomain("");
    setMaxUses("25");
  };

  const submit = async () => {
    setPending(true);
    const created = await createLink({
      role,
      max_uses: maxUses.trim() === "" ? null : Number(maxUses),
      email_domain: domain.trim() || null,
    });
    setPending(false);
    if (created) setLink(created);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            Invite with a link
          </DialogTitle>
          <DialogDescription>
            One URL anybody can use to join, instead of an invitation per address. Paste it into a
            channel and it works until it expires, runs out of uses, or you revoke it.
          </DialogDescription>
        </DialogHeader>

        {link === null ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="link-role">Join as</Label>
              <Select value={role} onValueChange={(value) => setRole(value as OrgRole)}>
                <SelectTrigger id="link-role" className="capitalize">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {assignable.map((option) => (
                    <SelectItem key={option} value={option} className="capitalize">
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="link-uses">How many people</Label>
                <Input
                  id="link-uses"
                  type="number"
                  min="1"
                  max="500"
                  value={maxUses}
                  onChange={(event) => setMaxUses(event.target.value)}
                  placeholder="Unlimited"
                />
                <p className="text-muted-foreground text-xs">Empty means unlimited.</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="link-domain">Only this email domain</Label>
                <Input
                  id="link-domain"
                  value={domain}
                  onChange={(event) => setDomain(event.target.value)}
                  placeholder="acme.com"
                  className="font-mono"
                />
                <p className="text-muted-foreground text-xs">Optional, and worth setting.</p>
              </div>
            </div>

            {maxUses.trim() === "" && domain.trim() === "" && (
              <p className="text-muted-foreground border-border rounded-md border border-dashed p-3 text-xs">
                Unlimited and open to any address: whoever this URL reaches can join as{" "}
                <span className="font-medium capitalize">{role}</span>. A link forwarded out of a
                channel is still a working link.
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-muted-foreground text-sm">
              Copy it now - it is shown once, and no later request returns it.
            </p>
            <div className="flex items-start gap-2">
              <code className="bg-muted min-w-0 flex-1 overflow-x-auto rounded-md p-2 font-mono text-xs">
                {link}
              </code>
              <Button variant="outline" size="sm" onClick={() => copy(link)} aria-label="Copy link">
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        )}

        <DialogFooter>
          {link === null ? (
            <>
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button onClick={submit} disabled={pending}>
                Create link
              </Button>
            </>
          ) : (
            <Button onClick={close}>Done</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
