"""
LokiLinux — Compliance Reporting Engine (docs/compliance/13-OPS.md Phase 5,
05-API.md §7, 01-DATA-MODEL.md §8).

Report data is computed on demand from `rule_evaluations` (confirmed
populated by lokilinux-compliance's Ingester.evaluateRules) rather than
`compliance_scores` (declared in migration 016 but never written by
anything, the same "table exists, no writer" gap this module has hit
before for drift_events/file_hashes) — reading the real evaluation table
directly avoids depending on a second table nothing keeps in sync, and
matches this module's "coverage is real, never silently assumed" ethos.

Category mapping matches docs/compliance/07-POLICY-ENGINE.md §4 exactly,
minus `packages` — that category sources from the existing `packages`
table (package inventory), a different subsystem this report generator
doesn't reach into yet; `overall` here is the mean of the four rule-backed
categories, not all five from the full spec.
"""

import csv
import io
import json
from datetime import datetime
from uuid import UUID

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_report import ComplianceReport
from lokilinux.models.compliance_rule import ComplianceRule
from lokilinux.models.rule_evaluation import RuleEvaluation

CATEGORY_BY_DOMAIN = {
    "sshd": "security",
    "pam": "security",
    "auditd": "security",
    "sudo": "security",
    "selinux": "security",
    "firewall": "security",
    "sysctl": "configuration",
    "systemd_services": "configuration",
    "cron": "configuration",
    "login_defs": "configuration",
    "password_policy": "configuration",
    "network": "configuration",
    "time_sync": "configuration",
    "mounts": "filesystem",
    "file_integrity": "filesystem",
    "repositories": "filesystem",
    "kernel": "kernel",
    "kernel_modules": "kernel",
}


async def _latest_evaluations(db: AsyncSession, agent_id: UUID | None = None):
    """One row per (agent_id, rule_id) — the most recent verdict, since
    rule_evaluations is an append-only hypertable that can carry many
    historical rows for the same rule.
    """
    q = (
        select(RuleEvaluation, ComplianceRule.domain, ComplianceRule.severity, ComplianceRule.title)
        .join(ComplianceRule, ComplianceRule.id == RuleEvaluation.rule_id)
        .distinct(RuleEvaluation.agent_id, RuleEvaluation.rule_id)
        .order_by(RuleEvaluation.agent_id, RuleEvaluation.rule_id, RuleEvaluation.time.desc())
    )
    if agent_id:
        q = q.where(RuleEvaluation.agent_id == agent_id)
    return (await db.execute(q)).all()


async def build_fleet_summary_data(db: AsyncSession, agent_id: UUID | None = None) -> dict:
    rows = await _latest_evaluations(db, agent_id)

    category_counts: dict[str, dict[str, int]] = {}
    violations: list[dict] = []

    for evaluation, domain, severity, title in rows:
        category = CATEGORY_BY_DOMAIN.get(domain, "configuration")
        bucket = category_counts.setdefault(category, {"passed": 0, "failed": 0})
        if evaluation.result == "PASS":
            bucket["passed"] += 1
        elif evaluation.result == "FAIL":
            bucket["failed"] += 1
            violations.append(
                {
                    "agent_id": str(evaluation.agent_id),
                    "domain": domain,
                    "severity": severity,
                    "title": title,
                    "time": evaluation.time.isoformat(),
                }
            )
        # ERROR/NOT_APPLICABLE/NOT_EVALUATED excluded from both numerator and
        # denominator — same rule 08-POLICY-ENGINE.md §4 applies fleet-wide.

    categories = {}
    for category, counts in category_counts.items():
        total = counts["passed"] + counts["failed"]
        categories[category] = {
            **counts,
            "score": round(100.0 * counts["passed"] / total, 1) if total else None,
        }

    scored = [c["score"] for c in categories.values() if c["score"] is not None]
    overall_score = round(sum(scored) / len(scored), 1) if scored else None

    violations.sort(
        key=lambda v: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(v["severity"], 4)
    )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "overall_score": overall_score,
        "categories": categories,
        "top_violations": violations[:50],
        "total_rules_evaluated": len(rows),
    }


def _flatten_for_csv(data: dict) -> list[dict]:
    rows = [
        {
            "row_type": "category",
            "name": "overall",
            "score": data["overall_score"],
            "passed": "",
            "failed": "",
        }
    ]
    for name, c in data["categories"].items():
        rows.append(
            {
                "row_type": "category",
                "name": name,
                "score": c["score"],
                "passed": c["passed"],
                "failed": c["failed"],
            }
        )
    for v in data["top_violations"]:
        rows.append(
            {
                "row_type": "violation",
                "name": v["title"],
                "score": v["severity"],
                "passed": v["domain"],
                "failed": v["agent_id"],
            }
        )
    return rows


def to_json(data: dict) -> bytes:
    return json.dumps(data, indent=2).encode("utf-8")


def to_csv(data: dict) -> bytes:
    buf = io.StringIO()
    rows = _flatten_for_csv(data)
    writer = csv.DictWriter(buf, fieldnames=["row_type", "name", "score", "passed", "failed"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def to_xlsx(data: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.worksheets[
        0
    ]  # Workbook() always creates exactly one sheet — index, not .active, avoids an Optional type
    ws.title = "Compliance Report"
    ws.append(["Category", "Score", "Passed", "Failed"])
    ws.append(["overall", data["overall_score"], "", ""])
    for name, c in data["categories"].items():
        ws.append([name, c["score"], c["passed"], c["failed"]])

    ws2 = wb.create_sheet("Top Violations")
    ws2.append(["Severity", "Domain", "Title", "Agent", "Time"])
    for v in data["top_violations"]:
        ws2.append([v["severity"], v["domain"], v["title"], v["agent_id"], v["time"]])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FORMAT_CONTENT_TYPES = {
    "JSON": "application/json",
    "CSV": "text/csv",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_SERIALIZERS = {"JSON": to_json, "CSV": to_csv, "XLSX": to_xlsx}


async def generate_report(db: AsyncSession, report: ComplianceReport) -> None:
    """Runs as a FastAPI BackgroundTask (see routers/compliance/reports.py)
    — mutates and commits `report` in place, matching the same
    Job-row-as-progress-tracker pattern the ComplianceAsCode importer uses.
    """
    report.status = "GENERATING"
    await db.commit()

    try:
        if report.format == "PDF":
            raise NotImplementedError(
                "PDF export isn't implemented yet — JSON/CSV/XLSX are real, "
                "PDF needs a rendering dependency not yet added (openpyxl "
                "covers XLSX; PDF needs reportlab or similar)."
            )

        agent_id = UUID(report.params["agent_id"]) if report.params.get("agent_id") else None
        if report.report_type in ("FLEET_SUMMARY", "DATACENTER", "CUSTOM"):
            data = await build_fleet_summary_data(db, agent_id=agent_id)
        elif report.report_type == "POLICY_SET":
            # ponytail: policy-set-scoped filtering (only rules belonging to
            # one policy_set_id) isn't built — this returns the same
            # fleet-wide data as FLEET_SUMMARY today. Add a policy_set_id
            # join filter here once a report specifically for one policy
            # set is needed.
            data = await build_fleet_summary_data(db, agent_id=agent_id)
        else:
            raise ValueError(f"unknown report_type {report.report_type!r}")

        serialize = _SERIALIZERS[report.format]
        report.body = serialize(data)
        report.status = "COMPLETED"
        report.completed_at = datetime.utcnow()
        report.artifact_uri = f"/api/v1/compliance/reports/{report.id}/download"
    except Exception as exc:
        report.status = "FAILED"
        report.error_message = str(exc)
        report.completed_at = datetime.utcnow()

    await db.commit()
