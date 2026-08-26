package ingest

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Package-level counters registered once on the default Prometheus registry
// (served on the metrics port by cmd/compliance). Nil-safe by construction:
// they exist from init, so hot paths just .Inc() them.
var (
	snapshotsIngested = promauto.NewCounter(prometheus.CounterOpts{
		Name: "lokilinux_compliance_snapshots_ingested_total",
		Help: "Inventory snapshots successfully ingested from agent heartbeats.",
	})
	snapshotFailures = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "lokilinux_compliance_snapshot_failures_total",
		Help: "Snapshot messages that failed ingestion, by failure class.",
	}, []string{"outcome"}) // "permanent" (Termed) | "transient" (NAKed)
	driftEvents = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "lokilinux_compliance_drift_events_total",
		Help: "New drift incidents opened, by severity.",
	}, []string{"severity"})
)

func observeOutcome(err error) {
	if isPermanent(err) {
		snapshotFailures.WithLabelValues("permanent").Inc()
		return
	}
	snapshotFailures.WithLabelValues("transient").Inc()
}
