"""
LokiLinux — API v1 router.

main.py mounts this at prefix="/api/v1" — no prefix set here.
"""

from fastapi import APIRouter

from .routers.admin import router as admin_router
from .routers.agent_install import register_router as agent_register_router
from .routers.agent_install import router as agent_install_router
from .routers.alerts import router as alerts_router
from .routers.ansible_projects import router as ansible_projects_router
from .routers.ansible_roles import router as ansible_roles_router
from .routers.categories import router as categories_router
from .routers.compliance import router as compliance_router
from .routers.cves import router as cves_router
from .routers.correlation import router as correlation_router
from .routers.dashboard import router as dashboard_router
from .routers.events import router as events_router
from .routers.incidents import router as incidents_router
from .routers.jobs import router as jobs_router
from .routers.observability import router as observability_router
from .routers.playbook_templates import router as playbook_templates_router
from .routers.playbooks import router as playbooks_router
from .routers.plugins import router as plugins_router
from .routers.policies import router as policies_router
from .routers.runbooks import router as runbooks_router
from .routers.servers import router as servers_router
from .routers.signals import router as signals_router
from .routers.topology import router as topology_router
from .routers.workflows import router as workflows_router

router = APIRouter()

router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
router.include_router(categories_router, tags=["categories"])
router.include_router(compliance_router, prefix="/compliance", tags=["compliance"])
router.include_router(events_router, prefix="/events", tags=["events"])
router.include_router(servers_router, prefix="/servers", tags=["servers"])
router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
router.include_router(cves_router, prefix="/vulnerabilities", tags=["vulnerabilities"])
router.include_router(policies_router, prefix="/policies", tags=["policies"])
router.include_router(plugins_router, prefix="/plugins", tags=["plugins"])
router.include_router(playbooks_router, prefix="/playbooks", tags=["playbooks"])
router.include_router(playbook_templates_router, prefix="/playbook-templates", tags=["playbook-templates"])
router.include_router(ansible_roles_router, prefix="/ansible-roles", tags=["ansible-roles"])
router.include_router(ansible_projects_router, prefix="/ansible-projects", tags=["ansible-projects"])
router.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(agent_install_router, prefix="/agent", tags=["agent-install"])
router.include_router(agent_register_router, prefix="/agents", tags=["agent-install"])
router.include_router(workflows_router, prefix="/workflows", tags=["workflows"])
router.include_router(topology_router, prefix="/topology", tags=["topology"])
router.include_router(runbooks_router, prefix="/runbooks", tags=["runbooks"])
router.include_router(incidents_router, prefix="/incidents", tags=["incidents"])
router.include_router(signals_router, prefix="/signals", tags=["signals"])
router.include_router(correlation_router, prefix="/correlation", tags=["correlation"])
router.include_router(observability_router, prefix="/observability", tags=["observability"])
