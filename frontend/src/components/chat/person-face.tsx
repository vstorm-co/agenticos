import { EntityAvatar } from "@/components/ui/entity-avatar";
import type { ChatPerson } from "@/types";

/**
 * A member of the organization in a chat: their picture, or the face their id
 * draws - the same one the members page shows, so a teammate looks alike
 * wherever they turn up.
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
