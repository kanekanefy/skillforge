# Skill format

A skill is a directory containing a `SKILL.md` file:

```
my-skill/
└── SKILL.md
```

Optional sibling files (scripts, prompts, fixtures) are also supported — Claude Code loads the directory contents alongside the main markdown.

## SKILL.md structure

```markdown
---
name: my-skill
description: One sentence (ideally trigger-like — "When the user asks X, do Y.")
license: Apache-2.0
maintainer: "@your-handle"
tags: [data, sql]
cssk:
  skill_id: 01HXY...        # ULID, populated by skillforge on create/install
  version: 3                 # bumped on FIX
  parents: [01HXX...]        # populated on DERIVED
  generation: 1              # max(parents.generation) + 1, or 0 for CAPTURED/original
  category: data
  origin: derived            # original | fixed | derived | captured
---

# Body — what the agent should do

Free-form Markdown explaining when this skill applies and how. The body
becomes the "what to follow" context when an agent picks this skill.

## Output protocol (optional, but encouraged)

If you want skillforge to track effectiveness, instruct your readers
(the agent following this skill) to end their response with:

```
<sf-outcome>{"applied":true,"effective":true,"fallback":false,"skill_id":"<id>"}</sf-outcome>
```

This is required only when the skill is invoked from a Task subagent;
inline use doesn't need a marker (skillforge tracks selection via the
`sf-skill:` marker in the Task prompt).
```

## Required fields

| Field | Required? | Notes |
|---|---|---|
| `name` | yes | kebab-case, unique within your registry |
| `description` | yes | one sentence; this is what BM25 matches against |
| `license` | recommended | SPDX identifier — registries can reject PRs missing this |
| `maintainer` | recommended | GitHub handle or email |
| `tags` | optional | array; used for search filtering |
| `cssk.skill_id` | auto-set by skillforge | ULID |
| `cssk.version` | auto-set | starts at 1, +1 per FIX |
| `cssk.parents` | auto-set | for DERIVED |
| `cssk.generation` | auto-set | depth in evolution tree |
| `cssk.origin` | auto-set | one of `original|fixed|derived|captured` |

## Writing a good description

The description is the BM25 search term and the trigger signal. Treat it as a **condition + verb**:

```
✓ "When the user wants to format SQL, reformat with each clause on its own line."
✓ "Validate YAML files for syntax errors and schema mismatches."
✗ "A skill about SQL."                  ← what condition triggers it?
✗ "The best SQL formatter ever."         ← marketing, not signal
```

## Body conventions

- Start with **trigger conditions** (when does this apply?)
- Then **steps** (what to do — be specific about commands/tools)
- End with **edge cases** (what to do if X)
- Keep it under ~500 words. Longer skills are less reliably followed.

## Best practices

1. **Don't include credentials or paths to private files.** Skills are sharable; treat them like public code.
2. **Use the most specific name you can.** `git-log-explainer` beats `git-helper`.
3. **Version your changes manually if you publish.** Bump `cssk.version` and commit a changelog note when you change semantics.
4. **Test your skill on a clean install.** Run it in a fresh `~/.skillforge/skills/` to make sure it doesn't depend on side effects.

## Compatibility

skillforge's frontmatter is a strict superset of Claude Code's native skill format. If someone clones your skill without installing skillforge, Claude Code still loads it correctly — the `cssk:` section is ignored.

This is intentional: skills should outlive any one orchestration tool.
