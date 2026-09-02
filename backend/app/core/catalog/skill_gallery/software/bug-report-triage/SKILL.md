---
name: Bug report triage
description: Turn a report into something reproducible, or say precisely what is missing.
category: qa
---

# Triaging a bug report

An unreproducible bug is not fixed, it is closed. The job is reproducibility.

## Establish

Exact steps in order · what happened · what was expected · environment, version
and browser · frequency — always, sometimes, once · when it started and what
changed then · does it happen for other users or other tenants.

## Classify honestly

**Bug** — it does not do what it says. **Regression** — it used to work; find the
version. **Missing feature** — it never worked; say so plainly rather than
accepting it as a bug. **Works as designed** — and the design surprised somebody,
which is worth its own ticket.

## Severity from impact and frequency

Not from how annoyed the reporter is. Say the reasoning so it can be argued
with.

## Always end with

Either a numbered reproduction, or a specific list of what is still needed. "Can
you provide more information" produces nothing.

## Never

Close for inactivity without saying what was missing, or merge two reports
because the symptoms look alike.
