# Mycelium skills

Claude Code skills for agents connected to a Mycelium server. Each skill says
when to use it; Claude loads it when a task matches, or you invoke it as
`/mycelium:<skill>`.

| Skill | Use it to | Needs |
|---|---|---|
| `mycelium-knowledge-source` | Answer product questions from the knowledge base, cite the statements an answer rests on, report what is missing | Any connection |
| `mycelium-authoring` | Write descriptive knowledge: what the product does and what holds, as statements, links and concepts | Writer, or drafter for drafts |
| `mycelium-guide-authoring` | Write how-to guides and troubleshooting trees (procedures, actions, checks, causes); load with `mycelium-authoring` | Writer, or drafter for drafts |
| `mycelium-draft` | Research a domain in a codebase and propose it as a submitted draft for the internal reviewer | Drafter token |
| `mycelium-draft-review` | Work the draft queue alongside the internal reviewer and recommend approve, reject, answer or correct | Real writer or admin |
| `mycelium-agent-tasks` | Do the work an action set to External agent queues: write, review and plan documentation, label audiences | Real writer or admin |
| `mycelium-documentation` | Have the server write, revise and plan documents from the knowledge base | Real writer or admin |
| `mycelium-curation` | Read knowledge health, run the connect pass, consolidate duplicates, triage knowledge gaps | Reader to look; writer, admin or curator to fix |
| `mycelium-code-curation` | From a product's repository, claim curation work, check it against the code and propose links, concepts and corrections with code evidence | Drafter token |

## Install

In Claude Code:

```text
/plugin marketplace add realDragonium/mycelium
/plugin install mycelium@mycelium
```

Then connect the server over MCP; its **Connect** page (`https://<host>/connect`)
has the command for your client. The skills name only the tools your
connection's role can see, and say so when a step needs more.

## In this repository

These directories are the only copy. `.claude/skills/<name>` links to
`skills/<name>`, so a session in a checkout loads the same skills, and
`tests/test_skills.py` fails when a skill names a tool, parameter or route the
server does not have.
