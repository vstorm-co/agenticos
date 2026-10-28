import { EntityAvatar } from "@/components/ui/entity-avatar";
import type { ChatPerson } from "@/types";

/**
 * A member in a chat wears the same photo or initials as on the members page.
 */
export function PersonFace({ person, className }: { person: ChatPerson; className?: string }) {
  return (
    <EntityAvatar
      seed={person.user_id}
      name={person.name}
      imageSrc={`/api/users/avatar/${person.user_id}`}
      hasImage={person.has_avatar}
      colorSlot={person.avatar_color}
      ariaHidden
      className={className}
    />
  );
}
