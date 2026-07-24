#!/usr/bin/env python3
"""Read-only sanitized collector for CompanyQualityResearch live roadmap."""
from __future__ import annotations
import argparse, hashlib, json, os, re, sqlite3, subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
STATE_DB = Path.home() / ".hermes" / "state.db"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def extract(line_pattern: str, text: str, default=""):
    m = re.search(line_pattern, text, re.M)
    return m.group(1).strip() if m else default


def parse_ticket(path: Path, config: dict):
    text = path.read_text(encoding="utf-8")
    ticket_id = int(path.name[:2])
    title = extract(r"^#\s+T?\d{2}\s+—\s+(.+)$", text, path.stem)
    status = extract(r"^\*\*Status:\*\*\s*(.+)$", text, "unknown")
    blocked_by = extract(r"^\*\*Blocked by:\*\*\s*(.+)$", text, "")
    what = extract(r"^\*\*(?:What to build|Objective):\*\*\s*(.+)$", text, "")
    worker = extract(r"^(?:\*\*Worker ownership:\*\*|- Worker:)\s*(.+)$", text, "")
    review = extract(r"^(?:\*\*Review ownership:\*\*|- Review:)\s*(.+)$", text, "")
    criteria = re.findall(r"^- \[([ xX])\]\s+(.+)$", text, re.M)
    completed = sum(1 for mark, _ in criteria if mark.lower() == "x")
    # Drafting progress is separate from implementation progress.
    planning_progress = int(config.get("ticket_planning_progress", 60)) if "draft-for-wayne-review" in status or "owner-gate-draft" in status else (100 if "approved" in status else 20)
    integrated = ticket_id in config.get("integrated_ticket_ids", set())
    active = ticket_id == config.get("active_ticket_id")
    implementation_progress = 100 if integrated else (50 if active else 0)
    deps = []
    for raw in re.findall(r"(?<![A-Za-z0-9])T(\d{2})(?![A-Za-z0-9])", blocked_by):
        value = int(raw)
        if value < ticket_id and value not in deps:
            deps.append(value)
    return {
        "id": ticket_id,
        "key": f"T{ticket_id:02d}",
        "title": title,
        "what": what,
        "status": "integrated" if integrated else ("in_progress" if active else status),
        "blocked_by": blocked_by,
        "dependencies": deps,
        "worker": worker.split("；", 1)[0],
        "reviewers": review.split("；", 1)[0],
        "acceptance_total": len(criteria),
        "acceptance_completed": completed,
        "planning_progress": planning_progress,
        "implementation_progress": implementation_progress,
        "review_state": "integrated" if integrated else ("in_progress" if active else "planned"),
        "generation": config.get("ticket_generation", "unknown"),
        "sha256": sha256(path),
        "file": str(path),
    }


def parse_verdict(summary: str):
    first = next((x.strip() for x in summary.splitlines() if x.strip()), "")
    if "NOT_APPROVED" in first:
        return "not_approved"
    if re.search(r"\bPASS\b", first):
        return "pass"
    return "completed"


def finding_titles(summary: str):
    titles = []
    for label, code, title in re.findall(r"^###\s+(?:(Critical|Important)\s+)?([CI]\d+)\s+—\s+(.+?)\s*$", summary, re.M):
        titles.append({"severity": "critical" if code.startswith("C") or label == "Critical" else "important", "title": title.strip()})
    for label, number, title in re.findall(r"^###\s+(Critical|Important)\s+(\d+)\s+—\s+(.+?)\s*$", summary, re.M):
        titles.append({"severity": "critical" if label == "Critical" else "important", "title": title.strip()})
    for severity, title in re.findall(r"(?:^|\n)(?:##\s+(Critical|Important(?: findings)?)\s*\n+)?\s*\d+\.\s+\*\*(.+?)\*\*", summary, re.M):
        titles.append({"severity": "critical" if severity.startswith("Critical") else "important", "title": title.strip()})
    if not titles:
        for title in re.findall(r"(?:^|\n)\s*\d+\.\s+\*\*(.+?)\*\*", summary):
            titles.append({"severity": "important", "title": title.strip()})
    return titles[:12]


def full_summary(result: dict):
    path = result.get("summary_full_path")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")[:20000]
        except OSError:
            pass
    return str(result.get("summary") or "")[:20000]


def load_agents(config):
    if not STATE_DB.exists():
        return [], [{"severity":"warning","title":"Hermes state.db 不可用；agent telemetry offline"}]
    tracked = set(config.get("tracked_delegations", []))
    rows = []
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=2)
        con.row_factory = sqlite3.Row
        rows = list(con.execute("SELECT delegation_id,state,dispatched_at,completed_at,updated_at,event_json,result_json,task_json FROM async_delegations ORDER BY updated_at DESC LIMIT 120"))
        con.close()
    except Exception as exc:
        return [], [{"severity":"warning","title":f"Hermes delegation telemetry unavailable: {type(exc).__name__}"}]
    agents, findings = [], []
    for row in rows:
        blob = " ".join(str(row[k] or "") for k in ("event_json","result_json","task_json"))
        if row["delegation_id"] not in tracked and "CompanyQualityResearch" not in blob and "/CompanyQualityResearch" not in blob and "company-quality" not in blob:
            continue
        event = load_embedded(row["event_json"])
        task_meta = load_embedded(row["task_json"])
        result_json = load_embedded(row["result_json"])
        goals = event.get("goals") or task_meta.get("goals") or []
        results = event.get("results") or result_json.get("results") or []
        if not goals:
            goal = event.get("goal") or task_meta.get("goal") or "Project delegation"
            goals = [goal]
        result_by_index = {int(x.get("task_index", i)): x for i, x in enumerate(results) if isinstance(x, dict)}
        registry = config.get("delegation_registry", {}).get(row["delegation_id"], {})
        for i, goal in enumerate(goals):
            result = result_by_index.get(i, {})
            summary = full_summary(result)
            batch_terminal = row["state"] in ("completed", "failed", "cancelled")
            verdict = parse_verdict(summary) if summary else (row["state"] if batch_terminal else "running")
            status = result.get("status") or (row["state"] if batch_terminal else "running")
            role = "Reviewer" if "審查" in goal or "review" in goal.lower() else "Research/Planning Agent"
            pm_state = registry.get("pm_state") or ("review_findings" if verdict == "not_approved" else ("verified_pass" if verdict == "pass" else "awaiting_pm_verification"))
            agents.append({
                "id": f"{row['delegation_id']}:{i}",
                "delegation_id": row["delegation_id"],
                "task_index": i,
                "role": role,
                "goal": goal,
                "status": status,
                "verdict": verdict,
                "model": result.get("model") or event.get("model") or task_meta.get("model") or "inherited",
                "dispatched_at": iso(row["dispatched_at"]),
                "completed_at": iso(row["completed_at"]),
                "updated_at": iso(row["updated_at"]),
                "duration_seconds": result.get("duration_seconds"),
                "latest_report": next((x.strip() for x in summary.splitlines() if x.strip()), "尚無 final report"),
                "observed_state": status,
                "pm_verified_state": pm_state,
                "phase": registry.get("phase", "Project delegation"),
                "is_current_binding": bool(registry.get("current", False)),
                "superseded_by": registry.get("superseded_by"),
            })
            if verdict == "not_approved" and pm_state == "review_findings" and registry.get("current", False):
                for item in finding_titles(summary):
                    item.update({"delegation_id":row["delegation_id"],"task_index":i,"review":goal})
                    findings.append(item)
    agents.sort(key=lambda a: a.get("updated_at") or "", reverse=True)
    return agents[:24], findings


def load_embedded(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def iso(epoch):
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()
    except Exception:
        return None


def git_progress(root: Path):
    try:
        subjects = subprocess.run(
            ["git", "log", "--format=%s"], cwd=root, text=True,
            capture_output=True, check=True, timeout=5,
        ).stdout
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, text=True,
            capture_output=True, check=True, timeout=5,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            capture_output=True, check=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return set(), None, None, "unknown"
    integrated = {int(value) for value in re.findall(r"\bt(\d{2})\b", subjects, re.I)}
    match = re.search(r"t(\d{2})", branch, re.I)
    return integrated, (int(match.group(1)) if match else None), head, branch


def collect():
    config = load_json(CONFIG_PATH, {})
    root = Path(config.get("project_root", HERE.parents[3]))
    integrated, active_ticket, head, branch = git_progress(root)
    config["integrated_ticket_ids"] = integrated
    config["active_ticket_id"] = active_ticket
    issue_dir = Path(config.get("issue_dir") or (root / ".scratch" / "company-quality-research" / "issues"))
    tickets = [parse_ticket(p, config) for p in sorted(issue_dir.glob("*.md"))]
    ticket_by_id = {t["id"]: t for t in tickets}
    waves = []
    for wave in config.get("waves", []):
        item = dict(wave)
        item["tickets"] = [ticket_by_id[i] for i in wave.get("ticket_ids", []) if i in ticket_by_id]
        item["planning_progress"] = round(sum(t["planning_progress"] for t in item["tickets"]) / len(item["tickets"])) if item["tickets"] else 0
        item["implementation_progress"] = round(sum(t["implementation_progress"] for t in item["tickets"]) / len(item["tickets"])) if item["tickets"] else 0
        states = {ticket["review_state"] for ticket in item["tickets"]}
        item["state"] = "complete" if states == {"integrated"} else ("in_progress" if "in_progress" in states else "planned")
        waves.append(item)
    agents, findings = load_agents(config)
    active = [a for a in agents if a["observed_state"] not in ("completed","failed","cancelled","timeout","timed_out")]
    current_agents = [a for a in agents if a.get("is_current_binding")]
    verdict_counts = {key:sum(1 for a in current_agents if a["verdict"] == key) for key in ("pass","not_approved","running")}
    implementation_progress = round(100 * len(integrated) / len(tickets)) if tickets else 0
    stages = [dict(stage) for stage in config.get("planning_stages", [])]
    for stage in stages:
        if stage.get("id") == "g0":
            stage.update(progress=100, state="complete", note="Lean產品開發已由Wayne授權並進行中")
        elif stage.get("id") == "implementation":
            note = f"已整合 T01–T{max(integrated):02d}" if integrated else "尚未整合 ticket"
            stage.update(progress=implementation_progress, state="in_progress", note=note)
    planning_gates_complete = sum(1 for s in stages[:5] if s.get("state") == "complete")
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": config.get("mode", "read-only"),
        "project": config.get("project", "CompanyQualityResearch"),
        "project_root": str(root),
        "e0_authorized": bool(config.get("e0_authorized", False)),
        "g0_authorized": True,
        "control_plane": {"current_stage":"LEAN_DELIVERY", "status":"in_progress", "predecessor":"T03_INTEGRATED", "candidate_sha":head, "merged_main_sha":head, "branch":branch, "reviewers":[]},
        "bindings": config.get("bindings", {}),
        "ticket_generation": config.get("ticket_generation", "unknown"),
        "max_parallel_agents": int(config.get("max_parallel_agents", 3)),
        "review_notice": f"Git即時狀態：已整合 {len(integrated)}/{len(tickets)} tickets；目前分支 {branch}。",
        "summary": {
            "planning_gates_complete": planning_gates_complete,
            "planning_gates_total": 5,
            "ticket_count": len(tickets),
            "active_agents": len(active),
            "recent_agents": len(agents),
            "review_not_approved": verdict_counts["not_approved"],
            "review_pass": verdict_counts["pass"],
            "e0": "complete" if config.get("e0_authorized") else "not_complete",
            "g0": "authorized",
            "implementation_progress": implementation_progress,
        },
        "planning_stages": stages,
        "waves": waves,
        "tickets": tickets,
        "agents": agents,
        "review_findings": findings,
        "safety": {
            "read_only": True,
            "mutation_endpoints": 0,
            "git_initialized": (root / ".git").exists(),
            "implementation_authorized": True,
            "message": "Dashboard 唯讀；進度直接取自目前 Git 分支與 main 合併紀錄，每 5 秒更新。"
        },
        "sources": [
            {"label":"Hermes agent authority","path":str(STATE_DB),"mode":"SQLite read-only"},
            {"label":"Work-order drafts","path":str(issue_dir),"mode":"filesystem read-only"},
            {"label":"Roadmap registry","path":str(CONFIG_PATH),"mode":"local planning config"}
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(HERE / "data" / "status.json"))
    args = parser.parse_args()
    data = collect()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output":str(out),"tickets":len(data["tickets"]),"agents":len(data["agents"]),"active":data["summary"]["active_agents"],"findings":len(data["review_findings"])},ensure_ascii=False))

if __name__ == "__main__":
    main()
