"""drop the archived dsc_* tables (MIS-173).

The DSC feature (per-resource-type state collection from agents) was never
finished and its code is gone from the repo — only three reference files
survive, on branch recovery/dsc-2026-08-24. The tables were left behind in
every deployment: no model, no migration, no code reading them.

The data was archived before this migration (2026-10-21):
  object: exports/ec1c125f-f0aa-42b3-a355-e1b4f7341d59/v1/dsc-archive-2026-10-21.tar.gz
  sha256: 0ee0f7e8e27e06443ccfcc521bb10b18a9aa4c900d5210d90b89a681147551f1
  size:   167100847 bytes (gzip CSVs + MANIFEST.txt with the column lists)
  rows:   dsc_resource_states 8227725, dsc_resource_blobs 25528,
          dsc_provider_status 64, dsc_verifications 0
  restore: gunzip <table>.csv.gz | psql -d target \
             -c "copy <table> from stdin with (format csv, header)"

dsc_resource_states and dsc_verifications are TimescaleDB hypertables —
dropping the parent drops its chunks.

Revision ID: 063
Create Date: 2026-10-21
"""

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Child first: dsc_resource_blobs holds the content-addressed bodies the
    # state rows point at. Literal names, no interpolation.
    # if_exists: a fresh database never had these tables.
    op.drop_table("dsc_verifications", if_exists=True)
    op.drop_table("dsc_resource_states", if_exists=True)
    op.drop_table("dsc_resource_blobs", if_exists=True)
    op.drop_table("dsc_provider_status", if_exists=True)


def downgrade() -> None:
    # The data lives in the archive (see the module docstring) — recreating
    # empty tables would only restore the drift, not the data.
    raise NotImplementedError(
        "dsc_* were archived as CSV — restore from the object storage archive "
        "(see the migration docstring) instead of downgrading."
    )
