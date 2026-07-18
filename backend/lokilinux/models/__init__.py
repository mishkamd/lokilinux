"""
LokiLinux ORM models — import all so Base.metadata tracks every table
(required for Alembic autogenerate and for app startup).
"""

from .agent import Agent, AgentHealth, AgentMetrics, AgentStatus
from .alert import Alert, AlertRule
from .audit import AuditLog, RoleAssignment, Setting, UserProfile, UserRole
from .category import Category, Project
from .cve import AgentVulnerability, CVE, Package, PackageVulnerability
from .job import Job, JobResult, JobStatus
from .plugin import Plugin, PluginInstallation, PluginStatus
from .policy import Policy, PolicyAudit

__all__ = [
    # agent
    "Agent", "AgentHealth", "AgentMetrics", "AgentStatus",
    # alert
    "Alert", "AlertRule",
    # audit
    "AuditLog", "RoleAssignment", "Setting", "UserProfile", "UserRole",
    # category
    "Category", "Project",
    # cve
    "AgentVulnerability", "CVE", "Package", "PackageVulnerability",
    # job
    "Job", "JobResult", "JobStatus",
    # plugin
    "Plugin", "PluginInstallation", "PluginStatus",
    # policy
    "Policy", "PolicyAudit",
]
