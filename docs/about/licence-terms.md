---
title: "Licence terms compared"
seo_title: "Licence terms compared: open-source AI agent platforms"
description: "Which AI agent platforms are open source without conditions? Compare Apache-2.0 with modified Apache, Elastic License 2.0, Sustainable Use and ee directories."
---

# Licence terms compared

"Open source" on a product page often means public code with conditions attached. For a company that wants to modify the software, or an integrator that wants to host one instance for several clients, those conditions decide what is allowed. This page sorts the platforms in these comparisons by what their licence lets you do, with the clause that matters quoted or summarized from the licence file.

Maintained by the AgenticOS team. Licence files checked 26 November 2026 in each project's main repository. This is a summary for orientation, not legal advice; read the licence itself before relying on it.

## The classes at a glance

| Class | What it lets you do | Projects |
| --- | --- | --- |
| Permissive OSI licence, nothing held back | Use, modify, brand and host for others | **AgenticOS** (Apache-2.0), Agno framework, Sim, OpenAgents, RAGFlow, LangBot (Apache-2.0); LibreChat core, AnythingLLM, Langflow, Hermes Agent, OpenClaw (MIT) |
| Copyleft | Use and modify; distributed changes, and for AGPL network use, must be shared under the same licence | OpenHuman, MaxKB (GPL-3.0); Khoj, Cherry Studio, Nextcloud (AGPL-3.0); LibreChat's admin panel (AGPL-3.0) |
| Open core with an enterprise directory | The core is permissive; features in `ee` or `enterprise` directories need a commercial licence | Onyx, LiteLLM, Langfuse, Activepieces, Chatwoot, Mastra, Windmill |
| Modified Apache 2.0 | Apache 2.0 plus conditions on multi-tenant use or branding | Dify, FastGPT |
| Source-available | Public code under terms that forbid competing or hosted use | Kortix CompanyOS (Elastic License 2.0), n8n (Sustainable Use License), AutoGPT Platform (Polyform Shield), Arize Phoenix (Elastic License 2.0) |
| Custom licence with conditions | Public code with commercial or branding conditions added | LobeHub (LobeHub Community License), Open WebUI (BSD-3 with a branding clause), NocoBase (its own licence agreement) |

Among the open-source platforms for company agents and the self-hosted builders, a licence with no conditions and no enterprise directory is the minority.

## The clauses that matter

### Kortix CompanyOS: Elastic License 2.0

You may not provide the software to third parties as a hosted or managed service, and you may not move, change, disable or circumvent its licence-key functionality. The repository was Apache-2.0 until December 2025 and moved to the Elastic License 2.0 on 18 February 2026. See [AgenticOS vs Kortix](kortix.md).

### Dify: Apache 2.0 with conditions

Operating a multi-tenant environment, where one tenant is one workspace, needs written permission, and the logo and copyright information in the frontend may not be removed or changed. See [AgenticOS vs Dify](dify.md).

### n8n: Sustainable Use License

Use is limited to internal business purposes, non-commercial or personal use. Paid features sit in `.ee.` files and need a licence key. See [AgenticOS vs n8n](n8n.md).

### LobeHub: LobeHub Community License

Commercial use is allowed as a frontend and backend service without modifying the source code. Developing and distributing a derivative work needs a commercial licence, and contributors agree that the producer may make the terms stricter. See [AgenticOS vs LobeHub](lobehub.md).

### Open WebUI: BSD-3 with a branding clause

Changing or removing its branding is allowed only for deployments with up to 50 users in a 30-day period; beyond that, an enterprise licence is needed. See [AgenticOS vs Open WebUI and LibreChat](open-webui-librechat.md).

### Onyx, LiteLLM, Langfuse: enterprise directories

The core is MIT. Code in the `ee` or `enterprise` directories is under a commercial licence; for Onyx, production use of it needs a licence for the number of seats. That is usually where single sign-on, SCIM, custom roles and audit features sit. See [AgenticOS vs Onyx](onyx.md) and [AgenticOS vs a DIY stack](diy-stack.md).

### AutoGPT Platform: Polyform Shield

The `autogpt_platform` directory is under the Polyform Shield licence, which forbids using it to compete with the licensor; the rest of the repository is MIT.

## AgenticOS

AgenticOS is Apache-2.0, with no enterprise directory and no feature held back for a paid edition. You may modify it, brand it as your own and run it for other organizations from one deployment. Some bundled components carry their own licences: the default PDF parser is AGPL-3.0, so a modified image you serve to others owes them its source. The [licences page](../licenses.md) lists every component and [the AGPL component](../licenses.md#the-agpl-component) explains the exception.

## Frequently asked questions

### Which AI agent platforms are fully open source?

Among those compared here, AgenticOS, Agno's framework, Sim, OpenAgents, LibreChat's core, AnythingLLM and Langflow use OSI licences without an enterprise directory. Dify, n8n, Kortix, LobeHub and Open WebUI add conditions.

### Can an integrator host AgenticOS for several clients?

Yes. Apache-2.0 allows it, and organizations in one deployment are isolated tenants. Dify's and FastGPT's licences require permission for multi-tenant use, and the Elastic License 2.0 forbids offering Kortix as a hosted service.

### Does this page replace a legal review?

No. Licences change, as Kortix's did three times in a year. Read the licence file of the version you deploy.

## Related comparisons

[All comparisons](comparison.md) · [Licences of AgenticOS components](../licenses.md)

## Sources

- [Kortix licence](https://github.com/kortix-ai/CompanyOS/blob/main/LICENSE) · [Dify licence](https://github.com/langgenius/dify/blob/main/LICENSE) · [n8n licence](https://github.com/n8n-io/n8n/blob/master/LICENSE.md)
- [LobeHub licence](https://github.com/lobehub/lobehub/blob/main/LICENSE) · [Open WebUI licence](https://docs.openwebui.com/license) · [Onyx licence](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE)
- [Langfuse licence](https://github.com/langfuse/langfuse/blob/main/LICENSE) · [LiteLLM enterprise](https://docs.litellm.ai/docs/enterprise) · [AutoGPT licence](https://github.com/Significant-Gravitas/AutoGPT/blob/master/LICENSE)
