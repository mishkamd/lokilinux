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
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.compliance_report import ComplianceReport
from lokilinux.models.compliance_rule import ComplianceRule, PolicySetRule
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


async def _latest_evaluations(
    db: AsyncSession, agent_id: UUID | None = None, policy_set_id: UUID | None = None
):
    """One row per (agent_id, rule_id) — the most recent verdict, since
    rule_evaluations is an append-only hypertable that can carry many
    historical rows for the same rule. policy_set_id restricts to only the
    rules that belong to that one policy set (via policy_set_rules) — the
    join a POLICY_SET-scoped report needs instead of fleet-wide data.
    """
    q = (
        select(RuleEvaluation, ComplianceRule.domain, ComplianceRule.severity, ComplianceRule.title)
        .join(ComplianceRule, ComplianceRule.id == RuleEvaluation.rule_id)
        .distinct(RuleEvaluation.agent_id, RuleEvaluation.rule_id)
        .order_by(RuleEvaluation.agent_id, RuleEvaluation.rule_id, RuleEvaluation.time.desc())
    )
    if agent_id:
        q = q.where(RuleEvaluation.agent_id == agent_id)
    if policy_set_id:
        q = q.join(PolicySetRule, PolicySetRule.rule_id == ComplianceRule.id).where(
            PolicySetRule.policy_set_id == policy_set_id
        )
    return (await db.execute(q)).all()


async def build_fleet_summary_data(
    db: AsyncSession, agent_id: UUID | None = None, policy_set_id: UUID | None = None
) -> dict:
    rows = await _latest_evaluations(db, agent_id, policy_set_id)

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


_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]
)


def to_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    overall = data["overall_score"] if data["overall_score"] is not None else "N/A"
    story = [
        Paragraph("Compliance Report", styles["Title"]),
        Paragraph(f"Generated: {data['generated_at']}", styles["Normal"]),
        Paragraph(f"Overall score: {overall}", styles["Heading2"]),
        Spacer(1, 12),
    ]

    category_rows = [["Category", "Score", "Passed", "Failed"]]
    for name, c in data["categories"].items():
        category_rows.append(
            [name, c["score"] if c["score"] is not None else "N/A", c["passed"], c["failed"]]
        )
    category_table = Table(category_rows, hAlign="LEFT")
    category_table.setStyle(_TABLE_STYLE)
    story += [category_table, Spacer(1, 20), Paragraph("Top Violations", styles["Heading2"])]

    violations = data["top_violations"]
    if violations:
        violation_rows = [["Severity", "Domain", "Title", "Agent"]]
        violation_rows += [
            [v["severity"], v["domain"], v["title"], v["agent_id"]] for v in violations
        ]
        violation_table = Table(violation_rows, hAlign="LEFT")
        violation_table.setStyle(_TABLE_STYLE)
        story.append(violation_table)
    else:
        story.append(Paragraph("No violations.", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


FORMAT_CONTENT_TYPES = {
    "JSON": "application/json",
    "CSV": "text/csv",
    "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "PDF": "application/pdf",
}

_SERIALIZERS = {"JSON": to_json, "CSV": to_csv, "XLSX": to_xlsx, "PDF": to_pdf}


async def generate_report(db: AsyncSession, report: ComplianceReport) -> None:
    """Runs as a FastAPI BackgroundTask (see routers/compliance/reports.py)
    — mutates and commits `report` in place, matching the same
    Job-row-as-progress-tracker pattern the ComplianceAsCode importer uses.
    """
    report.status = "GENERATING"
    await db.commit()

    try:
        agent_id = UUID(report.params["agent_id"]) if report.params.get("agent_id") else None
        if report.report_type == "POLICY_SET":
            if not report.params.get("policy_set_id"):
                raise ValueError("POLICY_SET reports require params.policy_set_id")
            policy_set_id = UUID(report.params["policy_set_id"])
            data = await build_fleet_summary_data(
                db, agent_id=agent_id, policy_set_id=policy_set_id
            )
        elif report.report_type in ("FLEET_SUMMARY", "DATACENTER", "CUSTOM"):
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
