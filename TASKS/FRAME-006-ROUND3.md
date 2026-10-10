# FRAME-006 final acceptance

Authorized on 2026-10-10: restore solely from durable state; final production Controller fixture E2E; Reviewer immutability/write denial; proof/runtime compatibility; Windows link checks; recovery documents; small independent review package. No new product scope, remote, deployment, credentials, system configuration, ACL, helper or runtime changes.

Startup verified HEAD: 41fd7acaf7569d5e18c96be4f7edd614db34f28a; branch codex/engineering-v03; clean. Round1 ACCEPTED_WITH_LIMITS; Round2 ACCEPTED. Persistent authority was read from E:/零碎/native-orchestrator/DEVELOPMENT_STATE.json, consistent with the development copy.

Model policy remains config/model-policy.toml: Executor gpt-6-luna/high; fresh independent Reviewer gpt-6.1-sol/high. Target two real SDK turns, hard cap three; no downgrade. All additional cases use local Git/SQLite/fakes or zero-turn native commands.

Production one-shot fixture entry: validate_round3.py under the pinned SDK Python. Controller.submit/run_one performs leases, budget reservation, attempt/spec binding, worktree creation, SDK editing, freezing, approved native checks and independent review; Controller.promote_repo_task performs exact-candidate local promotion. Existing live evidence must never be overwritten or blindly replayed.

Proof compatibility: current repo-worktree-proof/2 includes explicit role SDK/runtime/model/effort/sandbox records, tied to hashed completed SDK evidence. Known proof/1 can be identified without mutation but requires NEEDS_RECONCILIATION. Missing fields, unknown/inconsistent versions and upgraded validator/boundary code fail closed. No default fields or hash rebinding convert old PASS into current PASS. Reconciliation requires explicit current boundary revalidation and new evidence; this release deliberately has no automatic legacy migration or model replay. Legacy text-controller proof functions remain unchanged.

Installing a new SDK/runtime alone does not change historical evidence or candidate identity. A new execution must pass existing model/sandbox preflight and native check runtime capability gates. Updating controller boundary code/source policy, changing spec/candidate/check catalog/model policy or losing evidence requires revalidation. Stored runtime versions are provenance, never silently replaced with the currently installed version.

Runtime write-denial probe uses official SDK CodexClient command/exec with sandboxPolicy readOnly and the same role overrides: read one owned marker, attempt modifying it and creating a second file, record results, remove only owned temporary bytes. Zero model turns; no third model probe if this succeeds. This proves the runtime preset under command execution; adapter tests independently prove Reviewer thread/turn selects the same preset with deny-all approvals.

Windows symlink SKIPs remain unknown. Real directory junction and committed Git mode 120000 tests are separate evidence and do not prove OS file/directory symlink support. Normal non-link repositories are the validated V1 scope.

Final acceptance is recorded in FRAME-006-ROUND3-ACCEPTANCE.json after frozen regression and real E2E. Framework expansion ends after acceptance. GitHub remote, Codex managed worktrees and Windows upstream sandbox enhancements are deferred.
