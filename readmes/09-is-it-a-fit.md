# AgenticOS

**Open-source, self-hosted AI agents for teams.** Before you install anything, here is an honest answer to the question that matters: is it the right tool for you?

<img src="../docs/assets/screens/light/agent-builder.png" alt="The agent builder: instructions, model selection and a published version." width="100%">

## Choose it when

- **You have repeated work** with documents or tools, and someone on the team can judge whether an answer is right.
- **Your data has to stay with you**, or at least you have to decide where each piece goes.
- **Several teams need agents**, with different access, budgets and approvals, managed in one place.
- **Non-developers should build and maintain agents**, while engineers extend the platform in Python.
- **Someone can operate a self-hosted deployment**: updates, backups, keys and access.

## Look elsewhere when

- **You want a hosted service with an SLA.** AgenticOS is software you run. Vstorm can run it with you, but nothing comes with an SLA by default.
- **You need a visual drag-and-drop workflow builder today.** One is in development; agents today are configured in a builder and orchestrated through delegation, routines and the API.
- **Your security model depends on mirrored source permissions.** SharePoint or Drive ACLs are not mirrored into retrieval; you scope each source's credential and share collections instead.
- **You need native MFA, SAML or SCIM.** Use your identity provider over OIDC; SAML only through a bridge such as Keycloak.
- **You plan for thousands of users on day one.** Today it runs on one host with Docker Compose; there are no Kubernetes manifests.

## How it compares

| If you use… | AgenticOS differs because… | Read |
|---|---|---|
| ChatGPT or Claude apps | Agents for the organisation rather than seats: on your infrastructure, any model, per-agent budgets, approvals and audit. Often used side by side | [ChatGPT](https://vstorm-co.github.io/agenticos/about/chatgpt/) · [Claude apps](https://vstorm-co.github.io/agenticos/about/claude-apps/) |
| Claude Code or Codex | Those are coding agents for developers; AgenticOS runs the agents everyone else uses, configured in a browser and governed on the server | [Claude Code](https://vstorm-co.github.io/agenticos/about/claude-code/) · [Codex](https://vstorm-co.github.io/agenticos/about/codex/) |
| Copilot Studio, Gemini Enterprise | Your infrastructure and any model provider, no platform fee or credits; if you live in Microsoft 365, Copilot Studio is a natural candidate | [Copilot Studio](https://vstorm-co.github.io/agenticos/about/copilot-studio/) · [Gemini Enterprise](https://vstorm-co.github.io/agenticos/about/gemini-enterprise/) |
| n8n, Dify | Agent-first rather than canvas-first; SSO, roles, budgets, approvals and audit in the Apache-2.0 product. n8n and AgenticOS fit together well | [n8n](https://vstorm-co.github.io/agenticos/about/n8n/) · [Dify](https://vstorm-co.github.io/agenticos/about/dify/) |

[All comparisons](https://vstorm-co.github.io/agenticos/about/comparison/). Documentation comparisons, not benchmarks.

## What you get

<img src="assets/six-things.webp" alt="Six things teams do with AgenticOS." width="100%">

<img src="assets/limits.webp" alt="Eight things AgenticOS does not do today, each with the alternative." width="100%">

## Evaluate it on one task

1. Pick a task from the [29 tutorials](https://vstorm-co.github.io/agenticos/use-cases/), or one of your own whose result someone can judge.
2. Record how it is done today, the questions that decide acceptance, the model and tools.
3. Run it, then change one fact in the source and run it again before widening the scope.

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/quickstart.sh | bash
```

[Plan a rollout](https://vstorm-co.github.io/agenticos/rollout/) · [Security review](https://vstorm-co.github.io/agenticos/security/) · [Documentation](https://vstorm-co.github.io/agenticos/)

[Apache License 2.0](../LICENSE) · Built by [Vstorm](https://vstorm.co)
