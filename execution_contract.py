"""Read-only engineering preflight. This module never dispatches a repo task."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

CONTRACT_VERSION = "native-orchestrator.execution-contract/0.3"
POLICY_VERSION = "native-orchestrator.engineering-policy/0.3"
NATIVE_VERSIONS = {"0.160.0", "0.160.1", "0.162.0-alpha.2"}
ROLE_CAPABILITIES = {"executor": {"repo_read", "file_proposal"},
                     "reviewer": {"repo_read", "bound_review"}}
PROTECTED = {".git", ".runtime", ".codex", ".agents", ".aws", ".env", "data-live",
             "config.live.json", "config.codex.json", "config.workbuddy.json",
             "mainline.md", "development_state.json", "state.sqlite", "auth.json"}
OID = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?\Z")
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


class ContractError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ": " + detail)


def canonical_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mapping(value, fields, label, optional=()):
    if not isinstance(value, dict) or set(fields) - set(value) or set(value) - set(fields) - set(optional):
        raise ContractError("INVALID_CONTRACT", label + " has missing or unknown fields")
    return value


def text(value, label, maximum=200):
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise ContractError("INVALID_CONTRACT", label + " must be a bounded nonempty string")
    return value


def number(value, label, low=0, high=10000):
    if type(value) is not int or not low <= value <= high:
        raise ContractError("INVALID_BUDGET", label + " must be an integer within its bound")
    return value


def absolute_root(value, label):
    value = text(value, label, 4096)
    path = Path(value)
    if not path.is_absolute():
        raise ContractError("INVALID_PATH", label + " must be absolute")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise ContractError("LINKED_PATH", label + " traverses a link")
    return path.resolve()


def relative_path(value):
    value = text(value, "relative change path", 1024)
    if value.startswith("/") or ":" in value or "\\" in value or any(ord(c) < 32 for c in value):
        raise ContractError("INVALID_PATH", "Invalid relative change path")
    for part in value.split("/"):
        if part in ("", ".", "..") or part.rstrip(" .") != part or any(c in part for c in '*?<>|"'):
            raise ContractError("INVALID_PATH", "Unsafe relative change path")
        if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
            raise ContractError("INVALID_PATH", "Reserved Windows file name")
    return value


def inspect_git_input(repo_root):
    """Read Git metadata with optional locks and external filter/fsmonitor execution disabled."""
    root = absolute_root(str(repo_root), "repo_root")
    if not root.is_dir():
        raise ContractError("REPOSITORY_UNAVAILABLE", "Approved repository directory does not exist")
    executable = shutil.which("git")
    if executable is None:
        raise ContractError("REPOSITORY_UNAVAILABLE", "Git executable unavailable")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    base = [executable, "-c", "safe.directory=" + str(root), "-c", "core.fsmonitor=false", "-C", str(root)]

    def read(args, allow_empty=False):
        try:
            result = subprocess.run(base + args, env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="strict", timeout=15, check=False,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise ContractError("REPOSITORY_UNAVAILABLE", "Read-only Git inspection failed") from None
        if result.returncode not in ((0, 1) if allow_empty else (0,)):
            raise ContractError("REPOSITORY_UNAVAILABLE", "Repository metadata could not be inspected")
        return result.stdout.strip()

    top = read(["rev-parse", "--show-toplevel"])
    if Path(top).resolve() != root:
        raise ContractError("REPOSITORY_ROOT_MISMATCH", "Input is not the exact repository root")
    # A clean filter is executable repository configuration; status must not invoke it here.
    if read(["config", "--includes", "--get-regexp", r"^filter\."], allow_empty=True):
        raise ContractError("REPOSITORY_EXECUTABLE_CONFIG", "External Git filters require separate input freezing")
    head = read(["rev-parse", "HEAD"])
    tree = read(["rev-parse", "HEAD^{tree}"])
    if not OID.fullmatch(head) or not OID.fullmatch(tree):
        raise ContractError("INVALID_BASELINE", "Committed Git object IDs required")
    clean = not bool(read(["status", "--porcelain=v1", "--untracked-files=all"]))
    return {"root": str(root), "head": head.lower(), "tree": tree.lower(), "clean": clean}


def verify_evidence(receipt, label):
    if receipt.get("verification") != "VERIFIED":
        raise ContractError("CAPABILITY_UNVERIFIED", label + " capability evidence is not verified")
    sha = receipt.get("evidence_sha256")
    if not isinstance(sha, str) or not SHA256.fullmatch(sha):
        raise ContractError("CAPABILITY_UNVERIFIED", label + " capability evidence fingerprint required")


def verify_receipt(receipt, required, label):
    verify_evidence(receipt, label)
    caps = receipt.get("capabilities")
    if not isinstance(caps, list) or not all(isinstance(x, str) for x in caps) or not required <= set(caps):
        raise ContractError("CAPABILITY_UNAVAILABLE", label + " lacks a required capability")


def validate_contract(contract, policy, usage=None, repository_probe=inspect_git_input):
    """Validate against a trusted control-plane policy; caller counters are not an authority store.

    Validity only permits future pipeline preparation. Even runtime_enabled=True cannot dispatch.
    Neither model turns, approved checks, authority writes nor repository edits occur here.
    """
    mapping(contract, {"schema_version", "project_id", "task_id", "request_id", "spec_version",
                       "authorization_ref", "input", "allowed_changes", "routes", "check_ids", "budget"}, "contract")
    if contract["schema_version"] != CONTRACT_VERSION:
        raise ContractError("CONTRACT_VERSION_UNSUPPORTED", "Current engineering contract version required")
    mapping(policy, {"schema_version", "runtime_enabled", "authorization_ref", "approved_repo_roots",
                     "protected_paths", "routes", "runner", "check_catalog", "limits"}, "policy")
    if policy["schema_version"] != POLICY_VERSION or type(policy["runtime_enabled"]) is not bool:
        raise ContractError("POLICY_VERSION_UNSUPPORTED", "Current typed control-plane policy required")
    for key in ("project_id", "task_id"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", text(contract[key], key, 64)):
            raise ContractError("INVALID_CONTRACT", "Invalid task/project identity")
    text(contract["request_id"], "request_id")
    number(contract["spec_version"], "spec_version", 1)
    if text(contract["authorization_ref"], "authorization_ref", 256) != text(policy["authorization_ref"], "policy authorization", 256):
        raise ContractError("AUTHORIZATION_MISMATCH", "Task scope is not bound to the approved policy")
    mapping(contract["input"], {"repo_root", "base_commit"}, "input")
    root = absolute_root(contract["input"]["repo_root"], "repo_root")
    roots = policy["approved_repo_roots"]
    if not isinstance(roots, list) or not roots or root not in [absolute_root(x, "approved root") for x in roots]:
        raise ContractError("ROOT_NOT_AUTHORIZED", "Repository root not approved by the control plane")
    commit = contract["input"]["base_commit"]
    if not isinstance(commit, str) or not OID.fullmatch(commit):
        raise ContractError("INVALID_BASELINE", "Full committed input revision required")
    changes = contract["allowed_changes"]
    protected = policy["protected_paths"]
    if not isinstance(protected, list):
        raise ContractError("INVALID_POLICY", "Protected paths must be explicit")
    forbidden = PROTECTED | {relative_path(x).casefold() for x in protected}
    if not isinstance(changes, list) or not 1 <= len(changes) <= 50:
        raise ContractError("INVALID_PATH", "Require 1..50 exact approved change paths")
    seen = set()
    for name in changes:
        name = relative_path(name)
        folded = name.casefold()
        if folded in seen:
            raise ContractError("DUPLICATE_PATH", "Case-insensitive change path collision")
        seen.add(folded)
        if any(folded == p or folded.startswith(p + "/") or p.startswith(folded + "/") for p in forbidden):
            raise ContractError("PROTECTED_PATH", "Change path is protected controller or repository data")
        target = root.joinpath(*name.split("/"))
        if not target.resolve().is_relative_to(root):
            raise ContractError("INVALID_PATH", "Change path escapes repository")
        parts = (target, *target.parents)
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in parts):
            raise ContractError("LINKED_PATH", "Change path traverses a link")
        if target.exists() and not target.is_file():
            raise ContractError("INVALID_PATH", "Approved changes must name files, never directory replacements")
    mapping(contract["routes"], {"executor", "reviewer"}, "routes")
    mapping(policy["routes"], {"executor", "reviewer"}, "policy routes")
    for role, caps in ROLE_CAPABILITIES.items():
        wanted = mapping(contract["routes"][role], {"client", "model", "reasoning_effort", "native_version"}, role + " route")
        available = mapping(policy["routes"][role], {"client", "model", "native_version", "supported_efforts",
                           "capabilities", "verification", "evidence_sha256"}, role + " policy route")
        if wanted["client"] != "codex" or available["client"] != "codex":
            raise ContractError("NATIVE_ROUTE_UNSUPPORTED", "Engineering first version uses the existing Codex native route")
        for key in ("model", "native_version"):
            if text(wanted[key], key) != text(available[key], "verified " + key):
                raise ContractError("ROUTE_MISMATCH", "Requested route differs from the verified native route")
        if wanted["native_version"] not in NATIVE_VERSIONS:
            raise ContractError("NATIVE_VERSION_UNSUPPORTED", "Revalidate the native protocol before proceeding")
        supported = available["supported_efforts"]
        if not isinstance(supported, list) or not all(isinstance(x, str) for x in supported) or wanted["reasoning_effort"] not in supported:
            raise ContractError("EFFORT_UNAVAILABLE", "Requested native effort is not advertised")
        text(wanted["reasoning_effort"], "reasoning_effort", 32)
        verify_receipt(available, caps, role)
    runner = mapping(policy["runner"], {"capabilities", "verification", "evidence_sha256"}, "runner")
    verify_receipt(runner, {"approved_checks"}, "runner")
    catalog = policy["check_catalog"]
    ids = contract["check_ids"]
    if not isinstance(catalog, dict) or not isinstance(ids, list) or not 1 <= len(ids) <= 10:
        raise ContractError("INVALID_CHECK_CATALOG", "Explicit approved check IDs required")
    if not all(isinstance(x, str) and x for x in ids) or len(set(ids)) != len(ids):
        raise ContractError("INVALID_CHECK_CATALOG", "Check IDs must be unique nonempty strings")
    for check_id in ids:
        if check_id not in catalog:
            raise ContractError("CHECK_NOT_APPROVED", "Task cannot provide arbitrary engineering commands")
        check = mapping(catalog[check_id], {"argv", "timeout_seconds", "output_bytes_cap", "write_scope", "network", "shell",
                                          "verification", "evidence_sha256"}, "catalog check")
        verify_evidence(check, "approved check " + check_id)
        argv = check["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or not all(isinstance(x, str) and x and "\0" not in x and len(x) <= 4096 for x in argv):
            raise ContractError("INVALID_CHECK_CATALOG", "Approved argv must be a bounded list of strings")
        if not Path(argv[0]).is_absolute():
            raise ContractError("INVALID_CHECK_CATALOG", "Check executable must be an exact absolute path")
        if check["shell"] is not False or check["write_scope"] != "scratch" or check["network"] != "disabled":
            raise ContractError("UNSAFE_CHECK_POLICY", "No shell expansion, external network or evidence writes")
        number(check["timeout_seconds"], "check timeout", 1, 600)
        if type(check["output_bytes_cap"]) is not int or not 1 <= check["output_bytes_cap"] <= 1024 * 1024:
            raise ContractError("INVALID_CHECK_CATALOG", "Check capture requires a per-stream byte cap within 1..1048576")
    limits = mapping(policy["limits"], {"max_native_turns", "max_master_turns", "max_reworks", "max_reply_bytes",
                     "max_summary_chars", "max_evidence_excerpt_bytes"}, "limits")
    for key in ("max_native_turns", "max_master_turns"):
        number(limits[key], key)
    number(limits["max_reworks"], "policy max_reworks", 0, 2)
    if (number(limits["max_reply_bytes"], "max_reply_bytes", 1) > 8192
            or number(limits["max_summary_chars"], "max_summary_chars", 1) > 400
            or number(limits["max_evidence_excerpt_bytes"], "max_evidence_excerpt_bytes", 1) > 2048):
        raise ContractError("INVALID_BUDGET", "Business reply budget cannot exceed the existing hard boundaries")
    budget = mapping(contract["budget"], {"max_native_turns", "max_master_turns", "max_reworks", "planning_turns", "notification_turns"}, "budget")
    for key in ("max_native_turns", "max_master_turns", "max_reworks"):
        number(budget[key], key, 0, 2 if key == "max_reworks" else 10000)
        if budget[key] > limits[key]:
            raise ContractError("BUDGET_NOT_AUTHORIZED", "Contract cannot raise the trusted project/role limits")
    reworks = number(budget["max_reworks"], "max_reworks", 0, 2)
    masters = number(budget["planning_turns"], "planning_turns", 0, 2) + number(budget["notification_turns"], "notification_turns", 0, 2)
    usage = {} if usage is None else usage
    mapping(usage, set(), "usage", ("native_turns", "master_turns"))
    used = number(usage.get("native_turns", 0), "used native turns")
    master_used = number(usage.get("master_turns", 0), "used master turns")
    if master_used > used:
        raise ContractError("INVALID_BUDGET", "Master usage must be included in project native usage")
    minimum, worst = 2 + masters, 2 * (1 + reworks) + masters
    if used + minimum > budget["max_native_turns"] or used + worst > budget["max_native_turns"] or master_used + masters > budget["max_master_turns"]:
        raise ContractError("BUDGET_EXHAUSTED", "Remaining project/role budget cannot cover the bounded execution plan")
    probe = repository_probe(str(root))
    if not isinstance(probe, dict) or not {"root", "head", "tree", "clean"} <= set(probe):
        raise ContractError("INVALID_BASELINE", "Read-only repository probe returned invalid metadata")
    if absolute_root(probe["root"], "observed root") != root:
        raise ContractError("REPOSITORY_ROOT_MISMATCH", "Repository probe returned another root")
    if probe["clean"] is not True:
        raise ContractError("DIRTY_INPUT", "Freeze user changes explicitly; no automatic stash or commit")
    if not isinstance(probe["head"], str) or probe["head"].lower() != commit.lower() or not isinstance(probe["tree"], str) or not OID.fullmatch(probe["tree"]):
        raise ContractError("BASELINE_CHANGED", "Committed input differs from the requested baseline")
    return {"status": "CONTRACT_VALIDATED", "dispatchable": False, "runtime_state": "REPO_PIPELINE_NOT_IMPLEMENTED",
            "contract_hash": canonical_hash(contract), "policy_hash": canonical_hash(policy),
            "input_hash": canonical_hash({"root": str(root), "head": probe["head"].lower(), "tree": probe["tree"].lower()}),
            "minimum_native_turns": minimum, "worst_case_native_turns": worst,
            "task_id": contract["task_id"], "project_id": contract["project_id"],
            "native_calls": 0, "authority_writes": 0}


def main():
    parser = argparse.ArgumentParser(description="Read-only engineering contract preflight; never dispatches")
    parser.add_argument("contract")
    parser.add_argument("--policy", required=True, help="Trusted control-plane policy, never task-supplied authority")
    parser.add_argument("--usage", help="Read-only control-plane usage snapshot; validation does not reserve budget")
    args = parser.parse_args()
    try:
        load = lambda name: json.loads(Path(name).read_text(encoding="utf-8-sig"))
        result = validate_contract(load(args.contract), load(args.policy), load(args.usage) if args.usage else None)
        print(json.dumps(result, ensure_ascii=True))
    except (ContractError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "dispatchable": False,
                          "code": getattr(error, "code", "INVALID_INPUT"), "detail": str(error)[:300]}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
