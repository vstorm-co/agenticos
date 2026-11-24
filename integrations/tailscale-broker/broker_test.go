package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/netip"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"tailscale.com/ipn"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/tailcfg"
	"tailscale.com/types/key"
)

func TestStatusDTOIsDeterministicAndRedactsRawTailscaleFields(t *testing.T) {
	peerA := &ipnstate.PeerStatus{
		ID:           tailcfg.StableNodeID("peer-a"),
		HostName:     "device-a",
		DNSName:      "device-a.example.ts.net.",
		TailscaleIPs: []netip.Addr{netip.MustParseAddr("fd7a:115c:a1e0::2"), netip.MustParseAddr("100.64.0.2")},
		Online:       true,
		OS:           "linux",
		UserID:       tailcfg.UserID(777),
		PeerAPIURL:   []string{"https://private-peer-api.invalid/secret"},
	}
	peerZ := &ipnstate.PeerStatus{
		ID:       tailcfg.StableNodeID("peer-z"),
		HostName: "device-z",
		DNSName:  "device-z.example.ts.net.",
		OS:       "windows",
	}
	status := &ipnstate.Status{
		BackendState: "Running",
		AuthURL:      "https://attacker.invalid/secret-auth-url",
		CurrentTailnet: &ipnstate.TailnetStatus{
			Name: "example.com",
		},
		Self: &ipnstate.PeerStatus{
			ID:      tailcfg.StableNodeID("self-node-id"),
			Expired: true,
		},
		Peer: map[key.NodePublic]*ipnstate.PeerStatus{
			key.NewNode().Public(): peerZ,
			key.NewNode().Public(): peerA,
		},
	}

	first := statusToEvent(status, true)
	second := statusToEvent(status, true)
	firstJSON, err := json.Marshal(first)
	if err != nil {
		t.Fatal(err)
	}
	secondJSON, err := json.Marshal(second)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstJSON, secondJSON) {
		t.Fatalf("status DTO changed between calls:\n%s\n%s", firstJSON, secondJSON)
	}
	if first.AuthURL != nil {
		t.Fatalf("untrusted auth URL was exposed: %v", *first.AuthURL)
	}
	if first.TailnetName == nil || *first.TailnetName != "example.com" ||
		first.NodeID == nil || *first.NodeID != "self-node-id" || !first.KeyExpired {
		t.Fatalf("status identity fields are incomplete: %#v", first)
	}
	if len(first.Peers) != 2 || first.Peers[0].ID != "peer-a" || first.Peers[1].ID != "peer-z" {
		t.Fatalf("peer order is not deterministic: %#v", first.Peers)
	}
	if got := first.Peers[0].IPs; !reflect.DeepEqual(got, []string{"100.64.0.2", "fd7a:115c:a1e0::2"}) {
		t.Fatalf("peer IPs = %v, want sorted addresses", got)
	}
	for _, forbidden := range []string{"PeerAPIURL", "private-peer-api.invalid", "UserID", "sshHostKeys", "attacker.invalid", "secret-auth-url"} {
		if bytes.Contains(firstJSON, []byte(forbidden)) {
			t.Fatalf("status JSON leaked %q: %s", forbidden, firstJSON)
		}
	}
}

func TestAuthenticatedStatusRejectsExpiredSelf(t *testing.T) {
	status := readyStatus()
	if !authenticatedStatus(status) {
		t.Fatal("running status with a valid self node was not authenticated")
	}
	status.Self.Expired = true
	if authenticatedStatus(status) {
		t.Fatal("running status with an expired self key was authenticated")
	}
}

func TestStatusDTOCapsPeersAt1024AfterSorting(t *testing.T) {
	peers := make(map[key.NodePublic]*ipnstate.PeerStatus, maxPeers+1)
	for index := 0; index <= maxPeers; index++ {
		peerID := fmt.Sprintf("peer-%04d", index)
		publicKey := key.NewNode().Public()
		peers[publicKey] = &ipnstate.PeerStatus{ID: tailcfg.StableNodeID(peerID)}
	}
	event := statusToEvent(&ipnstate.Status{Peer: peers}, false)
	if len(event.Peers) != maxPeers {
		t.Fatalf("peer count = %d, want %d", len(event.Peers), maxPeers)
	}
	if event.Peers[0].ID != "peer-0000" || event.Peers[len(event.Peers)-1].ID != "peer-1023" {
		t.Fatalf("capped peer range = %q to %q", event.Peers[0].ID, event.Peers[len(event.Peers)-1].ID)
	}
}

func TestTSNetServerUsesRestrictedUserspaceConfiguration(t *testing.T) {
	store, err := newSnapshotStore(nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	server := newTSNetServer("broker-1", "private-dir", store)
	if server.Hostname != "broker-1" || server.Dir != "private-dir" || server.Store != store {
		t.Fatalf("tsnet server does not use the dedicated host, directory, and parent store: %#v", server)
	}
	if server.Ephemeral || server.Tun != nil || server.RunWebClient {
		t.Fatalf("tsnet server enabled ephemeral, TUN, or WebClient mode: %#v", server)
	}
	if server.AuthKey != "" || server.ClientID != "" || server.ClientSecret != "" || server.IDToken != "" ||
		server.Audience != "" || server.ControlURL != "" {
		t.Fatalf("tsnet server inherited auth or alternate control settings: %#v", server)
	}
}

func TestSafeEnvironmentDropsAllInheritedSettings(t *testing.T) {
	got := safeEnvironment([]string{
		"TS_AUTHKEY=do-not-forward",
		"TS_CONTROL_URL=https://control.invalid",
		"TSNET_FORCE_LOGIN=true",
		"HTTP_PROXY=http://proxy.invalid",
		"PATH=C:\\tools",
	})
	want := []string{"TS_NO_LOGS_NO_SUPPORT=true"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("safeEnvironment = %v, want %v", got, want)
	}
}

func TestRunBrokerEnrollmentUsesInteractiveLoginAndStops(t *testing.T) {
	config := fastBrokerConfig()
	server := &fakeNode{beforeLogin: &ipnstate.Status{BackendState: ipn.NeedsLogin.String(), AuthURL: "https://login.tailscale.com/a/attempt"}}
	output, err := runFakeBroker(t, modeEnroll, nil, server, config, 0)
	if err != nil {
		t.Fatalf("runBroker: %v", err)
	}
	if !server.loginRequested || !server.closed {
		t.Fatalf("login requested=%v closed=%v", server.loginRequested, server.closed)
	}
	if !strings.Contains(output, `"reason":"ready"`) || !strings.Contains(output, `"node_id":"stable-node"`) {
		t.Fatalf("enrollment did not complete with stable node identity: %s", output)
	}
}

func TestRunBrokerEnrollResumesPausedIdentityWithoutInteractiveLogin(t *testing.T) {
	config := fastBrokerConfig()
	server := &fakeNode{statuses: []*ipnstate.Status{
		{BackendState: ipn.Stopped.String(), Self: &ipnstate.PeerStatus{ID: tailcfg.StableNodeID("stable-node")}},
		readyStatus(),
	}}
	output, err := runFakeBroker(t, modeEnroll, map[string]string{"_machinekey": "a2V5"}, server, config, 0)
	if err != nil {
		t.Fatalf("runBroker: %v", err)
	}
	if server.loginRequested || !server.closed {
		t.Fatalf("login requested=%v closed=%v", server.loginRequested, server.closed)
	}
	if !strings.Contains(output, `"reason":"ready"`) || !strings.Contains(output, `"node_id":"stable-node"`) {
		t.Fatalf("resumed enrollment did not complete with stable node identity: %s", output)
	}
}

func TestRunBrokerStatusDoesNotStartInteractiveLogin(t *testing.T) {
	config := fastBrokerConfig()
	config.statusDuration = 45 * time.Millisecond
	server := &fakeNode{beforeLogin: &ipnstate.Status{
		BackendState: ipn.NeedsLogin.String(),
		AuthURL:      "https://login.tailscale.com/a/re-auth",
	}}
	output, err := runFakeBroker(t, modeStatus, map[string]string{"_machinekey": "a2V5"}, server, config, 0)
	if err != nil {
		t.Fatalf("runBroker: %v", err)
	}
	if server.loginRequested {
		t.Fatal("status mode started an interactive login")
	}
	if !strings.Contains(output, `"reason":"timeout"`) || !strings.Contains(output, `"auth_url":"https://login.tailscale.com/a/re-auth"`) {
		t.Fatalf("status mode result missing expected state: %s", output)
	}
}

func TestRunBrokerLogoutReportsLocalLogoutOnly(t *testing.T) {
	config := fastBrokerConfig()
	server := &fakeNode{beforeLogin: readyStatus()}
	output, err := runFakeBroker(t, modeLogout, map[string]string{"_machinekey": "a2V5"}, server, config, 0)
	if err != nil {
		t.Fatalf("runBroker: %v", err)
	}
	if !server.logoutRequested || !server.closed {
		t.Fatalf("logout requested=%v closed=%v", server.logoutRequested, server.closed)
	}
	if !strings.Contains(output, `"reason":"logged_out"`) || !strings.Contains(output, `"auth_url":null`) || strings.Contains(output, "login.tailscale.com") {
		t.Fatalf("logout completion is incorrect: %s", output)
	}
}

func TestRunBrokerStopCompletesAfterShutdown(t *testing.T) {
	config := fastBrokerConfig()
	config.statusDuration = time.Second
	server := &fakeNode{beforeLogin: readyStatus()}
	output, err := runFakeBroker(t, modeStatus, map[string]string{"_machinekey": "a2V5"}, server, config, 15*time.Millisecond)
	if err != nil {
		t.Fatalf("runBroker: %v", err)
	}
	if !server.closed || !strings.Contains(output, `"reason":"stopped"`) {
		t.Fatalf("stop was not completed after shutdown: closed=%v output=%s", server.closed, output)
	}
}

func TestRunBrokerSanitizesStatusErrors(t *testing.T) {
	config := fastBrokerConfig()
	server := &fakeNode{err: errors.New("state secret and private control response")}
	output, err := runFakeBroker(t, modeStatus, map[string]string{"_machinekey": "a2V5"}, server, config, 0)
	if err == nil || !strings.Contains(output, `"code":"status_unavailable"`) {
		t.Fatalf("status failure missing sanitized error: err=%v output=%s", err, output)
	}
	if strings.Contains(output, "state secret") || strings.Contains(output, "private control response") {
		t.Fatalf("status error leaked provider details: %s", output)
	}
}

func fastBrokerConfig() brokerConfig {
	return brokerConfig{
		statusInterval:    10 * time.Millisecond,
		statusDuration:    35 * time.Millisecond,
		enrollDuration:    200 * time.Millisecond,
		logoutDuration:    100 * time.Millisecond,
		statusCallTimeout: 50 * time.Millisecond,
		ackTimeout:        100 * time.Millisecond,
		heartbeatTimeout:  500 * time.Millisecond,
	}
}

func readyStatus() *ipnstate.Status {
	return &ipnstate.Status{
		BackendState: ipn.Running.String(),
		Self:         &ipnstate.PeerStatus{ID: tailcfg.StableNodeID("stable-node")},
		CurrentTailnet: &ipnstate.TailnetStatus{
			Name: "example.com",
		},
	}
}

func runFakeBroker(t *testing.T, requestMode mode, state map[string]string, node *fakeNode, config brokerConfig, stopAfter time.Duration) (string, error) {
	t.Helper()
	input, parent := io.Pipe()
	var output bytes.Buffer
	request, err := json.Marshal(startFrame{
		Version:      protocolVersion,
		Type:         "start",
		ConnectionID: "123e4567-e89b-12d3-a456-426614174000",
		Hostname:     "broker-1",
		Mode:         requestMode,
		State:        state,
	})
	if err != nil {
		t.Fatal(err)
	}
	go func() {
		_, _ = parent.Write(append(request, '\n'))
		if stopAfter > 0 {
			time.Sleep(stopAfter)
			_, _ = io.WriteString(parent, `{"type":"stop"}`+"\n")
		}
	}()
	factory := func(hostname, dir string, store *snapshotStore) (tailnetNode, error) {
		if hostname != "broker-1" || dir == "" || store == nil {
			return nil, errors.New("invalid fake factory arguments")
		}
		return node, nil
	}
	err = runBroker(input, &output, t.TempDir(), factory, config)
	_ = parent.Close()
	return output.String(), err
}

type fakeNode struct {
	mu              sync.Mutex
	beforeLogin     *ipnstate.Status
	statuses        []*ipnstate.Status
	statusCalls     int
	loginRequested  bool
	logoutRequested bool
	closed          bool
	err             error
}

func (n *fakeNode) Status(context.Context) (*ipnstate.Status, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.err != nil {
		return nil, n.err
	}
	if len(n.statuses) > 0 {
		index := n.statusCalls
		if index >= len(n.statuses) {
			index = len(n.statuses) - 1
		}
		n.statusCalls++
		return n.statuses[index], nil
	}
	if n.logoutRequested || !n.loginRequested {
		if n.beforeLogin != nil {
			return n.beforeLogin, nil
		}
		return &ipnstate.Status{BackendState: ipn.NeedsLogin.String()}, nil
	}
	return readyStatus(), nil
}

func (n *fakeNode) StartLoginInteractive(context.Context) error {
	n.mu.Lock()
	n.loginRequested = true
	n.mu.Unlock()
	return nil
}

func (n *fakeNode) Logout(context.Context) error {
	n.mu.Lock()
	n.logoutRequested = true
	n.mu.Unlock()
	return nil
}

func (n *fakeNode) Close() error {
	n.mu.Lock()
	n.closed = true
	n.mu.Unlock()
	return nil
}
