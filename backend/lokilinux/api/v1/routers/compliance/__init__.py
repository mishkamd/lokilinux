"""
LokiLinux — Compliance module router aggregator.

Sub-package (not a single file) because this module has more surface area
than any existing router — one file per submodule as the module grows
(baselines today; policies/drift/remediation/ai land as their phases are
built, docs/compliance/13-OPS.md roadmap). Mounted at prefix="/compliance"
in api/v1/__init__.py.
"""

from fastapi import APIRouter

from .baselines import router as baselines_router
from .drift import router as drift_router
from .file_integrity import router as file_integrity_router
from .inventory import router as inventory_router
from .policy_engine import router as policy_engine_router
from .remediation import router as remediation_router
from .reports import router as reports_router

router = APIRouter()
router.include_router(baselines_router)
router.include_router(drift_router)
router.include_router(file_integrity_router)
router.include_router(inventory_router)
router.include_router(policy_engine_router)
router.include_router(remediation_router)
router.include_router(reports_router)
