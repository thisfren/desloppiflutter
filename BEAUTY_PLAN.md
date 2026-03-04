# Beauty Plan (v0.9.0)

Fixes derived from five-persona deep code review, updated for the v0.9.0 branch which has already completed significant refactoring (base→core reorg, Finding→Issue rename, facade deletions, scan orchestrator removal, plan reconciliation extraction, compatibility shim removal).

Items marked DONE were already addressed on this branch. Remaining items ordered by structural depth.

---

## DONE — Already addressed on v0.9.0

- **base/ → core/ reorganization** with subdirectories (discovery/, output/, search/, text/)
- **scoring.py and engine/work_queue.py facades deleted** — direct imports now
- **ScanOrchestrator removed** — inlined into scan command
- **Plan reconciliation extracted** to `scan/plan_reconcile.py`
- **Silent `except Exception: pass` fixed** — exceptions now properly handled
- **Finding → Issue rename** across entire codebase
- **Dead code and compatibility shims removed**

---

## REMAINING — Still needs work

### Manual addendum (2026-03-04) — beauty blockers from direct source review

These findings came from a manual line-by-line review of current source files (not tool-generated queue output).

Manual shape snapshot (non-test Python modules):
- 87 files are `>=300 LOC`
- 24 files are `>=500 LOC`

### A0. Keep the elegant parts intact

Before refactoring, preserve the modules that already feel clean:
- `desloppify/cli.py` (tight parse → runtime → dispatch flow)
- `desloppify/languages/_framework/runtime.py` and `.../base/types.py` (clear runtime contract boundary)
- small focused helpers like `engine/planning/dimension_rows.py` and `base/output/fallbacks.py`

The cleanup goal is to make more of the codebase look like these modules.

### A1. Restore module boundaries (private imports leaking across layers)

**The deeper issue:** Internal/private functions (`_name`) are imported across package boundaries and treated as public APIs. This makes refactors brittle and blurs ownership.

**Representative evidence:**
- `desloppify/state.py` imports private scoring helpers from `engine/_state/schema_scores.py`
- `app/commands/review/cmd.py` imports `_do_run_batches` from the batch orchestrator
- `app/cli_support/parser.py` imports `_add_plan_parser` from parser internals

**The fix:** Promote real public functions and stop importing private symbols across modules. Keep `_name` imports strictly intra-module or same-package-internal.

---

### A2. Split orchestration-heavy command modules

**The deeper issue:** Several command modules still mix state mutation, validation, workflow policy, and terminal UX in single files/functions, which hurts readability and testability.

**Representative evidence:**
- `app/commands/plan/triage/stages.py` (~989 LOC, many responsibilities)
- `app/commands/review/runner_process.py` (~766 LOC)
- `app/commands/review/runner_parallel.py` (~697 LOC)

**The fix:** For each, split into:
1. policy/validation functions
2. state transition/persistence functions
3. presentation/rendering functions
4. thin command entrypoint orchestrator

Keep write-side effects (`save_plan`, filesystem writes, subprocess execution) centralized and explicit.

---

### A3. Replace dict-heavy seams with typed contracts

**The deeper issue:** Critical workflows still pass large `dict[str, Any]` payloads across boundaries. This preserves flexibility but hides contract drift and weakens static guarantees.

**Representative evidence:**
- review batch normalization/merge paths in `app/commands/review/batch/core.py`
- workflow sync payload handling in `engine/_plan/stale_dimensions.py`
- language import graph/resolver payloads in `languages/_framework/treesitter/_imports.py`

**The fix:** Introduce focused TypedDict/dataclass contracts at module boundaries first (especially review import/merge and work queue items), then narrow `Any` over time.

---

### A4. Deduplicate parallel review test suites

**The deeper issue:** Review test cases are split across `tests/review/` and `tests/review/integration/` with substantial overlap and some near-identical case files, increasing maintenance cost and drift risk.

**Representative evidence:**
- `tests/review/review_commands_cases.py` vs `tests/review/integration/review_commands_cases.py`
- `tests/review/review_submodules_cases.py` equals `tests/review/integration/review_submodules_cases.py`
- similar overlap pattern in misc/coverage/work-queue case modules

**The fix:** Keep a single canonical case module per domain and keep wrappers thin. Integration wrappers should import canonical cases, not maintain forked copies.

---

### A5. Decompose tree-sitter import resolver monolith

**The deeper issue:** `languages/_framework/treesitter/_imports.py` mixes dep-graph building, multi-language import resolution rules, and module-level caching in one long module.

**Representative evidence:**
- many `resolve_<lang>_import` functions in one file
- module-level mutable `_GO_MODULE_CACHE`
- mixed responsibilities: parsing glue + language policy

**The fix:** Split into:
1. shared graph/parsing core
2. per-language resolver modules
3. explicit cache abstraction (injected or encapsulated), avoiding open mutable globals

---

### A6. Split scan/plan orchestration state machines

**The deeper issue:** Scan and planning flow logic is still concentrated in very large orchestration modules that combine policy, queue mutation, and persistence sequencing.

**Representative evidence:**
- `app/commands/scan/workflow.py` (runtime prep + scan generation + merge/persist + reminders)
- `engine/_plan/stale_dimensions.py` (stale/unscored/under-target/triage/workflow synthetic queue logic)
- `engine/_plan/auto_cluster.py` (grouping strategy + cluster lifecycle + override synchronization)

**The fix:** keep one orchestrator function per file and extract policy-specific functions into dedicated modules (`runtime`, `queue_policy`, `persistence`, `cluster_sync`). This enables focused tests and lowers change blast radius.

---

### A7. Replace runtime `assert` guards with explicit errors

**The deeper issue:** Non-test import/review paths still rely on `assert` to enforce required payload invariants. In optimized Python runs, these checks can be stripped.

**Representative evidence:**
- `app/commands/review/importing/helpers.py` (`assert normalized_issues_data is not None`, etc.)
- `intelligence/review/importing/holistic.py` (`assert issue is not None`)
- `app/commands/review/batch/core.py` (`assert issue is not None`, `assert isinstance(note_raw, dict)`)

**The fix:** Replace with explicit branches that raise domain errors (`CommandError`/`ValueError`) and preserve behavior regardless of interpreter flags.

---

### A8. Harden jscpd adapter process + hash choices

**The deeper issue:** `engine/detectors/jscpd_adapter.py` executes `npx` directly and uses SHA1 fragment keys, which repeatedly trips avoidable security/tooling concerns and weakens execution clarity.

**Representative evidence:**
- direct `subprocess.run(["npx", "--yes", "jscpd", ...])`
- `hashlib.sha1(...).hexdigest()[:16]` for cluster IDs

**The fix:** Resolve executable path deterministically, keep subprocess invocation constrained and explicit, and migrate fragment keying to a non-legacy hash (`sha256`/`blake2`) to remove recurring lint/noise debt.

---

### A9. Decompose language configuration assembly modules

**The deeper issue:** Language config modules still carry too many responsibilities (registration, detector wiring, fixers, zone rules, review hooks), making each language hard to evolve safely.

**Representative evidence:**
- `languages/typescript/__init__.py` (registration + detector/fixer assembly + zone/review constants in one file)
- similar pattern in other language `__init__.py` assembly modules

**The fix:** Move to explicit assembly layout per language (`config/registration.py`, `config/detectors.py`, `config/fixers.py`, `config/review.py`) and keep `__init__.py` as a thin wiring surface.

---

### 1. Finish core/ domain-module placement

**The deeper issue:** The core/ reorg created good subdirectories (discovery/, output/, search/, text/) but several domain-specific modules still sit at the core/ root level: `registry.py` (detector metadata), `signal_patterns.py` (detection heuristics), `skill_docs.py` (AI skill documentation), `subjective_dimensions.py`. These are domain logic, not foundation primitives.

**The fix:** Move these to the packages that own their domain:
- `registry.py` → `engine/detectors/registry.py` (detector catalog belongs with detectors)
- `signal_patterns.py` → `engine/detectors/signal_patterns.py` (detection heuristics)
- `skill_docs.py` → `app/skill_docs.py` (serves the CLI layer)
- `subjective_dimensions.py` → `engine/_scoring/subjective_dimensions.py` (scoring domain)

What stays in `core/`: enums, exceptions, config, runtime_state, tooling, and the subdirectory packages (discovery, output, search, text). Pure primitives and infrastructure.

---

### 2. Fix the circular dependency — state shouldn't compute scores

**Status on v0.9.0:** Still present. `engine/_state/scoring.py` line 286-288 still has deferred imports from `engine._scoring` to break a cycle.

**The deeper issue:** `_state/scoring.py` contains score recomputation logic (`_update_objective_health`) that needs scoring functions, but the scoring modules transitively import state types. State should load, validate, merge, and persist — not compute scores.

**The fix:** Move `_update_objective_health()` and `_recompute_stats()` into `engine/_scoring/` (e.g., `engine/_scoring/state_integration.py`). The persistence layer calls this module to recompute before writing. The deferred import disappears and dependency flow becomes strictly one-directional.

---

### 3. Delete the helpers/score.py re-export shim

**Status on v0.9.0:** Still exists. Pure re-export of `coerce_target_score` and `target_strict_score_from_config` from `core.config`.

**The fix:** Delete `app/commands/helpers/score.py`. Update all importers to import from `desloppify.core.config` directly. The project's own policy says no API backward-compat shims for an internal tool.

---

### 4. Deduplicate the assessment reset functions

**Status on v0.9.0:** Both `_reset_subjective_assessments_for_scan_reset` and `_expire_provisional_manual_override_assessments` still exist in `scan/workflow.py` with near-identical logic.

**The deeper issue:** Both iterate assessments, set score=0.0, set assessed_at/reset_by/placeholder, pop the same keys. They differ only in the filter predicate and source label.

**The fix:** Extract `_apply_assessment_reset(payload: dict, *, source: str, now: str) -> None` that performs the common mutation. Both callers become thin loops with their own filter calling this shared helper. Cuts ~30 lines of duplication.

---

### 5. Consolidate duplicated target-score constants

**Status on v0.9.0:** Still duplicated. `fallback=95.0` is hardcoded inline in multiple workflow.py calls rather than using a named constant.

**The fix:** Define `DEFAULT_TARGET_STRICT_SCORE = 95.0` once in `core/config.py`. All callers import and use it. If `intelligence/narrative/core.py` has its own copy, delete it and import from config.

---

### 6. Enforce FixResult contract

**Status on v0.9.0:** `isinstance(raw, FixResult)` check still in `fix/cmd.py`.

**The deeper issue:** fixer.fix() can return either FixResult or a raw list — a half-finished migration.

**The fix:** Audit all fixer implementations. Ensure every `fix()` method returns `FixResult`. Remove the isinstance branch. If any fixer returns a raw list, wrap it at the fixer level.

---

### 7. Create WorkQueueItem TypedDict

**Status on v0.9.0:** Work queue items still untyped `list[dict]`. `WorkQueueResult` TypedDict exists for the result shape but items themselves are anonymous dicts with ~25 implicit keys.

**The deeper issue:** The queue item contract is folklore — it exists only in the aggregate of all `.get()` calls across `_work_queue/`.

**The fix:** Define `WorkQueueItem(TypedDict, total=False)` with all known fields. Optionally `ClusterItem(TypedDict)` for cluster-specific fields. Update signatures for `build_issue_items`, `build_subjective_items`, `item_sort_key`, `_apply_plan_order`. This is type annotations only — no runtime behavior change.

---

### 8. Make concern generators data-driven

**Status on v0.9.0:** `_build_question` in concerns.py is still a chain of independent if-blocks appending strings. `_build_summary` is still branching on concern_type.

**The fix:** Define a `CONCERN_TEMPLATES` dict mapping concern type → `{summary_template, question_parts}`. Extract a `_make_concern()` factory that handles fingerprinting and dismissal checking — both `_cross_file_patterns` and `_systemic_smell_patterns` duplicate ~20 lines of Concern construction. The if-blocks in `_build_question` could become a list of `(condition, template)` tuples iterated once.

---

### 9. Formalize command options extraction

**Status on v0.9.0:** 9 getattr calls in next/cmd.py (down from 10). Pattern persists across command files.

**The deeper issue:** argparse.Namespace is untyped, and every command reinvents argument extraction with subtly different default-value patterns.

**The fix:** For the worst offenders, define a frozen dataclass with a `from_args(cls, args)` classmethod that extracts and validates once. Start with `next/cmd.py` and `review/entrypoint.py`. Expand incrementally — this doesn't need to be all-at-once.

---

### 10. Split show_score_delta into focused functions

**Status on v0.9.0:** Still a monolithic ~116-line function managing four independent display concerns.

**The fix:** Extract `_print_score_quartet()`, `_print_wontfix_gap()`, `_print_score_legend()`, `_print_integrity_warnings()`. Each becomes <25 lines. `show_score_delta` becomes a 10-line orchestrator.

---

### 11. Type the Issue detail field (incremental)

**Status on v0.9.0:** Still `detail: dict[str, Any]` (now on the `Issue` TypedDict).

**The approach:** Don't do a big-bang refactor. Instead:
1. Add a comment block in schema.py documenting known detail shapes per detector category.
2. Consider adding `detail_schema: str` to DetectorMeta in the registry.
3. Gradually type individual detector details when touching them for other reasons.

---

### 12. Complete StateModel/PlanModel TypedDicts

**The problem:** `StateModel` in `engine/_state/schema.py` lists 16 fields, but code throughout the system also accesses `state["scan_path"]`, `state["tool_hash"]`, `state["scan_completeness"]`, `state["potentials"]`, `state["codebase_metrics"]` — none of which appear in the TypedDict. Type checkers silently pass on all these accesses.

**The fix:** Audit all `state["..."]` and `plan["..."]` accesses. Add all missing fields to `StateModel` and `PlanModel` with correct types. Fields that are genuinely optional get `NotRequired[...]`. Fields present after migration but not at creation get `NotRequired[T] | None`. This is annotation-only — no runtime behavior changes.

---

### 13. Centralize per-detector configuration

**The problem:** Understanding what a single detector does requires reading 4–5 files:
- `base/registry.py` — display metadata, dimension assignment
- `engine/_scoring/policy/core.py` — scoring policy, tier, dimension
- `engine/_state/merge.py` — which detectors mark subjective dims stale
- language `_get_ts_fixers()` — which detectors have fixers

If you rename or remove a detector you must update all four manually.

**The fix:** Add a `scoring_policy`, `marks_dims_stale`, and `has_fixer` annotation directly to `DetectorMeta` in `base/registry.py`. The separate policy files read from the registry rather than redeclaring associations. This doesn't require eliminating the policy modules — just making the registry the first source to consult and keeping it authoritative.

---

### 14. Make NarrativeContext required fields explicit

**The problem:** `NarrativeContext` in `intelligence/narrative/core.py` declares all fields as `Optional` with `None` defaults, but several (e.g. `state`, `history`) are de facto required — passing `None` produces silent partial output rather than an error.

**The fix:** Use `Required[...]` for fields that must always be present. If TypedDict semantics don't allow this cleanly, split into `NarrativeInputs` (required) and `NarrativeContext` (optional overrides). Callers then get a static error when they forget a required field instead of discovering the problem at runtime.

---

### 15. Rename or split text_utils.py

**The problem:** `base/text_utils.py` contains `get_project_root()` (path resolution), `get_area()` (path manipulation), `is_numeric()` (type predicate), `read_code_snippet()` (file I/O), and `strip_c_style_comments()` (text processing). The name says "text" but most of the module is path and I/O utilities.

**The fix:** Either rename to `misc_utils.py` / `code_utils.py` that accurately reflects the mix, or split the path functions into `base/discovery/paths.py` (where path resolution already lives) and leave only the text-specific functions in `text_utils.py`. The name should match what's in the file.

---

### 16. CommandHandler type: replace Any with argparse.Namespace

**The problem:** `app/commands/registry.py` defines `CommandHandler = Callable[[Any], None]`. Every command handler actually accepts `argparse.Namespace`. The `Any` suppresses type checking on all command dispatch.

**The fix:** One-line change — `CommandHandler = Callable[[argparse.Namespace], None]`. Then mypy/pyright will catch any command that deviates from the expected signature. Fast win, zero behavior change.

---

### 17. Persistence load failures need explicit signaling

**The problem:** `engine/_state/persistence.py` load path: if JSON is corrupted, falls back to `.json.bak`, then falls back to `empty_state()` with no indication to the caller that data was lost. Callers receive a seemingly valid empty state and proceed to overwrite real data.

**The fix:** Return a `(state, LoadStatus)` pair, or raise a recoverable `StateLoadWarning` that the CLI catches and displays. At minimum, log a visible warning when falling back to backup or empty state so the user knows data was lost or recovered.

---

### DEFERRED

- **LangConfig decomposition:** Still monolithic (30+ fields). Defer until a new feature adds significant new fields.
- **Freeze mutable registries:** DETECTORS and DETECTOR_SCORING_POLICIES are still mutable module-level dicts. Defer unless test isolation issues surface.
- **ensure_state_defaults mutation signaling:** Currently mutates in-place and returns None with no indication of what changed. Could return a count of fields defaulted or a diff. Deferred because this is an internal function with a single call site.
- **discovery/ module naming:** `api.py`, `source.py`, `file_paths.py`, `paths.py` have overlapping names. Worth revisiting if the discovery package grows.

---

## Execution Order

**Phase 1 — Structural (items 1, 2, 3, 5):** Finish base/ placement, fix circular dep, delete score.py shim, consolidate constants. All module-structure work.

**Phase 2 — Scan/fix cleanup (items 4, 6, 10):** Deduplicate resets, enforce FixResult, split score display. Localized to scan/fix commands.

**Phase 3 — Type improvements (items 7, 8, 11, 12, 13, 16):** WorkQueueItem TypedDict, data-driven concerns, document detail schemas, complete StateModel/PlanModel, centralize detector config, fix CommandHandler type.

**Phase 4 — Command layer (items 9, 14):** Formalize options extraction, fix NarrativeContext required fields. Most widespread, do incrementally.

**Phase 5 — Naming and naming clarity (items 15, 17):** text_utils rename/split, persistence load signaling. Lower structural impact, do opportunistically.

**Manual addendum routing:** Run `A6` and `A9` with Phase 1 structural work, `A7` and `A8` with Phase 2 correctness hardening, and `A4` alongside Phase 5/late cleanup when test refactors are already in motion.
