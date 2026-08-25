// Job validation pipeline: runs BEFORE any dispatch in runJob's caller.
// Signed-envelope verification + replay protection + capability coverage.
// Fail-closed when security.enforce_signed_jobs=true; observability mode
// (WARN per unsigned privileged job) while false during staged rollout.
package agent

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/lokilinux/agent/internal/modules"
	"github.com/lokilinux/agent/internal/security"
)

// initVerifier loads the platform signing public key at startup.
// Enforcement ON without a usable key is a configuration error — refuse to
// start rather than silently running an unenforceable policy.
func initVerifier(cfg *configSecurity) (*security.Verifier, error) {
	keys := map[int]string{}
	for ver, b64 := range cfg.SigningPubKeys {
		keys[ver] = b64
	}
	if _, hasV1 := keys[1]; !hasV1 {
		raw, err := os.ReadFile(cfg.SigningPubKeyPath)
		if err == nil && len(raw) > 0 {
			keys[1] = string(raw)
		} else if cfg.EnforceSignedJobs {
			return nil, fmt.Errorf("enforce_signed_jobs=true but signing public key unreadable at %s: %w", cfg.SigningPubKeyPath, err)
		}
	}
	if len(keys) == 0 {
		return nil, nil // observability mode without any key is fine
	}
	return security.NewVerifierSet(keys, cfg.RetiredKeys)
}

// configSecurity narrows the fields job validation needs (testability).
type configSecurity struct {
	EnforceSignedJobs bool
	SigningPubKeyPath string
	SigningPubKeys    map[int]string
	RetiredKeys       []int
}

// validateAndAuthorize runs the full pre-dispatch gate. A non-nil result
// means the job was REJECTED — the result must be reported upstream so the
// job doesn't linger RUNNING until the timeout sweeper.
func validateAndAuthorize(
	cfgSec configSecurity,
	verifier *security.Verifier,
	replay *security.ReplayStore,
	policy *security.LocalPolicy,
	agentID string,
	jobID, jobType string,
	params map[string]interface{},
	stepsJSON string,
	now time.Time,
) *modules.JobResult {
	required := security.RequiredCapabilities(jobType, stepsJSON)

	envRaw, ok := params["_envelope"]
	if !ok {
		if cfgSec.EnforceSignedJobs {
			return rejectResult(jobID, "unsigned_job", fmt.Sprintf("privileged job %s (%s) arrived without an envelope", jobID, jobType))
		}
		if required != nil {
			// Observability mode: allow, but make it loud enough to drive rollout.
			return nil
		}
		return nil
	}

	envJSON, err := json.Marshal(envRaw)
	if err != nil {
		return rejectResult(jobID, "malformed_envelope", err.Error())
	}
	env, err := security.ParseEnvelope(envJSON)
	if err != nil {
		return rejectResult(jobID, "malformed_envelope", err.Error())
	}

	// Payload binding: the signature must cover EXACTLY the parameters that
	// will execute. Without this, an attacker could keep a valid envelope and
	// swap the outer parameters (signature still verifies, execution differs).
	if cfgSec.EnforceSignedJobs {
		outer := make(map[string]interface{}, len(params))
		for k, v := range params {
			if k != "_envelope" && k != "_approval_claim" { // transport keys, not job content
				outer[k] = v
			}
		}
		var want []byte = []byte("{}")
		if len(outer) > 0 {
			b, err := json.Marshal(outer)
			if err != nil {
				return rejectResult(jobID, "malformed_params", err.Error())
			}
			if want, err = security.Canonical(b); err != nil {
				return rejectResult(jobID, "malformed_params", err.Error())
			}
		}
		got, err := security.Canonical(env.Payload)
		if err != nil || string(want) != string(got) {
			return rejectResult(jobID, "payload_mismatch",
				"envelope payload does not match job parameters")
		}
	}

	if cfgSec.EnforceSignedJobs {
		if !security.IsRegistered(jobType) {
			return rejectResult(jobID, "unknown_capability", fmt.Sprintf("job type %q not in capability registry", jobType))
		}
		if reason, err := verifier.Verify(env, agentID, now); err != nil {
			return rejectResult(jobID, string(reason), err.Error())
		}
		dup, err := replay.MarkSeen(context.Background(), env.Nonce, env.JobID)
		if err != nil {
			return rejectResult(jobID, "replay_store_error", err.Error())
		}
		if !dup {
			return rejectResult(jobID, "duplicate_job", fmt.Sprintf("nonce %s already consumed", env.Nonce))
		}
		if missing := missingCapabilities(env.RequestedCapabilities, required); len(missing) > 0 {
			return rejectResult(jobID, "capability_gap",
				fmt.Sprintf("envelope lacks %v required by %s", missing, jobType))
		}

		// Approval claims (plan §6): a valid signed claim satisfies
		// require_approval gates; everything else keeps the hard reject.
		var approvalClaim *security.ApprovalClaim
		if rawClaim, ok := params["_approval_claim"]; ok {
			claimJSON, err := json.Marshal(rawClaim)
			if err != nil {
				return rejectResult(jobID, "approval_malformed", err.Error())
			}
			claim, err := security.ParseApprovalClaim(claimJSON)
			if err != nil {
				return rejectResult(jobID, "approval_malformed", err.Error())
			}
			payloadCanonical, err := security.Canonical(env.Payload)
			if err != nil {
				return rejectResult(jobID, "approval_malformed", err.Error())
			}
			jobHash := fmt.Sprintf("%x", sha256.Sum256(payloadCanonical))
			if err := verifier.VerifyApprovalClaim(
				claim,
				env.JobID,
				jobHash,
				env.AgentID,
				env.RequestedCapabilities,
				replayAdapter{store: replay},
				now,
			); err != nil {
				return rejectResult(jobID, "approval_invalid", err.Error())
			}
			approvalClaim = claim
		}

		approvedByClaim := map[string]bool{}
		if approvalClaim != nil {
			for _, cp := range approvalClaim.Capabilities {
				approvedByClaim[cp] = true
			}
		}

		// Local policy enforcement (fail-closed for HIGH/CRITICAL): a bug or
		// compromise in the control plane must not silently widen execution.
		if reason, detail := policy.EvaluateAuthorizations(
			env.RequestedCapabilities,
			func(c string) string { return string(security.RiskFor(c)) },
			now,
			approvedByClaim,
		); reason != "" {
			return rejectResult(jobID, string(reason), detail)
		}
	} else if cfgSec.EnforceSignedJobs {
		// Unsigned jobs never reach here when enforcement is on (rejected
		// earlier); nothing to evaluate.
	}
	return nil
}

func missingCapabilities(requested []string, required []string) []string {
	have := make(map[string]bool, len(requested))
	for _, c := range requested {
		have[c] = true
	}
	var missing []string
	for _, c := range required {
		if !have[c] {
			missing = append(missing, c)
		}
	}
	return missing
}

func rejectResult(jobID, code, detail string) *modules.JobResult {
	return &modules.JobResult{
		JobID:    jobID,
		ExitCode: 126, // command found but not executable — conventional authz failure
		Error:    fmt.Sprintf("rejected [%s]: %s", code, detail),
	}
}
