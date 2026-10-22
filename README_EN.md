# collab-charter · Executable Kernel of the Collaboration Charter

> 中文: [README.md](README.md) · English: this file

[![M8ven Score](https://m8ven.ai/badge/mcp/lucasdevkid9/collab-charter)](https://m8ven.ai/mcp/lucasdevkid9/collab-charter?s=readme)

> Turn a *user-side collaboration charter* from a prompt document into an
> **loadable, callable, verifiable** execution layer for AI agents.

**90 clauses · 8-stage pipeline · 14 MCP tools · 421 tests · bidirectional clause↔implementation traceability · 330-entry knowledge base**

---

## What This Is

A collaboration spec written in Markdown can only ever be "followed on a best-effort
basis" by a model. This project **compiles it into something that actually runs**:

| Charter clause | In this project |
|---|---|
| 0.3 Routing pipeline (8 stages) | `Router` class — the station set is locked to the charter by assertions; changing one side without the other fails immediately |
| 0.4 Five priority levels / 0.5 Five conflict rules | `Arbiter` class — every verdict returns the **clause id** it rests on, fully traceable |
| Chapter 10 Safety gate | `charter.yaml:enforcement.gate_matrix` (full 3×3 matrix) + `SafetyGate` table-driven execution |
| 0.6 Memory flow (deposit / reactivation / decay) | `MemoryStore` — half-life confidence decay, correction trail, JSON persistence |
| 0.8 Pre-reflow self-check (six items) | `SelfCheckRunner` — every item returns an assertable `passed` flag plus failure details |
| Chapter 11 Knowledge base & semantic field | `knowledge/*.yaml` (330 entries) + the `lexicon` toolkit: deterministic measure space, distribution weights, latent-field network analysis |
| Chapter 12 Symbolic anchoring | `anchor` package (cognitive-anchor v2.0 merged in): z3 full enumeration, AST whitelist, multi-round drift detection |
| —— | Plus: the image-prompt spec `<modular feature-cluster markup syntax>` also shipped as an executable linter |

**In one sentence**: the charter is no longer a paragraph saying "please comply" —
it is a system that can be `curl`ed, called via MCP, pinned by test assertions,
and that fails loudly the moment it is broken.

## Quick Start

### 1. Command line (zero install)

```bash
git clone https://github.com/LucasDevKid9/collab-charter && cd collab-charter

# Session start: the receipt self-check required by Chapter 1 (≤3 lines)
PYTHONPATH=src python3 -m collab_charter.cli receipt

# Full pipeline or fast path for this request?
PYTHONPATH=src python3 -m collab_charter.cli route "help me refactor this module"
# → Route(full): safety gate → intent → cognitive mirror → memory recall → role council
#   → adjudication → output → reflow

# Run the full pipeline: per-station trace + output + self-check verdict
PYTHONPATH=src python3 -m collab_charter.cli handle "refactor this module" --constraint keep the API compatible

# Look up any clause verbatim (for "show your source" requests)
PYTHONPATH=src python3 -m collab_charter.cli clause 0.5-R4

# Charter integrity self-check
PYTHONPATH=src python3 -m collab_charter.cli verify

# Knowledge base summary (Chapter 11: entry count / broken links / cross-file duplicates / unverified)
PYTHONPATH=src python3 -m collab_charter.cli kb

# Semantic-field mining: weighted entries + distribution weights + gate verdict + coverage gaps
PYTHONPATH=src python3 -m collab_charter.cli mine "谷圈 痛包 晒谷" --state 收敛期

# Latent semantic field: association network / centrality / communities / gaps
PYTHONPATH=src python3 -m collab_charter.cli field "谷圈 痛包 晒谷" --state 收敛期

# Symbolic anchoring: hand multi-condition trade-offs to z3 (requires pip install z3-solver)
PYTHONPATH=src python3 -m collab_charter.anchor \
  --declare "x:feasible,y:budget,z:time,w:risk_ok" \
  --constraints "x+y+z+w>=3; Implies(y==0,w==1)" \
  --decisions "do:x+y+z+w>=4; wait:x+y+z+w==3; skip:x+y+z+w<3" \
  --rounds "|y==0"

# Governance kernel: replay the audit ledger (every handle is recorded automatically;
# decisions stay explainable and reviewable)
PYTHONPATH=src python3 -m collab_charter.cli replay --sessions          # list audit sessions
PYTHONPATH=src python3 -m collab_charter.cli replay <session> --step    # replay event by event
PYTHONPATH=src python3 -m collab_charter.cli replay --why <decision_id> # explain one decision (why blocked/allowed)
PYTHONPATH=src python3 -m collab_charter.cli replay <session> --json    # machine-readable export

# Compile the charter into policy IR + risk overview + charter diff
# (governance kernel · P2-10 lite)
PYTHONPATH=src python3 -m collab_charter.cli policy --summary           # risk-tier overview
PYTHONPATH=src python3 -m collab_charter.cli policy --risk critical     # only critical clauses
PYTHONPATH=src python3 -m collab_charter.cli policy --diff another.yaml # charter diff (what changed)
PYTHONPATH=src python3 -m collab_charter.cli policy --json              # machine-readable export
```

### 2. Python

```python
from collab_charter import Charter, Session
from collab_charter.flows import user_instruction, model_speculation

session = Session(Charter.load())
session.register_tool(ToolSpec("web_search", "web search", my_search_fn, {"q": {"type": "string"}}))

session.ask("look up the latest tech choices for z3")
session.call_tool("web_search", q="z3 solver 2024")
out = session.handle("also assess the migration cost", constraints=["no downtime"])

print(out.text)                # output
print(out.trace)               # per-station trace (expanded when reasoning is requested)
print(out.explain_failures())  # exactly which self-check items failed, and why
```

**A note on the reflow self-check (0.8-C4)**: on the full path, `handle()` does not
auto-deposit memories by default, so 0.8-C4 ("has the feedback been reflowed?") will
show as not passed — this is a **deliberate safety gate** against writing unconfirmed
content into long-term memory. Two ways to make it pass:

```python
# Option A: explicit reflow (deposit the session's key flows)
session.reflow()
out = session.handle("confirm once more", constraints=[])

# Option B: whitelist auto-deposit (flows matching the message text or memory_key
# are stored automatically, passing the check for this run)
out = session.handle("note this: gate first, then assert", auto_deposit_keys=("gate first",))
assert out.selfcheck.passed
```

**Cognitive execution injection (agent-platform wiring point)**: `stage_hooks` applies
uniformly to **all 8 stations**; `mirror_fn` / `council_fn` let you replace the
deterministic templates for cognitive mirroring and triangular role council with real
LLM callbacks (without callbacks it falls back to the templates, staying zero-dependency):

```python
from collab_charter.router import PipelineStage

out = session.handle(
    "help me refactor this module",
    mirror_fn=lambda flows: "mirror: your implicit need is a low-risk refactor",
    council_fn=lambda flows: real_llm_council(flows),   # real triangular perspectives
    stage_hooks={PipelineStage.INTENT: tag_flows},      # intercept any station
)
```

### 3. MCP (recommended for agent platforms)

```json
{
  "mcpServers": {
    "collab-charter": {
      "command": "python3",
      "args": ["/absolute/path/collab-charter/interfaces/mcp_server.py"]
    }
  }
}
```

Zero dependencies (stdlib-only JSON-RPC over stdio) — copy it into any sandbox and
it just runs. It has passed an end-to-end smoke test with the official `mcp` SDK's
`ClientSession` (initialize → tools/list → tools/call), so it can complete a handshake
in real clients such as Claude Code / Cursor.
**14 tools**: clause lookup / clause listing / receipt self-check /
routing decision / pipeline execution / conflict arbitration / safety gate /
prompt diagnosis / memory deposit / memory recall / symbolic-anchor solving /
knowledge-base search / semantic-field mining / latent semantic field.

(`anchor_solve` needs the optional dependency `z3-solver`: `pip install collab-charter[anchor]`.
When absent it returns clear install instructions instead of breaking the other 13 tools.)

### 4. Feature-cluster prompt diagnosis

```bash
PYTHONPATH=tools python3 -m fcslint "古早立绘，半身像，赛璐璐平涂，16-bit indexed color，硬边缘，4:3"
```

Outputs six functional-cluster classification, weight-gradient deviation, conflict
list, a quantified control score (0–100), and a **structure-preserving rewrite in the
same paradigm** (reorder / down-weight / drop dead tokens / add anchors).
The lexicon is now an extensible knowledge base (`knowledge/`, 330 entries); diagnosis
and mining share the same data.

## Project Structure

```
charter/            ① Charter layer    CHARTER.md (human-readable) · charter.yaml (★SSOT) · compact.md (compact)
knowledge/          ② Knowledge layer  lexicon.yaml · styles.yaml · subcultures.yaml (330 entries, 11.1)
src/collab_charter/ ③ Kernel layer     flows · gates · router · arbiter · memory · selfcheck · session · cli
                                 · lexicon/ (knowledge toolkit) · anchor/ (symbolic solver)
                                 · governance (DecisionRecord / audit ledger) · policy_ir · sanitize
interfaces/         ④ Interface layer  mcp_server.py (zero-dependency MCP, 14 tools)
tools/              ⑤ Tool layer       fcslint/ (feature-cluster diagnosis) · anchor/solve.py (compat shim)
skills/             ⑥ Skill layer      using-charter · info-flow-protocol · feature-cluster-syntax
                                 · deep-research · authoring-skills · cognitive-anchor
harnesses/          ⑦ Adapter layer    claude/codex/cursor/gemini manifests · session-start hook · tool-mapping.md
tests/              ⑧ Verification     421 tests, incl. bidirectional clause↔implementation traceability
docs/              ANALYSIS · ARCHITECTURE · SEMANTIC-FIELD · TRACEABILITY
```

## Four Designs Worth a Look

**① Single source of truth + bidirectional traceability.** Clauses live only in
`charter/charter.yaml`, each with a globally unique id. Code declares "which clauses
I implement"; tests mechanically verify "clause exists → module exists → has a named
test", plus a **reverse check** — declaring a clause that does not exist in the
charter is rejected. See [docs/TRACEABILITY.md](docs/TRACEABILITY.md).

**② Invariants as assertions, not comments.** The charter's 0.3 defines eight
stations. Drop one in code and a naive implementation silently drifts; this project
**validates at startup** and throws on mismatch. The same technique covers gate-matrix
coverage, self-check item consistency, knowledge-base link integrity, and MCP tool count.

**③ Skills name actions, never tools.** Skills describe actions only ("look up a
clause"); platform differences converge into one mapping table,
[harnesses/tool-mapping.md](harnesses/tool-mapping.md). Adding a platform touches
**no skill and no source file** — the most important invariant in this project.

**④ Determinism over cleverness.** The vector space avoids the hashing trick
(collision noise is observable at 330 entries), community detection uses no random
initialization, and spaces are built per task and discarded after use. All in service
of 11.2-V1: same input → same output → reproducible and auditable.
See [docs/SEMANTIC-FIELD.md](docs/SEMANTIC-FIELD.md).

## Platform Integration

| Platform | How to plug in |
|---|---|
| Claude Code | `harnesses/claude-plugin/` (ships with an `mcpServers` block, install and go) |
| Codex | `harnesses/codex-plugin/` |
| Cursor | `harnesses/cursor-plugin/` + `hooks/hooks.json` |
| Gemini CLI | `harnesses/gemini-cli/GEMINI.md` (fallback for hook-less platforms) |
| Other / custom agents | `harnesses/generic/AGENTS.md` + `tool-mapping.md` |

Platform capability gaps and degradation strategies (no memory / no file access /
no network / no sub-agents) are documented in
[tool-mapping.md](harnesses/tool-mapping.md).

## Testing

```bash
python3 -m pytest -q                              # 421 tests
python3 -m pytest tests/test_traceability.py -v   # clause traceability
PYTHONPATH=src python3 -m collab_charter.cli verify
```

Requirements: Python ≥ 3.9, `pyyaml` (that is the only hard dependency; the MCP
server and fcslint core are zero-dependency). `fastapi`/`uvicorn` are optional
(HTTP interface); `z3-solver` is optional (symbolic anchoring,
`pip install collab-charter[anchor]`).

## Documentation

- [docs/ANALYSIS.md](docs/ANALYSIS.md) — evidence-based deep analysis of four source
  materials (superpowers / cognitive-core / feature-cluster spec / collaboration charter)
  with a P0–P3 defect list, plus this project's self-imposed constraints
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — seven key design decisions, trade-offs,
  and honest boundaries
- [docs/SEMANTIC-FIELD.md](docs/SEMANTIC-FIELD.md) — knowledge base / measure space /
  distribution weights / latent semantic field, in depth, with honest boundaries
- [docs/TRACEABILITY.md](docs/TRACEABILITY.md) — per-clause ownership for all 90 clauses
  (code-enforced / skill-carried)

## License

MIT, see [LICENSE](LICENSE).
