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

The recurring composer placement supports variant A below. Variants B and C are
our alternatives for evaluation, not claims about the current layouts of those
products. AgenticOS also has responsibilities these examples do not establish:
organization model profiles, personal credentials, standing tool consent and
private coding accounts must retain their existing authority checks.

The three previews reuse the existing model editor and connection forms. They
remove the second permissions selector from Chat controls; Agent rules remains
its single visible entry point. Remembered grants remain reachable separately.
No models are run automatically and no new approval authority is introduced.

| Variant | Development preview | Tradeoff |
| --- | --- | --- |
| A: composer | `/chat?layout=composer` | Model beside composing, compact connection menu. Frequent actions stay together; less width for long agent names. |
| B: header | `/chat?layout=header` | Model in a quiet fixed header, minimal composer. More writing space, but attention moves farther to change models. |
| C: floating | `/chat?layout=floating` | Small model pill floats at the top-right of the chat. No permanent header row, but overlay placement needs care on narrow screens. |

Preview URLs are development-only. The regular `/chat` and production retain
the existing layout until the maintainer chooses a variant. Remove unchosen
alternatives after that decision. Mobile, existing conversations and account
connection flows must be checked before promoting a preview to the default.
