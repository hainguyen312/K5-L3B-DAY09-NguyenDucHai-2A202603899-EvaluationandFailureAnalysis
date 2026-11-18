"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = _graded_ids(spec)

    # 1. Metric values must be real numbers: NaN/inf compare False with every threshold.
    for name, rep in (("PR", pr), ("baseline", base)):
        for k, v in (rep.get("metrics") or {}).items():
            if v is not None and not _finite(v):
                problems.append(f"{name} metric {k} = {v!r} is not a finite number")

    # 2. Evaluator failures, or rows where a graded metric is missing / not a bool.
    if pr.get("evaluator_failures"):
        problems.append(f"PR has {len(pr['evaluator_failures'])} evaluator failure(s): a crashed grader "
                        f"is not a pass (first: {str(pr['evaluator_failures'][0])[:80]})")
    for name, rep in (("PR", pr), ("baseline", base)):
        holes = [(r.get("item_id"), r.get("seed"), m) for r in rep.get("rows") or [] for m in graded
                 if not isinstance(r.get(m), bool)]
        if holes:
            item, seed, m = holes[0]
            problems.append(f"{name} has {len(holes)} row value(s) that are not True/False for graded "
                            f"metrics (first: {item}@{seed} {m})")

    # 3. Row count, duplicates and the (item, seed) set: no dropped, duplicated or cherry-picked rows.
    for name, rep in (("PR", pr), ("baseline", base)):
        man, rows = rep.get("manifest") or {}, rep.get("rows") or []
        want = int(man.get("items") or 0) * len(man.get("seeds") or [])
        if len(rows) != want:
            problems.append(f"{name} has {len(rows)} rows, manifest says {man.get('items')} items x "
                            f"{len(man.get('seeds') or [])} seeds = {want}")
        keys = [(r.get("item_id"), r.get("seed")) for r in rows]
        dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
        if dups:
            problems.append(f"{name} has duplicated (item, seed) rows: {dups[:3]}")
    pm, bm = pr.get("manifest") or {}, base.get("manifest") or {}
    if sorted(pm.get("seeds") or []) != sorted(bm.get("seeds") or []):
        problems.append(f"PR seeds {pm.get('seeds')} differ from baseline seeds {bm.get('seeds')}")
    if pm.get("items") != bm.get("items"):
        problems.append(f"PR covers {pm.get('items')} items, baseline {bm.get('items')}")
    pk = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    bk = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pk != bk:
        miss, extra = sorted(bk - pk, key=str), sorted(pk - bk, key=str)
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")

    # 4. Slice tags come from the labels, so they must match the baseline item by item.
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    moved = sorted({r.get("item_id") for r in pr.get("rows") or [] if r.get("item_id") in base_slices
                    and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]}, key=str)
    if moved:
        problems.append(f"slice tags of {len(moved)} item(s) differ from the baseline: {moved[:3]}")

    # 5. Reported metrics must be what the rows say (a hand-edited headline number).
    problems += _metrics_match_rows(pr, spec)

    # 6. Ratchet: on the same eval-set version the spec may only get stricter.
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _finite(v: object) -> bool:
    if isinstance(v, bool):
        return True
    return isinstance(v, (int, float)) and math.isfinite(v)


def _graded_ids(spec: dict) -> list[str]:
    """Spec metrics (and slice metrics) that a per-row grader produces."""
    from lab9.graders import GRADERS
    ids = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for sl in spec.get("slices") or []:
        m = sl.get("metric", "pass_rate")
        if m in GRADERS and m not in ids:
            ids.append(m)
    return ids


def _metrics_match_rows(pr: dict, spec: dict) -> list[str]:
    """Recompute the headline metrics from the rows with the same aggregate() the harness uses."""
    from lab9.eval import aggregate
    rows = pr.get("rows") or []
    if not rows:
        return ["PR has no rows"]
    ids = [m for m in _graded_ids(spec) if all(isinstance(r.get(m), bool) for r in rows)]
    try:
        again = aggregate([{**r, "cost": r.get("cost") or 0.0} for r in rows], ids,
                          k_values=spec.get("pass_k", []))
    except (KeyError, TypeError, ValueError) as exc:
        return [f"cannot recompute metrics from rows: {exc}"]
    checked = set(ids)
    if "pass_rate" in ids:
        checked |= {"pass_5"} | {k for k in again if k.startswith(("pass_at_", "pass_hat_"))}
    if all(isinstance(r.get("cost"), (int, float)) for r in rows):
        checked.add("cost_per_success")
    reported = pr.get("metrics") or {}
    out = []
    for k in sorted(checked):
        if k not in reported or again.get(k) is None:
            continue
        got, want = reported[k], again[k]
        if got is None or not _finite(got) or abs(float(got) - float(want)) > 1e-6:
            out.append(f"metric {k} = {got!r} but the rows give {want!r}")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                       # new eval-set version: thresholds start over (new baseline)
    out: list[str] = []
    for key in ("eval_set", "labels", "adversarial_pack"):
        if spec.get(key) != base_spec.get(key):
            out.append(f"RATCHET {key} changed {base_spec.get(key)!r} -> {spec.get(key)!r} on the same eval-set version")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    for key in ("rng", "method"):
        if bb.get(key) != sb.get(key):
            out.append(f"RATCHET bootstrap {key} changed {bb.get(key)!r} -> {sb.get(key)!r}")
    if sb.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append("RATCHET bootstrap confidence raised: a wider CI blocks fewer regressions")
    if sb.get("n_resamples", 1000) < bb.get("n_resamples", 1000):
        out.append("RATCHET bootstrap n_resamples lowered")
    dropped_k = sorted(set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []))
    if dropped_k:
        out.append(f"RATCHET pass_k dropped {dropped_k}")
    out += _ratchet_entries("metric", {m["id"]: m for m in base_spec.get("metrics") or []},
                            {m["id"]: m for m in spec.get("metrics") or []})
    key = lambda s: f"{s.get('name')}/{s.get('metric', 'pass_rate')}"
    out += _ratchet_entries("slice", {key(s): s for s in base_spec.get("slices") or []},
                            {key(s): s for s in spec.get("slices") or []})
    return out


def _ratchet_entries(kind: str, old: dict, new: dict) -> list[str]:
    out = []
    for k, o in old.items():
        n = new.get(k)
        if n is None:
            out.append(f"RATCHET {kind} {k} removed")
            continue
        if o.get("blocking") and not n.get("blocking"):
            out.append(f"RATCHET {kind} {k} is no longer blocking")
        ot = (o.get("threshold") or {}) if kind == "metric" else o
        nt = (n.get("threshold") or {}) if kind == "metric" else n
        for bound in ("max", "max_increase", "max_new_failing_items"):
            if bound in ot and (bound not in nt or nt[bound] > ot[bound]):
                out.append(f"RATCHET {kind} {k} {bound} loosened {ot[bound]} -> {nt.get(bound, 'none')}")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            out.append(f"RATCHET {kind} {k} min loosened {ot['min']} -> {nt.get('min', 'none')}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            out.append(f"RATCHET {kind} {k} dropped no_significant_drop")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl.get("metric", "pass_rate")
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                       # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
            if "max_new_failing_items" in sl:
                # Items that passed on every seed in the baseline but not any more. A fix on one item
                # can cancel a new bug on another in every mean; per item it cannot hide.
                new_fail = [k for k in keys if b[k] == 1.0 and a[k] < 1.0]
                if len(new_fail) > sl["max_new_failing_items"]:
                    verdict = "fail"
                    note = (note + f" new failing items {new_fail[:3]}").strip()
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop", "max_new_failing_items") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
