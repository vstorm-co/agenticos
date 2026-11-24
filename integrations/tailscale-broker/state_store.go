package main

import (
	"bytes"
	"encoding/base64"
	"errors"
	"sync"

	"tailscale.com/ipn"
)

var errStateLimit = errors.New("state limit exceeded")

type snapshotStore struct {
	writeMu  sync.Mutex
	mu       sync.RWMutex
	state    map[ipn.StateKey][]byte
	sequence uint64
	commit   func(sequence uint64, snapshot map[string]string) error
}

func newSnapshotStore(initial map[string][]byte, commit func(uint64, map[string]string) error) (*snapshotStore, error) {
	state := make(map[ipn.StateKey][]byte, len(initial))
	for key, value := range initial {
		if key == "" || len([]byte(key)) > maxStateKeyBytes {
			return nil, errStateLimit
		}
		state[ipn.StateKey(key)] = bytes.Clone(value)
	}
	if err := checkStateLimits(state); err != nil {
		return nil, err
	}
	return &snapshotStore{state: state, commit: commit}, nil
}

func (s *snapshotStore) ReadState(id ipn.StateKey) ([]byte, error) {
	s.mu.RLock()
	value, ok := s.state[id]
	if ok {
		value = bytes.Clone(value)
	}
	s.mu.RUnlock()
	if !ok {
		return nil, ipn.ErrStateNotExist
	}
	return value, nil
}

func (s *snapshotStore) WriteState(id ipn.StateKey, value []byte) error {
	if id == "" || len([]byte(id)) > maxStateKeyBytes {
		return errStateLimit
	}
	s.writeMu.Lock()
	defer s.writeMu.Unlock()

	s.mu.Lock()
	previous := s.state
	next := cloneStoreState(previous)
	if value == nil {
		delete(next, id)
	} else {
		next[id] = bytes.Clone(value)
	}
	if err := checkStateLimits(next); err != nil {
		s.mu.Unlock()
		return err
	}
	if equalStoreState(previous, next) {
		s.mu.Unlock()
		return nil
	}
	s.sequence++
	sequence := s.sequence
	s.state = next
	s.mu.Unlock()

	if s.commit == nil {
		return nil
	}
	if err := s.commit(sequence, storeStateBase64(next)); err != nil {
		s.mu.Lock()
		s.state = previous
		s.mu.Unlock()
		return errors.New("state persistence failed")
	}
	return nil
}

func (s *snapshotStore) empty() bool {
	s.mu.RLock()
	empty := len(s.state) == 0
	s.mu.RUnlock()
	return empty
}

func checkStateLimits(state map[ipn.StateKey][]byte) error {
	if len(state) > maxStateKeys {
		return errStateLimit
	}
	total := 0
	for key, value := range state {
		if key == "" || len([]byte(key)) > maxStateKeyBytes || len(value) > maxStateBytes-total {
			return errStateLimit
		}
		total += len(value)
	}
	return nil
}

func cloneStoreState(state map[ipn.StateKey][]byte) map[ipn.StateKey][]byte {
	clone := make(map[ipn.StateKey][]byte, len(state))
	for key, value := range state {
		clone[key] = bytes.Clone(value)
	}
	return clone
}

func equalStoreState(left, right map[ipn.StateKey][]byte) bool {
	if len(left) != len(right) {
		return false
	}
	for key, value := range left {
		other, ok := right[key]
		if !ok || !bytes.Equal(value, other) {
			return false
		}
	}
	return true
}

func storeStateBase64(state map[ipn.StateKey][]byte) map[string]string {
	encoded := make(map[string]string, len(state))
	for key, value := range state {
		encoded[string(key)] = base64.StdEncoding.EncodeToString(value)
	}
	return encoded
}
