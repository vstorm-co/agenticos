package main

import (
	"bytes"
	"encoding/json"
	"io"
	"testing"
	"time"

	"tailscale.com/ipn"
	"tailscale.com/ipn/ipnstate"
)

func TestParentEOFTerminatesWhileFactoryIsBlocked(t *testing.T) {
	config := fastBrokerConfig()
	terminated := make(chan struct{}, 1)
	config.terminate = func() { terminated <- struct{}{} }

	input, parent := io.Pipe()
	defer input.Close()
	defer parent.Close()
	enteredFactory := make(chan struct{})
	releaseFactory := make(chan struct{})
	runDone := make(chan error, 1)
	factory := func(string, string, *snapshotStore) (tailnetNode, error) {
		close(enteredFactory)
		<-releaseFactory
		return &fakeNode{beforeLogin: readyStatus()}, nil
	}
	go func() { runDone <- runBroker(input, io.Discard, t.TempDir(), factory, config) }()
	writeStartFrame(t, parent, modeStatus)
	select {
	case <-enteredFactory:
	case <-time.After(time.Second):
		t.Fatal("node factory did not start")
	}
	_ = parent.Close()
	awaitTermination(t, terminated)
	close(releaseFactory)
	awaitRunReturn(t, runDone)
}

func TestParentEOFTerminatesWhileOutputWriteIsBlocked(t *testing.T) {
	config := fastBrokerConfig()
	terminated := make(chan struct{}, 1)
	config.terminate = func() { terminated <- struct{}{} }
	input, parent := io.Pipe()
	defer input.Close()
	defer parent.Close()
	output := &blockingOutput{entered: make(chan struct{}), release: make(chan struct{})}
	runDone := make(chan error, 1)
	factory := func(string, string, *snapshotStore) (tailnetNode, error) {
		return &fakeNode{beforeLogin: readyStatus()}, nil
	}
	go func() { runDone <- runBroker(input, output, t.TempDir(), factory, config) }()
	writeStartFrame(t, parent, modeStatus)
	select {
	case <-output.entered:
	case <-time.After(time.Second):
		t.Fatal("status output did not block")
	}
	_ = parent.Close()
	awaitTermination(t, terminated)
	close(output.release)
	awaitRunReturn(t, runDone)
}

func TestHeartbeatWatchdogRemainsArmedDuringBlockedShutdownAfterStop(t *testing.T) {
	config := fastBrokerConfig()
	config.heartbeatTimeout = 100 * time.Millisecond
	terminated := make(chan struct{}, 1)
	config.terminate = func() { terminated <- struct{}{} }
	input, parent := io.Pipe()
	defer input.Close()
	defer parent.Close()
	closing := make(chan struct{})
	releaseClose := make(chan struct{})
	node := &blockingCloseNode{fakeNode: &fakeNode{beforeLogin: readyStatus()}, entered: closing, release: releaseClose}
	runDone := make(chan error, 1)
	factory := func(string, string, *snapshotStore) (tailnetNode, error) { return node, nil }
	go func() { runDone <- runBroker(input, io.Discard, t.TempDir(), factory, config) }()
	writeStartFrame(t, parent, modeStatus)
	if _, err := io.WriteString(parent, "{\"type\":\"heartbeat\"}\n"); err != nil {
		t.Fatalf("write initial heartbeat: %v", err)
	}
	if _, err := io.WriteString(parent, "{\"type\":\"stop\"}\n"); err != nil {
		t.Fatalf("write stop: %v", err)
	}
	select {
	case <-closing:
	case <-time.After(time.Second):
		t.Fatal("node shutdown did not start")
	}
	awaitTermination(t, terminated)
	close(releaseClose)
	awaitRunReturn(t, runDone)
}

func TestCleanCompletionDoesNotInvokeHardTermination(t *testing.T) {
	config := fastBrokerConfig()
	terminated := make(chan struct{}, 1)
	config.terminate = func() { terminated <- struct{}{} }
	input, parent := io.Pipe()
	defer input.Close()
	defer parent.Close()
	var output bytes.Buffer
	factory := func(string, string, *snapshotStore) (tailnetNode, error) {
		return &fakeNode{beforeLogin: &ipnstate.Status{BackendState: ipn.NeedsLogin.String()}}, nil
	}
	runDone := make(chan error, 1)
	go func() { runDone <- runBroker(input, &output, t.TempDir(), factory, config) }()
	writeStartFrame(t, parent, modeEnroll)
	select {
	case err := <-runDone:
		if err != nil {
			t.Fatalf("runBroker: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("clean enrollment did not complete")
	}
	_ = parent.Close()
	select {
	case <-terminated:
		t.Fatal("clean completion invoked hard termination")
	case <-time.After(40 * time.Millisecond):
	}
}

func writeStartFrame(t *testing.T, parent *io.PipeWriter, requestMode mode) {
	t.Helper()
	frame, err := json.Marshal(startFrame{
		Version:      protocolVersion,
		Type:         "start",
		ConnectionID: "123e4567-e89b-12d3-a456-426614174000",
		Hostname:     "broker-1",
		Mode:         requestMode,
		State:        map[string]string{"_machinekey": "a2V5"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := parent.Write(append(frame, '\n')); err != nil {
		t.Fatalf("write start frame: %v", err)
	}
}

func awaitTermination(t *testing.T, terminated <-chan struct{}) {
	t.Helper()
	select {
	case <-terminated:
	case <-time.After(time.Second):
		t.Fatal("hard termination hook was not invoked")
	}
}

func awaitRunReturn(t *testing.T, runDone <-chan error) {
	t.Helper()
	select {
	case <-runDone:
	case <-time.After(time.Second):
		t.Fatal("broker did not return after releasing its blocked operation")
	}
}

type blockingOutput struct {
	entered chan struct{}
	release chan struct{}
}

func (w *blockingOutput) Write(p []byte) (int, error) {
	select {
	case <-w.entered:
	default:
		close(w.entered)
	}
	<-w.release
	return len(p), nil
}

type blockingCloseNode struct {
	*fakeNode
	entered chan struct{}
	release chan struct{}
}

func (n *blockingCloseNode) Close() error {
	close(n.entered)
	<-n.release
	return n.fakeNode.Close()
}
