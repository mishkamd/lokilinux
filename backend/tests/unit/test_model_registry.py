"""
Regression guard: every ORM model must be importable through
lokilinux.models (the single Base.metadata registration hub, see its
docstring) so cross-package foreign keys resolve regardless of which
model a test or startup path happens to import first.

Caught live: Alert.incident_id -> incidents.id and
Incident.root_cause_signal_id/correlation_rule_id -> signals.id/
correlation_rules.id are cross-package FKs (lokilinux.incidents /
lokilinux.signals live outside lokilinux.models) — any test that only
triggered lokilinux.models without also importing those packages first
hit NoReferencedTableError at mapper configuration time.
"""

from sqlalchemy.orm import configure_mappers


def test_all_models_configure_without_dangling_foreign_keys():
    import lokilinux.models  # noqa: F401

    configure_mappers()  # raises if any FK target table isn't registered
