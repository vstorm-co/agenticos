import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Two letters for a face nobody uploaded.
 *
 * Splits on whitespace *and* `@`, so an account with no name still gets initials
 * from the local part of its address rather than one letter from "kacper@vstorm.co".
 */
export function initialsOf(nameOrEmail: string): string {
  return (
    nameOrEmail
      .split(/[\s@]/)
      .filter((part) => part.length > 0)
      .slice(0, 2)
      // `charAt`, not `[0]`: it returns a string for any index, so there is no
      // impossible-empty case to guard against and no dead branch to leave behind.
      .map((part) => part.charAt(0).toUpperCase())
      .join("")
  );
}

export interface IdentifiedMember {
  user_id: string;
  email: string;
  full_name?: string | null;
}

/** What to call somebody, preferring the name they gave over their address. */
export function displayName(member: IdentifiedMember): string {
  // The address without its domain, by removing the domain rather than by indexing a
  // split - which would need a fallback for an element that always exists.
  return member.full_name || member.email.replace(/@.*$/, "");
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
  const name = displayName(member);

  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <Avatar className="h-7 w-7 shrink-0">
        <AvatarImage src={`/api/users/avatar/${member.user_id}`} alt="" />
        <AvatarFallback className="text-[10px]">
          {initialsOf(member.full_name || member.email)}
        </AvatarFallback>
      </Avatar>
      <span className="min-w-0">
        <span className="text-foreground block truncate text-sm">
          {name}
          {isSelf && <span className="text-muted-foreground"> (you)</span>}
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
