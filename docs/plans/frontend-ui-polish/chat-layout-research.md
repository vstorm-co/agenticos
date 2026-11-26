# Chat layout alternatives

Research date: 2026-11-18. These observations come from the products' own help,
release notes and public interface, not from logged-in testing of every product.
Model names and plan limits are outside this comparison.

## Patterns in eight products

| Product | Documented pattern | Relevant lesson |
| --- | --- | --- |
| [ChatGPT](https://help.openai.com/en/articles/6825453-chatgpt-browser) | The April 28 release note places model selection in the composer and effort inside its menu. | Keep frequent choices near writing; group model-specific settings. |
| [Claude](https://support.claude.com/en/articles/8664678-change-the-model-effort-and-thinking-settings) | Model and effort appear next to Send; the model name opens their menu. | A short label can replace a large settings panel. |
| [Gemini](https://support.google.com/gemini/answer/18648722) | Manual model selection is at the bottom of the chat box, with an optional thinking level. | Keep the current model discoverable without covering the conversation. |
| [Perplexity](https://www.perplexity.ai/) | The public input offers mode, model, project and plugins as separate controls. [Its Labs introduction](https://www.perplexity.ai/en-GB/hub/blog/introducing-perplexity-labs) documents mode selection in the input bar. | Separate the task mode from model choice and secondary configuration. |
| [GitHub Copilot](https://docs.github.com/en/enterprise-cloud%40latest/copilot/how-tos/github-copilot-app/agent-sessions) | Model and effort dropdowns sit below the prompt field; Auto exposes the model used. | Put concise execution choices together and show what will run. |
| [LibreChat](https://www.librechat.ai/docs/features/composer) | Files/tools/skills/MCP enter through +; active tools become chips; thinking is conditional. Its [agent documentation](https://www.librechat.ai/docs/features/agents) describes agent choice in the selector or with @. | Reveal controls only when relevant; show selected context instead of permanent form sections. |
| [Open WebUI](https://docs.openwebui.com/features/workspace/models/) | Model controls appear beside the input's model selector only when the model defines them; model switching is searchable and saved with the chat. | Progressive disclosure beats an always-open configuration form. |
| [Mistral Vibe](https://docs.mistral.ai/resources/release-notes) | The September 22 note describes one Chat/Work entry point and Fast/Think selection in the message input. | Avoid asking people to navigate configuration before writing a task. |

## Accepted composition

The maintainer selected Minimal on 2026-11-19. It is now the ordinary `/chat`
layout in development and production. All query-driven alternatives, the design
switcher, draft experiment CSS and unused copy were removed. Embedded chats use
a separate context and retain their existing controls.

Files follow the agent. Chat settings, an icon-only permission shield, the context
ring and the model sit beside dictation and Send/Stop. Context percentages stay
in the details panel. The shield and model chevron reflect their selected/open
states. Empty drafts promote dictation; drafting reveals Send. The + menu keeps
less frequent actions, and read-only Inbox topics appear below a new conversation.
Calls and dictation share the composer surface and width. No paid call or model
request was used for the visual iteration.

The maintainer's Mistral reference and Codex screenshots informed the compact
menus and control grouping. Existing Radix collision, keyboard and focus behavior
remain; the chosen layout uses the account's current light/dark palette. Reduced
motion is respected. Profile suitability, credential scopes, personal connection
forms and permission gates are unchanged.
