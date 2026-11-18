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

## Application to AgenticOS

The first three placement-only alternatives were rejected after hands-on review:
they moved the model without considering the whole control surface. The second
round compares complete compositions and palettes, using the real editor, file
menu, agent and approval selectors, model picker, context usage, settings,
dictation and voice-call/Send controls. The call retains its real readiness and
permission behavior; an unavailable call is never simulated as enabled.

| Variant | Development preview | Composition |
| --- | --- | --- |
| Studio | `/chat?layout=studio` | Cool light workspace; agent/model metadata above the editor, file and voice actions below. |
| Canvas | `/chat?layout=canvas` | Warm paper palette; a left identity/model column beside a larger editor, with utilities underneath. |
| Command | `/chat?layout=command` | Dark graphite/green palette and monospace controls; model/usage above the prompt, execution controls below. |
| Focus | `/chat?layout=focus` | Mint palette, rounded input and separate identity/model capsules; lighter visual grouping and more whitespace. |

All four retain working account connections and standing-consent rules. Usage
is reachable directly beside the model rather than buried in settings.
Narrow screens retain the existing + sheet for secondary controls. The preview
switcher preserves the conversation query parameters when changing designs.

Preview URLs remain development-only; regular `/chat` and production retain the
current layout until a new choice. These are review compositions: before promoting
one, consolidate the chosen tokens and DOM/keyboard order, remove discarded
alternatives and verify populated conversations and mobile flows.
