---
name: agent-instructions
description: Write an agent's instructions so it does one job well - role, scope, refusals, sources and tone.
category: product
---

# Writing an agent's instructions

Instructions are the agent's job description. Write them for a capable new
colleague who knows nothing about the company.

## The five parts, in this order

1. **Who it is and for whom.** "You answer refund questions for Acme's online
   shop customers." One sentence; the audience changes every later choice.
2. **What it does.** The tasks, as verbs: answer, draft, look up, summarise.
3. **What it does not do.** Out-of-scope requests and what to say instead:
   "You do not change orders; tell the customer to reply to their order email."
4. **Where its answers come from.** "Answer only from the knowledge base. When
   it does not say, say you do not know and offer a person." Cite the document.
5. **How it sounds.** Tone, length, language: "Friendly, three sentences at most,
   in the customer's language."

## Rules that hold up

- One job per agent. Two jobs are two agents and a delegation.
- Name the refusal. An agent told what not to do and what to say instead stops
  improvising at the edge.
- Examples beat adjectives: one good answer quoted teaches more than "be concise".
- Variables keep instructions fresh: `{{today}}`, `{{user_name}}`, `{{org_name}}`.
- Short beats long. Every sentence the model reads costs on every message.

## Never

Secrets, keys or passwords in instructions; "always" rules the agent cannot
check; a list of everything the company does.
