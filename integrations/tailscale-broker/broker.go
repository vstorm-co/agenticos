package main

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net/netip"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"tailscale.com/ipn"
	"tailscale.com/ipn/ipnstate"
)

var errInteractiveLogin = errors.New("interactive login failed")

type brokerConfig struct {
	statusInterval    time.Duration
	statusDuration    time.Duration
	enrollDuration    time.Duration
	logoutDuration    time.Duration
	statusCallTimeout time.Duration
	ackTimeout        time.Duration
	heartbeatTimeout  time.Duration
	terminate         func()
}

// maxHeartbeatAge is shorter than the parent's 15-second lease so a lost
// control pipe shuts this process down before its lease could be reassigned.
const maxHeartbeatAge = 8 * time.Second

func defaultBrokerConfig() brokerConfig {
	return brokerConfig{
		statusInterval:    2 * time.Second,
		statusDuration:    20 * time.Second,
		enrollDuration:    10 * time.Minute,
		logoutDuration:    10 * time.Second,
		statusCallTimeout: 5 * time.Second,
		ackTimeout:        5 * time.Second,
		heartbeatTimeout:  maxHeartbeatAge,
	}
}

func runBroker(input io.Reader, output io.Writer, tempRoot string, factory nodeFactory, config brokerConfig) error {
	reader := bufio.NewReaderSize(input, readerBufferSize)
	writer := newEventWriter(output)
	request, initialState, code := readStart(reader)
	if code != "" {
		writer.emitError(code)
		return protocolFailure(code)
	}

	control := newControlSession(reader, config)
	control.start()
	defer control.closeInput(input)

	store, err := newSnapshotStore(initialState, func(sequence uint64, snapshot map[string]string) error {
		return control.persistState(writer, sequence, snapshot)
	})
	if err != nil {
		writer.emitError("invalid_start")
		return err
	}

	if request.Mode == modeStatus && store.empty() {
		status := statusEvent{Type: "status", BackendState: ipn.NoState.String(), Peers: []peerDTO{}}
		if err := writer.emit(status); err != nil {
			return err
		}
		return runNoStateStatus(control, writer, config)
	}
	if request.Mode == modeLogout && store.empty() {
		if err := writer.emit(statusEvent{Type: "status", BackendState: ipn.NoState.String(), Peers: []peerDTO{}}); err != nil {
			return err
		}
		return control.emitComplete(writer, "logged_out")
	}

	tempDir, err := makePrivateTempDir(tempRoot, request.ConnectionID)
	if err != nil {
		writer.emitError("startup_failed")
		return errors.New("temporary state directory unavailable")
	}
	defer os.RemoveAll(tempDir)

	node, err := factory(request.Hostname, tempDir, store)
	if err != nil {
		writer.emitError("startup_failed")
		return errors.New("tsnet startup failed")
	}

	nodeClosed := false
	shutdown := func(reason string) error {
		if !nodeClosed {
			nodeClosed = true
			if err := node.Close(); err != nil {
				if control.hasFailed() {
					writer.emitError(control.failureCode())
				} else {
					writer.emitError("shutdown_failed")
				}
				return errors.New("tsnet shutdown failed")
			}
		}
		if control.hasFailed() {
			if reason != "" {
				writer.emitError(control.failureCode())
			}
			return errors.New("parent control failed during shutdown")
		}
		if err := os.RemoveAll(tempDir); err != nil {
			writer.emitError("shutdown_failed")
			return errors.New("temporary state cleanup failed")
		}
		if reason != "" {
			if err := control.emitComplete(writer, reason); err != nil {
				return errors.New("completion event failed")
			}
		}
		return nil
	}
	defer func() {
		if !nodeClosed {
			_ = node.Close()
		}
	}()

	if request.Mode == modeLogout {
		ctx, cancel := context.WithTimeout(context.Background(), config.logoutDuration)
		logoutErr := node.Logout(ctx)
		cancel()
		if logoutErr != nil {
			writer.emitError("logout_failed")
			if err := shutdown("timeout"); err != nil {
				return err
			}
			return errors.New("logout failed")
		}
		status, statusErr := getStatus(node, config)
		if statusErr != nil {
			writer.emitError("status_unavailable")
			_ = shutdown("")
			return errors.New("status unavailable")
		}
		if err := writer.emit(statusToEvent(status, false)); err != nil {
			_ = shutdown("")
			return err
		}
		return shutdown("logged_out")
	}

	reason, runErr := monitorNode(request.Mode, node, control, writer, config)
	if runErr != nil {
		if control.hasFailed() {
			writer.emitError(control.failureCode())
		} else if errors.Is(runErr, errInteractiveLogin) {
			writer.emitError("interactive_login_failed")
		} else {
			writer.emitError("status_unavailable")
		}
		_ = shutdown("")
		return errors.New("broker monitoring failed")
	}
	return shutdown(reason)
}

func makePrivateTempDir(root, connectionID string) (string, error) {
	if root == "" {
		root = os.TempDir()
	}
	dir, err := os.MkdirTemp(root, "agenticos-tsnet-"+connectionID+"-")
	if err != nil {
		return "", err
	}
	if err := os.Chmod(dir, 0o700); err != nil {
		_ = os.RemoveAll(dir)
		return "", err
	}
	return filepath.Clean(dir), nil
}

func monitorNode(requestMode mode, node tailnetNode, control *controlSession, writer *eventWriter, config brokerConfig) (string, error) {
	duration := config.statusDuration
	if requestMode == modeEnroll {
		duration = config.enrollDuration
	} else if requestMode != modeStatus {
		return "", errors.New("unsupported broker mode")
	}
	deadline := time.NewTimer(duration)
	defer deadline.Stop()
	ticker := time.NewTicker(config.statusInterval)
	defer ticker.Stop()
	wasReady := false
	loginStarted := false

	for {
		status, err := getStatus(node, config)
		if err != nil {
			return "", err
		}
		// A restored identity may report Starting/Stopped while tsnet resumes.
		// Only NeedsLogin means an interactive login is actually required.
		if requestMode == modeEnroll && !loginStarted && status.BackendState == ipn.NeedsLogin.String() {
			loginStarted = true
			ctx, cancel := context.WithTimeout(context.Background(), config.statusCallTimeout)
			loginErr := node.StartLoginInteractive(ctx)
			cancel()
			if loginErr != nil {
				return "", errInteractiveLogin
			}
			status, err = getStatus(node, config)
			if err != nil {
				return "", err
			}
		}
		ready := authenticatedStatus(status)
		wasReady = ready
		if err := writer.emit(statusToEvent(status, requestMode != modeLogout)); err != nil {
			control.fail("output_failed")
			return "", err
		}
		if requestMode == modeEnroll && ready {
			return "ready", nil
		}
		select {
		case <-control.fatal:
			return "", protocolFailure(control.failureCode())
		case <-control.stop:
			return "stopped", nil
		case <-deadline.C:
			if requestMode == modeStatus && wasReady {
				return "ready", nil
			}
			return "timeout", nil
		case <-ticker.C:
		}
	}
}

func runNoStateStatus(control *controlSession, writer *eventWriter, config brokerConfig) error {
	ticker := time.NewTicker(config.statusInterval)
	defer ticker.Stop()
	deadline := time.NewTimer(config.statusDuration)
	defer deadline.Stop()
	for {
		select {
		case <-control.fatal:
			writer.emitError(control.failureCode())
			return protocolFailure(control.failureCode())
		case <-control.stop:
			return control.emitComplete(writer, "stopped")
		case <-deadline.C:
			return control.emitComplete(writer, "timeout")
		case <-ticker.C:
			if err := writer.emit(statusEvent{Type: "status", BackendState: ipn.NoState.String(), Peers: []peerDTO{}}); err != nil {
				return err
			}
		}
	}
}

func getStatus(node tailnetNode, config brokerConfig) (*ipnstate.Status, error) {
	ctx, cancel := context.WithTimeout(context.Background(), config.statusCallTimeout)
	defer cancel()
	status, err := node.Status(ctx)
	if err != nil || status == nil {
		return nil, errors.New("status unavailable")
	}
	return status, nil
}

func statusToEvent(status *ipnstate.Status, allowAuthURL bool) statusEvent {
	event := statusEvent{Type: "status", BackendState: status.BackendState, Peers: make([]peerDTO, 0)}
	if allowAuthURL {
		event.AuthURL = trustedAuthURL(status.AuthURL)
	}
	if status.CurrentTailnet != nil {
		event.TailnetName = requiredString(status.CurrentTailnet.Name)
	}
	if status.Self != nil {
		event.NodeID = requiredString(string(status.Self.ID))
		event.KeyExpired = status.Self.Expired
	}
	for _, peer := range status.Peer {
		if peer == nil || peer.ID == "" {
			continue
		}
		dto := peerDTO{
			ID:       string(peer.ID),
			Hostname: peer.HostName,
			DNSName:  peer.DNSName,
			IPs:      peerIPs(peer.TailscaleIPs),
			Online:   peer.Online,
			OS:       peer.OS,
		}
		event.Peers = append(event.Peers, dto)
	}
	sort.Slice(event.Peers, func(i, j int) bool {
		left, right := event.Peers[i], event.Peers[j]
		if left.ID != right.ID {
			return left.ID < right.ID
		}
		if left.Hostname != right.Hostname {
			return left.Hostname < right.Hostname
		}
		if left.DNSName != right.DNSName {
			return left.DNSName < right.DNSName
		}
		return strings.Join(left.IPs, ",") < strings.Join(right.IPs, ",")
	})
	if len(event.Peers) > maxPeers {
		event.Peers = event.Peers[:maxPeers]
	}
	return event
}

func peerIPs(addresses []netip.Addr) []string {
	ips := make([]string, 0, len(addresses))
	for _, address := range addresses {
		if address.IsValid() {
			ips = append(ips, address.String())
		}
	}
	sort.Strings(ips)
	return ips
}

func authenticatedStatus(status *ipnstate.Status) bool {
	return status != nil &&
		status.BackendState == ipn.Running.String() &&
		status.Self != nil && status.Self.ID != "" && !status.Self.Expired &&
		status.CurrentTailnet != nil && status.CurrentTailnet.Name != ""
}
