package policy

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// Parse decodes a fetched policy document into a validated Policy.
//
// Strictness contract (plan §4): unknown top-level/spec fields are REJECTED
// (DisallowUnknownFields), not silently ignored — a document produced by a
// newer control plane must fail closed here instead of being half-applied.
// Faza-5 runtime sections (signals/services/logs/...) must be absent or
// empty until their enforcement ships.
func Parse(raw []byte) (*Policy, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()

	p := &Policy{}
	if err := dec.Decode(p); err != nil {
		return nil, fmt.Errorf("policy schema: %w", err)
	}
	if p.APIVersion != "lokilinux.io/v1" {
		return nil, fmt.Errorf("apiVersion %q unsupported", p.APIVersion)
	}
	if p.Kind != "AgentPolicy" {
		return nil, fmt.Errorf("kind %q is not AgentPolicy", p.Kind)
	}
	if p.Metadata.Name == "" {
		return nil, fmt.Errorf("metadata.name: required")
	}

	for name, section := range map[string]map[string]interface{}{
		"signals": p.Spec.Signals, "services": p.Spec.Services,
		"logs": p.Spec.Logs, "limits": p.Spec.Limits, "buffer": p.Spec.Buffer,
		"compliance": p.Spec.Compliance, "otel": p.Spec.Otel,
	} {
		if len(section) > 0 {
			return nil, fmt.Errorf("spec.%s: runtime enforcement lands in a later release — empty mapping only", name)
		}
	}

	if err := validateSpec(&p.Spec); err != nil {
		return nil, err
	}
	return p, nil
}
