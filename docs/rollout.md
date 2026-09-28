---
title: "Deploy and operate AgenticOS"
description: "Assign ownership, understand operating costs and scope implementation help."
---

# Deploy and operate AgenticOS

AgenticOS is an application your organization operates. Start with [one checkable task](howto/first-document-agent.md), then decide who maintains the deployment and who owns the agent's work.

## Who maintains what

| Area | Operating responsibility |
| --- | --- |
| Hosting and updates | Deploy services, monitor capacity, review releases and plan upgrades |
| Backup and recovery | Back up databases and required workspace data, protect keys and test restoration |
| Sources and behavior | Keep documents, instructions, skills and published versions current |
| Access and secrets | Maintain identities, resource grants, provider credentials and rotation |
| Failures and approvals | Inspect runs, route incidents and assign authorized decision makers |
| External services | Review model, parser, embedding, tool, sandbox, channel and tracing destinations |

Use [installation](install.md), [deployment](deployment.md), [secrets](secrets.md), [permissions](permissions.md) and [security](security.md) for implementation details. Keep restore evidence and operating contacts with your deployment. A published agent does not replace that work.

## Costs and delivery options

Count model usage, infrastructure, external services, implementation and ongoing operating time. Recorded run spend is only part of that total. Check the [project and component licences](licenses.md) for your deployment.

You can operate AgenticOS yourself. Vstorm can separately help with deployment in client infrastructure, documentation, process creation and custom development. An ongoing maintenance service requires an agreed scope and responsibilities. No standard price, included support or SLA follows from installing the open-source project.

For implementation help, contact [Vstorm](https://vstorm.co/) or Kacper with the task, source types, infrastructure constraints and operating owner. Private documents are not needed for the first conversation.

<span id="what-your-security-review-will-ask"></span>

## Boundaries to verify

Self-hosting does not mean offline operation. A local chat model changes one data path; parsing, embeddings, tools, hosted sandboxes, channels and tracing may still use external services. Review the [data-flow statement](security.md).

Approval coverage depends on the selected capability and configuration. Budget checks use recorded spend before a model call and do not guarantee zero overshoot. Collection grants do not establish inheritance of every source system's document ACLs. Test the actual identities and task, using [governance](governance.md) and [collection access](file-processing.md).

## Evaluate the pilot

Record the current way of doing the task, acceptance questions, source version, model, tools and actual results. Include missing information, failed runs, review effort and usage. Change one source fact and repeat before expanding the scope.

Use [comparisons](about/comparison.md) when selecting a platform and [help](help.md) for reproducible problems. A pilot can justify extending, fixing or stopping a use case; it is not a promised business outcome.
