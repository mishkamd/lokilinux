"""
LokiLinux ORM models — import all so Base.metadata tracks every table
(required for Alembic autogenerate and for app startup).
"""

from .agent import Agent, AgentHealth, AgentMetrics, AgentStatus
from .alert import Alert, AlertRule
from .audit import AuditLog, RoleAssignment, Setting, UserProfile, UserRole
from .baseline import Baseline, BaselineApproval, BaselineEffective, BaselineVersion
from .category import Category, Project
from .compliance_report import ComplianceReport
from .compliance_rule import (
    ComplianceRule,
    PolicyAssignment,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from .cve import CVE, AgentVulnerability, Package, PackageVulnerability
from .drift import DriftDetail, DriftEvent
from .file_integrity import FileChange, FileHash
from .inventory import InventoryBlob, InventoryDelta, InventorySnapshot
from .job import Job, JobResult, JobStatus
from .plugin import Plugin, PluginInstallation, PluginStatus
from .policy import Policy, PolicyAudit
from .remediation import MaintenanceWindow, RemediationAction, RemediationJob, RemediationPlan
from .rule_evaluation import ComplianceScore, RuleEvaluation

__all__ = [
    # agent
    "Agent",
    "AgentHealth",
    "AgentMetrics",
    "AgentStatus",
    # alert
    "Alert",
    "AlertRule",
    # audit
    "AuditLog",
    "RoleAssignment",
    "Setting",
    "UserProfile",
    "UserRole",
    # baseline (compliance module)
    "Baseline",
    "BaselineApproval",
    "BaselineEffective",
    "BaselineVersion",
    # category
    "Category",
    "Project",
    # compliance_rule (compliance module)
    "ComplianceRule",
    "PolicyAssignment",
    "PolicySet",
    "PolicySetRule",
    "RemediationTemplate",
    # compliance_report (compliance module)
    "ComplianceReport",
    # cve
    "AgentVulnerability",
    "CVE",
    "Package",
    "PackageVulnerability",
    # drift (compliance module)
    "DriftDetail",
    "DriftEvent",
    # file_integrity (compliance module)
    "FileChange",
    "FileHash",
    # inventory (compliance module)
    "InventoryBlob",
    "InventoryDelta",
    "InventorySnapshot",
    # job
    "Job",
    "JobResult",
    "JobStatus",
    # plugin
    "Plugin",
    "PluginInstallation",
    "PluginStatus",
    # policy
    "Policy",
    "PolicyAudit",
    # remediation (compliance module)
    "MaintenanceWindow",
    "RemediationAction",
    "RemediationJob",
    "RemediationPlan",
    # rule_evaluation (compliance module)
    "ComplianceScore",
    "RuleEvaluation",
]
