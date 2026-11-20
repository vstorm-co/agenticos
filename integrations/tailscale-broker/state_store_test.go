package main

import (
	"bytes"
	"encoding/base64"
	"errors"
	"testing"

	"tailscale.com/ipn"
)

func TestSnapshotStoreWaitsForParentPersistence(t *testing.T) {
	entered := make(chan struct{})
	release := make(chan struct{})
	store, err := newSnapshotStore(nil, func(sequence uint64, state map[string]string) error {
		if sequence != 1 || state["state-key"] != base64.StdEncoding.EncodeToString([]byte("value")) {
			t.Errorf("commit snapshot sequence=%d state=%v", sequence, state)
		}
		close(entered)
		<-release
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	input := []byte("value")
	result := make(chan error, 1)
	go func() { result <- store.WriteState("state-key", input) }()
	<-entered
	input[0] = 'X'
	select {
	case err := <-result:
		t.Fatalf("WriteState returned before parent persistence: %v", err)
	default:
	}
	stored, err := store.ReadState("state-key")
	if err != nil || !bytes.Equal(stored, []byte("value")) {
		t.Fatalf("ReadState = %q, %v", stored, err)
	}
	close(release)
	if err := <-result; err != nil {
		t.Fatalf("WriteState after parent persistence: %v", err)
	}
}

func TestSnapshotStoreNilDeletesKeyAndDeepCopies(t *testing.T) {
	initial := map[string][]byte{"state-key": []byte("original")}
	store, err := newSnapshotStore(initial, func(_ uint64, state map[string]string) error {
		if _, ok := state["state-key"]; ok {
			t.Fatal("deleted key remained in persisted snapshot")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	initial["state-key"][0] = 'X'
	read, err := store.ReadState("state-key")
	if err != nil || string(read) != "original" {
		t.Fatalf("initial state was not copied: %q, %v", read, err)
	}
	read[0] = 'Y'
	readAgain, err := store.ReadState("state-key")
	if err != nil || string(readAgain) != "original" {
		t.Fatalf("ReadState returned shared bytes: %q, %v", readAgain, err)
	}
	if err := store.WriteState("state-key", nil); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ReadState("state-key"); !errors.Is(err, ipn.ErrStateNotExist) {
		t.Fatalf("ReadState after nil delete error = %v", err)
	}
}

func TestSnapshotStoreFailureRollsBackCandidate(t *testing.T) {
	store, err := newSnapshotStore(map[string][]byte{"state-key": []byte("old")}, func(uint64, map[string]string) error {
		return errors.New("do not disclose backend error")
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.WriteState("state-key", []byte("new")); err == nil || err.Error() != "state persistence failed" {
		t.Fatalf("WriteState error = %v, want sanitized state persistence failure", err)
	}
	value, err := store.ReadState("state-key")
	if err != nil || string(value) != "old" {
		t.Fatalf("store did not roll back failed write: %q, %v", value, err)
	}
}

func TestSnapshotStoreEnforcesStateLimits(t *testing.T) {
	store, err := newSnapshotStore(nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.WriteState(ipn.StateKey(string(bytes.Repeat([]byte{'k'}, maxStateKeyBytes+1))), []byte("v")); !errors.Is(err, errStateLimit) {
		t.Fatalf("oversized state key error = %v", err)
	}
	if err := store.WriteState("state-key", bytes.Repeat([]byte{'v'}, maxStateBytes+1)); !errors.Is(err, errStateLimit) {
		t.Fatalf("oversized state value error = %v", err)
	}
}
