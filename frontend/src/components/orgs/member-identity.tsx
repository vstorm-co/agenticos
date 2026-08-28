import { EntityAvatar } from "@/components/ui";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

export interface IdentifiedMember {
  user_id: string;
  email: string;
  full_name?: string | null;
}

/**
 * What to call somebody, preferring the name they gave over their address.
 *
 * The whole address when there is no name, not its local part. Stripping the
 * domain read tidily and made two people indistinguishable: `alex@corp.example`
 * and `alex@vendor.example` both drew as `alex`, and the row omits the address
 * beneath a nameless account precisely because the line above it is supposed to
 * *be* the address (#931).
 */
export function displayName(member: IdentifiedMember): string {
  return member.full_name || member.email;
}

/**
 * One person, as this application draws a person.
 *
 * The name on top and the address beneath it, with a face beside them. Both lines
 * are needed and neither alone is enough: two colleagues called Bob are told apart
 * only by the address, and an address alone reads like a database row in a place
 * somebody is choosing a *person*.
 *
 * Extracted because the members table, the admin lists and the alerts picker were
 * each drawing this from scratch - three copies of the same row, one of which had
 * drifted into showing a bare name with no way to tell two people apart.
 */
export function MemberIdentity({
  member,
  isSelf = false,
  className,
}: {
  member: IdentifiedMember;
  /** Marks the caller's own row, because "(you)" answers a question every list raises. */
  isSelf?: boolean;
  className?: string;
}) {
  const t = useTranslations("orgs");
  const name = displayName(member);

  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <EntityAvatar
        seed={member.user_id}
        name={member.full_name || member.email}
        imageSrc={`/api/users/avatar/${member.user_id}`}
        size="sm"
        className="shrink-0"
      />
      <span className="min-w-0">
        <span className="text-foreground block truncate text-sm">
          {name}
          {isSelf && <span className="text-muted-foreground"> {t("you")}</span>}
        </span>
        {/* Only when it adds something. For an account with no name the line above
            is already the address, and repeating it is a row that says one thing
            twice. */}
        {member.full_name ? (
          <span className="text-muted-foreground block truncate text-xs">{member.email}</span>
        ) : null}
      </span>
    </span>
  );
}
