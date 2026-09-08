# Open decisions — Ryan and Vincent

Decisions that need both of you. Each one is stated as a fork, not a
recommendation. Nothing here is acted on until you agree.

Sourced from the WeChat thread, 2026-01-01 to 2026-08-28. The record ends as your
2026-08-28 Zoom call begins, so anything settled in that call is not reflected here.

---

## 1. Auto-trading contradicts the system's first hard constraint

**Status: open. Blocking nothing today, blocking a lot later.**

Vincent, 2026-07-31:

> 「我用queatrade前几天大版本更新 可以接ai了…我在想可以把做dashboard的计算逻辑结合
> 这样可以ai可以自动在平台交易」

`MARKET_OPPORTUNITY_SYSTEM_SPEC.md` §2, hard constraint 1:

> **The system must not place trades.**

That is not a gap to fill. It is a designed-in limit, repeated in §2 non-goals ("No
trade execution, order routing, or brokerage integration") and in the
`execution-engine` boundary, which is specified as a consumer contract and explicitly
not a trading bot.

The three ways out:

| Option | What it means | Cost |
|---|---|---|
| **Keep the ban** | The engine emits decisions. A human places every order. | Vincent does not get the thing he asked for. |
| **Read-only broker bridge** | Import Questrade positions so analysis runs against real holdings. Still no order path. | Serves most of the intent. Needs OAuth and a token store. |
| **Lift the ban** | Add an execution path behind explicit per-order confirmation. | Changes the project's risk profile, its legal exposure, and constraint 1. Not reversible by a later edit. |

**What is needed:** a decision from both of you, not a default. If the ban is lifted,
it must be lifted in the spec first, deliberately, with the reason written down.

Related, unresolved: Ryan asked on 2026-08-09 whether Questrade even exposes an API
(「你有查过Questrade有吗？」). No answer appears in the record.

---

## 2. Delivery shape — web app, or scheduled agent task

**Status: open.**

Vincent, 2026-08-02:

> 「现在这个股票分析 除了html弄成网页 能有其他方式能做吗。做的要找数据api 有些找不到不太稳定。
> 能不能直接在codex里面的Scheduled tasks 把要求告诉他 他来给结果。因为本质还是固定code算法推荐」

He is making a real argument: if the output is a deterministic algorithm's
recommendation, the web UI may be overhead, and unstable data APIs may be avoidable
by letting an agent fetch on demand.

The counter-argument is already in the repo. Spec §2 constraint 3 forbids the LLM
from computing any indicator or score. An agent that "just gets the result" either
computes the numbers itself, which the spec forbids, or calls the same APIs, which
solves nothing.

The middle path nobody has costed: keep the deterministic engine, drop the interactive
UI, and deliver a scheduled digest. Worth pricing before either of you builds more UI.

---

## 3. Two engines, one contract — is `decision.v1` agreed?

**Status: blocked on Vincent.**

Branch `consolidation/decision-v1` holds a finished contract (21 schema checks, 12
invariant checks, all green) meant to let both engines exchange a decision without
either changing internally. Its own handover names the blocker:

> **Vincent has never seen any of this.** Every vocabulary here was read off his
> `AGENTS.md` and engine source, never agreed with him.

Three smaller items behind it, from that same handover:

- `reduceRange` has no source in this repo. Five of the eight price states need it.
- `confidence` is 0.0–1.0 here and 0–100 in the contract. A mapping that forgets to
  rescale produces `0.7` where `70` was meant, and looks plausible.
- `accumulate` and `trim` have no source at all in `analyst_service`.

Your 2026-08-28 call may have settled the first point. If it did, write the outcome
into `CONSOLIDATION-LOOP.md` before extending that branch.

---

## 4. Horizon mismatch between the two of you

**Status: probably already agreed, worth confirming.**

Vincent, 2026-06-15, on whether the tool needs live data:

> 「我觉得咱如果是中长线就没问题 不差那一天…就至少持有一季度那种」

The repo agrees — spec §2 makes speed explicitly secondary. But the engine's
`Horizon` enum is `1D | 1W | 2-4W | 3-6M`, and the default target window for
evaluation is `1M`. If the shared use case is "hold at least a quarter", the default
horizon should probably be `3-6M`, and the track-record report should lead with the
3M column rather than 1M.

Cheap to change, but it changes what every past recommendation is scored against, so
it should be a decision rather than a drive-by edit.
