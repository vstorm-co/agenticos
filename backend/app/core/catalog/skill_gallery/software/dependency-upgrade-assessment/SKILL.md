---
name: Dependency upgrade assessment
description: Judge whether an upgrade is safe, and say what to test.
category: engineering
---

# Assessing a dependency upgrade

Two questions: what breaks, and what happens if we do nothing.

## Read in this order

The changelog between the two versions — every one, not just the latest ·
breaking changes and deprecations · security advisories fixed · whether the
minimum runtime version moved · transitive dependency changes.

## Classify

**Security** — has a deadline, and it is short. **Breaking** — needs code
changes; list them with file paths. **Routine** — batch it.

## Say what to test

Name the specific paths this dependency is on. "Run the suite" is not an
assessment — the suite passing is necessary and, for a library that changes
behaviour rather than signatures, not sufficient.

## Always report the cost of waiting

Version drift compounds. Four majors behind is a project; one is an afternoon.
Say which this is becoming.

## Never

Upgrade a major version in the same change as a feature, or trust a green suite
on a library whose defaults changed.
