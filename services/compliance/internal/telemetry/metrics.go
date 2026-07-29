// Package telemetry wires Prometheus metrics for lokilinux-compliance.
//
// ponytail: metrics are served via plain net/http (promhttp.Handler is
// net/http-native) on their own port, rather than pulling in a Fiber adaptor
// package just to mount it on the Fiber app — one fewer dependency for the
// same result. /healthz stays on Fiber per docs/compliance/02-GO-SERVICE.md.
package telemetry

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics holds the counters/histograms this service exposes. Empty at
// skeleton stage — populated as ingest/rules/drift/scheduler land (each
// future package registers its own metrics via promauto against the same
// default registry, so this struct grows alongside them rather than needing
// a central rewrite).
type Metrics struct {
	SnapshotsIngestedTotal prometheus.Counter
	DriftEventsTotal       *prometheus.CounterVec
}

// New registers and returns the service's metrics on the default Prometheus
// registry (matches the process-global registry pattern promhttp.Handler
// expects, same as the rest of the Prometheus Go ecosystem).
func New() *Metrics {
	return &Metrics{
		SnapshotsIngestedTotal: promauto.NewCounter(prometheus.CounterOpts{
			Name: "lokilinux_compliance_snapshots_ingested_total",
			Help: "Total inventory snapshots ingested from agent heartbeats.",
		}),
		DriftEventsTotal: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "lokilinux_compliance_drift_events_total",
			Help: "Total drift events detected, by severity.",
		}, []string{"severity"}),
	}
}

// Handler returns the net/http handler to mount on the metrics port.
func Handler() http.Handler {
	return promhttp.Handler()
}
