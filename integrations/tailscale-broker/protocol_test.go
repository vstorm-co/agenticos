package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

func TestReadJSONLineRejectsOversizedAndIncompleteFrames(t *testing.T) {
	t.Run("oversized", func(t *testing.T) {
		input := strings.Repeat("x", maxFrameBytes+1) + "\n"
		_, err := readJSONLine(bufio.NewReader(strings.NewReader(input)), maxFrameBytes)
		if !errors.Is(err, errFrameTooLarge) {
			t.Fatalf("readJSONLine error = %v, want frame-too-large", err)
		}
	})
	t.Run("incomplete", func(t *testing.T) {
		_, err := readJSONLine(bufio.NewReader(strings.NewReader("{")), maxFrameBytes)
		if !errors.Is(err, errUnexpectedEOF) {
			t.Fatalf("readJSONLine error = %v, want incomplete-frame", err)
		}
	})
	t.Run("clean eof", func(t *testing.T) {
		_, err := readJSONLine(bufio.NewReader(strings.NewReader("")), maxFrameBytes)
		if !errors.Is(err, io.EOF) {
			t.Fatalf("readJSONLine error = %v, want EOF", err)
		}
	})
}

func TestReadStartRejectsInvalidFramesAndState(t *testing.T) {
	valid := `{"version":1,"type":"start","connection_id":"123e4567-e89b-12d3-a456-426614174000","hostname":"broker-1","mode":"enroll","state":{}}`
	tests := []struct {
		name  string
		frame string
	}{
		{name: "bad json", frame: "{not-json}"},
		{name: "wrong version", frame: strings.Replace(valid, `"version":1`, `"version":2`, 1)},
		{name: "unknown field", frame: strings.TrimSuffix(valid, "}") + `, "token":"secret"}`},
		{name: "invalid hostname", frame: strings.Replace(valid, "broker-1", "bad/name", 1)},
		{name: "invalid base64", frame: strings.Replace(valid, `"state":{}`, `"state":{"k":"!"}`, 1)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, _, code := readStart(bufio.NewReader(strings.NewReader(test.frame + "\n")))
			if code != "invalid_start" {
				t.Fatalf("readStart code = %q, want invalid_start", code)
			}
		})
	}
	_, _, code := readStart(bufio.NewReader(strings.NewReader(strings.Repeat("x", maxFrameBytes+1) + "\n")))
	if code != "frame_too_large" {
		t.Fatalf("oversized start code = %q, want frame_too_large", code)
	}
}

func TestDecodeStateEnforcesCountAndCombinedSize(t *testing.T) {
	tooMany := make(map[string]string, maxStateKeys+1)
	for index := 0; index <= maxStateKeys; index++ {
		tooMany[string(rune('a'+index))] = ""
	}
	if _, err := decodeState(tooMany); err == nil {
		t.Fatal("decodeState accepted too many keys")
	}
	tooLarge := map[string]string{"state": " " + strings.Repeat("A", 4*maxStateBytes/3)}
	if _, err := decodeState(tooLarge); err == nil {
		t.Fatal("decodeState accepted an overlarge state value")
	}
}

func TestControlRejectsNetworkDialAndProxyCommands(t *testing.T) {
	for _, command := range []string{"dial", "proxy"} {
		kind, _, code := validateControlFrame(controlFrame{Type: command})
		if kind != "" || code != "invalid_control" {
			t.Fatalf("control command %q accepted: kind=%q code=%q", command, kind, code)
		}
	}
	var frame controlFrame
	if err := decodeStrictJSON([]byte(`{"type":"heartbeat","url":"http://127.0.0.1"}`), &frame); err == nil {
		t.Fatal("control protocol accepted an unknown URL field")
	}
}

func TestControlPersistStateRequiresMatchingParentAck(t *testing.T) {
	input, parent := io.Pipe()
	defer parent.Close()
	defer input.Close()
	config := defaultBrokerConfig()
	config.ackTimeout = time.Second
	config.heartbeatTimeout = time.Second
	control := newControlSession(bufio.NewReader(input), config)
	control.start()
	out := &channelWriter{frames: make(chan []byte, 1)}
	result := make(chan error, 1)
	go func() {
		result <- control.persistState(newEventWriter(out), 1, map[string]string{"_machinekey": "c2VjcmV0"})
	}()

	frame := <-out.frames
	var event stateEvent
	if err := json.Unmarshal(bytes.TrimSpace(frame), &event); err != nil {
		t.Fatalf("state event JSON: %v", err)
	}
	if event.Type != "state" || event.Sequence != 1 || event.State["_machinekey"] != "c2VjcmV0" {
		t.Fatalf("unexpected state event: %#v", event)
	}
	select {
	case err := <-result:
		t.Fatalf("persist returned before parent acknowledgement: %v", err)
	default:
	}
	if _, err := io.WriteString(parent, `{"type":"ack","sequence":1}`+"\n"); err != nil {
		t.Fatalf("write ack: %v", err)
	}
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("persist after ack: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("persist did not complete after matching acknowledgement")
	}
}

func TestControlStopKeepsAckLoopOpenForFinalStateFlush(t *testing.T) {
	input, parent := io.Pipe()
	defer parent.Close()
	defer input.Close()
	config := defaultBrokerConfig()
	config.ackTimeout = time.Second
	config.heartbeatTimeout = time.Second
	control := newControlSession(bufio.NewReader(input), config)
	control.start()
	if _, err := io.WriteString(parent, `{"type":"stop"}`+"\n"); err != nil {
		t.Fatalf("write stop: %v", err)
	}
	select {
	case <-control.stop:
	case <-time.After(time.Second):
		t.Fatal("stop request was not observed")
	}

	out := &channelWriter{frames: make(chan []byte, 1)}
	result := make(chan error, 1)
	go func() {
		result <- control.persistState(newEventWriter(out), 1, map[string]string{"_machinekey": "c2VjcmV0"})
	}()
	frame := <-out.frames
	var event stateEvent
	if err := json.Unmarshal(bytes.TrimSpace(frame), &event); err != nil {
		t.Fatalf("state event JSON: %v", err)
	}
	if event.Type != "state" || event.Sequence != 1 {
		t.Fatalf("unexpected final state event: %#v", event)
	}
	if _, err := io.WriteString(parent, `{"type":"ack","sequence":1}`+"\n"); err != nil {
		t.Fatalf("write final state acknowledgement: %v", err)
	}
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("final state flush after stop: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("final state flush did not complete after acknowledgement")
	}
}

func TestControlAckTimeoutFailsClosed(t *testing.T) {
	input, parent := io.Pipe()
	defer parent.Close()
	defer input.Close()
	config := defaultBrokerConfig()
	config.ackTimeout = 40 * time.Millisecond
	config.heartbeatTimeout = time.Second
	control := newControlSession(bufio.NewReader(input), config)
	control.start()
	err := control.persistState(newEventWriter(io.Discard), 1, map[string]string{})
	if err == nil || !control.hasFailed() || control.failureCode() != "state_ack_timeout" {
		t.Fatalf("persist err=%v failed=%v code=%q", err, control.hasFailed(), control.failureCode())
	}
}

func TestControlHeartbeatLapseAndEOFFailClosed(t *testing.T) {
	t.Run("heartbeat lapse", func(t *testing.T) {
		input, parent := io.Pipe()
		defer parent.Close()
		defer input.Close()
		config := defaultBrokerConfig()
		config.heartbeatTimeout = 80 * time.Millisecond
		control := newControlSession(bufio.NewReader(input), config)
		control.start()
		select {
		case <-control.fatal:
			if got := control.failureCode(); got != "heartbeat_timeout" {
				t.Fatalf("failure code = %q, want heartbeat_timeout", got)
			}
		case <-time.After(time.Second):
			t.Fatal("heartbeat lapse was not detected")
		}
	})
	t.Run("parent eof", func(t *testing.T) {
		input, parent := io.Pipe()
		config := defaultBrokerConfig()
		control := newControlSession(bufio.NewReader(input), config)
		control.start()
		_ = parent.Close()
		defer input.Close()
		select {
		case <-control.fatal:
			if got := control.failureCode(); got != "parent_eof" {
				t.Fatalf("failure code = %q, want parent_eof", got)
			}
		case <-time.After(time.Second):
			t.Fatal("parent EOF was not detected")
		}
	})
}

func TestErrorEventContainsOnlySanitizedCode(t *testing.T) {
	const secret = "private state that must never be emitted"
	var output bytes.Buffer
	newEventWriter(&output).emitError("status_unavailable")
	if strings.Contains(output.String(), secret) || strings.Contains(output.String(), "message") {
		t.Fatalf("error event leaked detail: %s", output.String())
	}
	var event map[string]any
	if err := json.Unmarshal(bytes.TrimSpace(output.Bytes()), &event); err != nil {
		t.Fatal(err)
	}
	if len(event) != 2 || event["type"] != "error" || event["code"] != "status_unavailable" {
		t.Fatalf("unexpected sanitized error event: %#v", event)
	}
}

func TestTrustedAuthURLAllowsOnlyExpectedInteractiveLoginURLs(t *testing.T) {
	for _, raw := range []string{
		"https://login.tailscale.com/a/123?token=abc",
		"https://LOGIN.TAILSCALE.COM:443/a/123",
		"https://login.tailscale.com/a/%2fadmin",
	} {
		if got := trustedAuthURL(raw); got == nil || *got != raw {
			t.Fatalf("trustedAuthURL(%q) = %v", raw, got)
		}
	}
	for _, raw := range []string{
		"http://login.tailscale.com/a/123",
		"https://login.tailscale.com.attacker.invalid/a/123",
		"https://region.login.tailscale.com/a/123",
		"https://user@login.tailscale.com/a/123",
		"https://login.tailscale.com:8443/a/123",
		"https://login.tailscale.com/other/123",
		"https://login.tailscale.com/a/123#fragment",
		"https://login.tailscale.com/a/123\nmalicious",
		"https://login.tailscale.com/a/" + strings.Repeat("x", 4096),
	} {
		if got := trustedAuthURL(raw); got != nil {
			t.Fatalf("trustedAuthURL(%q) = %q, want nil", raw, *got)
		}
	}
}

type channelWriter struct {
	frames chan []byte
}

func (w *channelWriter) Write(p []byte) (int, error) {
	w.frames <- bytes.Clone(p)
	return len(p), nil
}
