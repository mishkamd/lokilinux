package policy

import (
	"os"
	"path/filepath"
)

// Store persists the active policy document atomically under
// /var/lib/lokilinux-agent/ (0700 dir, 0600 files — plan §8).
//
// Files:
//
//	policy.json      exact canonical payload bytes (last committed)
//	policy.meta      JSON envelope metadata {policy_id, version, hash, signature, key_id}
//
// Crash safety: STAGE writes tmp+fsync; COMMIT renames into place. A crash
// mid-commit leaves either the old or the new file — never a torn one.
type Store struct {
	dir string
}

func NewStore(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	return &Store{dir: dir}, nil
}

type StoredMeta struct {
	PolicyID     string `json:"policy_id"`
	Version      int    `json:"version"`
	Hash         string `json:"hash"`
	SignatureB64 string `json:"signature"`
	KeyID        string `json:"key_id"`
}

const (
	filePayload = "policy.json"
	fileMeta    = "policy.meta"
)

func atomicWrite(path string, data []byte, perm os.FileMode) error {
	tmp := path + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, perm)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close() //nolint:errcheck
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close() //nolint:errcheck
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Stage writes the candidate out of the live path; Commit promotes it.
type Staged struct {
	payload []byte
	meta    StoredMeta
}

func (s *Store) Stage(payload []byte, meta StoredMeta) (*Staged, error) {
	return &Staged{payload: payload, meta: meta}, nil
}

func (s *Store) Commit(staged *Staged) error {
	if err := atomicWrite(filepath.Join(s.dir, filePayload), staged.payload, 0o600); err != nil {
		return err
	}
	metaBytes := jsonMarshal(staged.meta)
	return atomicWrite(filepath.Join(s.dir, fileMeta), metaBytes, 0o600)
}

// Load returns the committed payload bytes + meta. Missing files (first boot)
// return (nil, StoredMeta{}, nil).
func (s *Store) Load() ([]byte, StoredMeta, error) {
	var meta StoredMeta
	payload, err := os.ReadFile(filepath.Join(s.dir, filePayload))
	if os.IsNotExist(err) {
		return nil, StoredMeta{}, nil
	}
	if err != nil {
		return nil, meta, err
	}
	metaBytes, err := os.ReadFile(filepath.Join(s.dir, fileMeta))
	if os.IsNotExist(err) {
		return payload, StoredMeta{}, nil
	}
	if err != nil {
		return payload, meta, err
	}
	if err := jsonUnmarshal(metaBytes, &meta); err != nil {
		return payload, StoredMeta{}, err
	}
	return payload, meta, nil
}

// CurrentVersion is a convenience for the verifier's monotonicity baseline.
func (s *Store) CurrentVersion() int {
	_, meta, _ := s.Load()
	return meta.Version
}
