# Onboarding visual research

Reviewed 22 November 2026 for PR #3137. This is an internal design reference,
not a claim that these products' screens increase retention. The review inspected
actual image pixels, not just search descriptions. No accounts were created,
credentials entered, or paid screenshot galleries accessed. Reference images stay
outside the repository in `~/.local/share/agenticos-pr3137/research/`.

## Evidence and its limits

| Flow | Evidence inspected | Reliability boundary |
| --- | --- | --- |
| Notion: intent → connections → workspace | Public captured screens 03, 06, 07 and 11 in [UserOnboarding Academy's recording](https://useronboarding.academy/onboarding-teardowns/notion), dated 3 November 2026 by its publisher | Third-party recording, not a fresh authenticated walkthrough; variation by account or experiment is unknown |
| Notion: template selection → preview → use | Two screenshots published in [Notion's own template guide](https://www.notion.com/help/guides/the-ultimate-guide-to-notion-templates) | Primary product imagery, but the guide mixes older and newer interface treatments; the gallery is an activation flow, not the complete signup wizard |
| Linear Mobile: welcome → workspace → Home | Public, unlocked ScreensDesign images 12, 16 and 17 from [Linear Mobile](https://screensdesign.com/apps/linear-mobile/) | Actual captured mobile UI; capture date is not established. Official [login methods](https://linear.app/docs/login-methods) corroborate account/workspace concepts, not every pixel |
| Duolingo: introduction → language selection | Public unlocked introduction/language images in [Duolingo onboarding](https://screensdesign.com/explore/apps/duolingo/onboarding/) and [the app gallery](https://screensdesign.com/apps/duolingo-language-lessons/?vs=112650) | Captured mobile onboarding, not a measured retention experiment; static images do not establish animation timing |

## 1. Notion: one question, then usable connections

**Observed.** The intent screen has a single centered question, one supporting
sentence, three stacked choices and a small progress bar. The task screen uses
four plain rows and provides an explicit exploration path. The connection screen
has two prominent provider marks with an individual Connect action, followed by
Continue and a separate Skip. The destination is a real workspace with populated
navigation and a welcome checklist, rather than another promotional screen.
[Captured sequence](https://useronboarding.academy/onboarding-teardowns/notion).

**Apply to AgenticOS.** Keep the current question and its choices together. Offer
subscription login, a Vault model and a new API key as immediately understandable
ways to power the same agent. Use direct Connect buttons on service tiles. Make
optional MCP setup skippable. End with a runnable AgenticOS conversation or an
Architect task, using the connections actually selected.

**Do not copy.** The screenshot's additional data-sharing checkbox and multi-action
welcome checklist add competing decisions. A populated workspace alone does not
identify the best next task. Prefer one suggested first action.

Private evidence: `notion-onboarding-{03,06,07,11}.webp`.

## 2. Notion: demonstrate the result before asking for commitment

**Observed.** The in-app gallery places categories on the left and a recognizable
Tasks table on the right. The selected template's action sits beside its concise
purpose. A separate preview presents the actual project/task structure, with one
primary adoption action. The official guide describes previewing before adding a
template to a workspace. [Primary source and screenshots](https://www.notion.com/help/guides/the-ultimate-guide-to-notion-templates).

**Apply to AgenticOS.** AgenticOS and Architect should be demonstrated through
concrete task/output pairs: summarize a supplied document, compare options, or
build a first agent. Preview the kind of result while the user chooses, then open
the real agent with that task. Keep all capability/runtime implementation terms
out of this introduction. Do not fabricate a successful run or invent user data.

Private evidence: `notion-template-gallery.webp`, `notion-template-preview.webp`.

## 3. Linear Mobile: separate welcome, setup and actual work

**Observed.** Welcome shows one large product mark, a short greeting and a bottom
start action. Workspace creation uses one heading, a brief explanation and a
single group containing name, URL and hosting region. The identity being used is
visible above that form. The notification permission prompt appears over the
working Home screen, after workspace creation; the Home destinations remain
visible behind it. [Public captured flow](https://screensdesign.com/apps/linear-mobile/).

**Apply to AgenticOS.** Give identity/workspace creation their own bounded moment.
Show the organization/account the user is configuring. Delay optional device or
notification requests until their benefit is concrete. Keep primary navigation
and the first useful action discoverable after completion.

**Limit.** This does not establish that Linear's desktop wizard has the same
sequence or that all notification requests occur at this exact point. A separate
NextWork account-creation tutorial describes desktop theme/shortcut/integration
steps, but its images were not successfully inspected here; do not treat that
sequence as visual evidence.

Private evidence: `linear-{welcome,workspace,permissions}.webp`.

## 4. Duolingo: personality without competing narrators

**Observed.** The introduction gives one character and a short speech bubble ample
space. The next captured screen reduces the character beside one question and a
simple choice list. Selection has a clear blue fill and border. Continue stays in
the same bottom band while the choice list scrolls; back navigation and a thin
progress indicator occupy the top. [Public captured screens](https://screensdesign.com/explore/apps/duolingo/onboarding/).

**Apply to AgenticOS.** Use a single active companion. Keep the prompt, controls
and footer in predictable locations. A speaking/avatar transition can introduce
a question; it should not compete with a second blob, a preview, an Architect
promotion and a navigation rail simultaneously. Preserve immediate access to the
choices and Continue; reduced motion must show the final state immediately.

**Separate primary evidence.** Duolingo's [official core-tabs design article](https://blog.duolingo.com/core-tabs-redesign/)
shows consistent header placement across three different screens and explains
purposeful spacing instead of unnecessary containers. That supports stable
hierarchy; it is not evidence of this onboarding's timings or completion rate.

Private evidence: `duolingo-introduction.webp`, `duolingo-language.webp`,
`duolingo-official-headers.png`.

## Supporting references, not additional captured onboarding flows

- [Slack's workspace-creator guide](https://slack.com/help/articles/217626298-Getting-started-for-workspace-creators)
  separates customization, meaningful channels and inviting coworkers. Its images
  are simplified illustrations of product states, not raw signup screenshots.
  Useful implication: establish something worth sharing before asking for invites.
- [Figma's agent introduction](https://www.figma.com/solutions/ai-onboarding-flow-agent/)
  links a hands-on playground and shows a Start action beside a concrete example
  prompt. The inspected image is a promotional playground cover, not a verified
  live onboarding screen. It supports demonstrating a task, not copying its layout
  as evidence of an actual signup journey. Private image: `figma-agent-playground.png`.

## Implementation priorities

1. **One active decision.** One main prompt, one choice group, one primary forward
   action. Put optional supporting information below the action or behind disclosure.
2. **One companion.** Use AgenticOS to guide setup; introduce Architect through its
   own useful task, rather than keeping both mascots active on every step.
3. **Real capability early.** Connect a subscription or choose an available Vault
   model, then demonstrate what the agent can do with it. Keep API-key and MCP
   configuration accessible without requiring both.
4. **Stable motion.** Transition the question/content region; keep back/continue
   positions stable. Stop decorative movement while a form or service login needs
   attention. Static captures do not justify copying unobserved animation durations.
5. **Honest progress.** Count completed work or show the current section. Do not
   imply completion merely because a provider was selected or an OAuth tab opened.
6. **Validate our result.** Review narrow screens, long translations, keyboard
   navigation, reduced motion, connection failures and returning users. Measure
   first successful task and abandonment at connection steps before claiming gains.
