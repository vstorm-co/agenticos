package main

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const (
	protocolVersion  = 1
	maxFrameBytes    = 1 << 20
	maxStateBytes    = 512 << 10
	maxStateKeys     = 256
	maxStateKeyBytes = 256
	maxPeers         = 1024
	readerBufferSize = 32 << 10
)

var (
	errFrameTooLarge = errors.New("frame too large")
	errInvalidFrame  = errors.New("invalid frame")
	errUnexpectedEOF = errors.New("incomplete frame")
	connectionIDRE   = regexp.MustCompile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
	hostnameRE       = regexp.MustCompile("^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
)

type mode string

const (
	modeEnroll mode = "enroll"
	modeStatus mode = "status"
	modeLogout mode = "logout"
)

type startFrame struct {
	Version      int               `json:"version"`
	Type         string            `json:"type"`
	ConnectionID string            `json:"connection_id"`
	Hostname     string            `json:"hostname"`
	Mode         mode              `json:"mode"`
	State        map[string]string `json:"state"`
}

type controlFrame struct {
	Type     string  `json:"type"`
	Sequence *uint64 `json:"sequence,omitempty"`
	OK       *bool   `json:"ok,omitempty"`
	Error    string  `json:"error,omitempty"`
}

type stateEvent struct {
	Type     string            `json:"type"`
	Sequence uint64            `json:"sequence"`
	State    map[string]string `json:"state"`
}

type errorEvent struct {
	Type string `json:"type"`
	Code string `json:"code"`
}

type completeEvent struct {
	Type   string `json:"type"`
	Reason string `json:"reason"`
}

type peerDTO struct {
	ID       string   `json:"id"`
	Hostname string   `json:"hostname"`
	DNSName  string   `json:"dns_name"`
	IPs      []string `json:"ips"`
	Online   bool     `json:"online"`
	OS       string   `json:"os"`
}

type statusEvent struct {
	Type         string    `json:"type"`
	BackendState string    `json:"backend_state"`
	AuthURL      *string   `json:"auth_url"`
	TailnetName  *string   `json:"tailnet_name"`
	NodeID       *string   `json:"node_id"`
	KeyExpired   bool      `json:"key_expired"`
	Peers        []peerDTO `json:"peers"`
}

type eventWriter struct {
	mu sync.Mutex
	w  io.Writer
}

func newEventWriter(w io.Writer) *eventWriter {
	return &eventWriter{w: w}
}

func (w *eventWriter) emit(event any) error {
	encoded, err := json.Marshal(event)
	if err != nil {
		return errors.New("event encoding failed")
	}
	if len(encoded)+1 > maxFrameBytes {
		return errFrameTooLarge
	}
	encoded = append(encoded, '\n')

	w.mu.Lock()
	defer w.mu.Unlock()
	for len(encoded) > 0 {
		n, writeErr := w.w.Write(encoded)
		if writeErr != nil || n == 0 {
			return errors.New("event write failed")
		}
		encoded = encoded[n:]
	}
	return nil
}

func (w *eventWriter) emitError(code string) {
	_ = w.emit(errorEvent{Type: "error", Code: code})
}

func readJSONLine(reader *bufio.Reader, maxBytes int) ([]byte, error) {
	var line []byte
	for {
		part, err := reader.ReadSlice('\n')
		if len(line)+len(part) > maxBytes {
			return nil, errFrameTooLarge
		}
		line = append(line, part...)
		if err == nil {
			line = bytes.TrimSuffix(line, []byte{'\n'})
			line = bytes.TrimSuffix(line, []byte{'\r'})
			return line, nil
		}
		if errors.Is(err, bufio.ErrBufferFull) {
			continue
		}
		if errors.Is(err, io.EOF) {
			if len(line) == 0 {
				return nil, io.EOF
			}
			return nil, errUnexpectedEOF
		}
		return nil, errInvalidFrame
	}
}

func decodeStrictJSON(line []byte, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return errInvalidFrame
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return errInvalidFrame
	}
	return nil
}

func readStart(reader *bufio.Reader) (startFrame, map[string][]byte, string) {
	line, err := readJSONLine(reader, maxFrameBytes)
	if err != nil {
		if errors.Is(err, errFrameTooLarge) {
			return startFrame{}, nil, "frame_too_large"
		}
		return startFrame{}, nil, "invalid_start"
	}

	var frame startFrame
	if decodeStrictJSON(line, &frame) != nil {
		return startFrame{}, nil, "invalid_start"
	}
	if frame.Version != protocolVersion || frame.Type != "start" ||
		!connectionIDRE.MatchString(frame.ConnectionID) ||
		!hostnameRE.MatchString(frame.Hostname) ||
		(frame.Mode != modeEnroll && frame.Mode != modeStatus && frame.Mode != modeLogout) {
		return startFrame{}, nil, "invalid_start"
	}
	state, err := decodeState(frame.State)
	if err != nil {
		return startFrame{}, nil, "invalid_start"
	}
	return frame, state, ""
}

func decodeState(encoded map[string]string) (map[string][]byte, error) {
	if len(encoded) > maxStateKeys {
		return nil, errInvalidFrame
	}
	decoded := make(map[string][]byte, len(encoded))
	total := 0
	for key, value := range encoded {
		if key == "" || len([]byte(key)) > maxStateKeyBytes {
			return nil, errInvalidFrame
		}
		stateBytes, err := base64.StdEncoding.DecodeString(value)
		if err != nil || len(stateBytes) > maxStateBytes-total {
			return nil, errInvalidFrame
		}
		total += len(stateBytes)
		decoded[key] = bytes.Clone(stateBytes)
	}
	return decoded, nil
}

func validateControlFrame(frame controlFrame) (kind string, seq uint64, code string) {
	switch frame.Type {
	case "heartbeat":
		if frame.Sequence != nil || frame.OK != nil || frame.Error != "" {
			return "", 0, "invalid_control"
		}
		return "heartbeat", 0, ""
	case "stop":
		if frame.Sequence != nil || frame.OK != nil || frame.Error != "" {
			return "", 0, "invalid_control"
		}
		return "stop", 0, ""
	case "ack":
		if frame.Sequence == nil || *frame.Sequence == 0 {
			return "", 0, "invalid_control"
		}
		if (frame.OK != nil && !*frame.OK) || frame.Error != "" {
			return "", *frame.Sequence, "state_persist_failed"
		}
		return "ack", *frame.Sequence, ""
	default:
		return "", 0, "invalid_control"
	}
}

func trustedAuthURL(raw string) *string {
	if len(raw) == 0 || len(raw) > 4096 {
		return nil
	}
	for index := 0; index < len(raw); index++ {
		if raw[index] < 0x20 || raw[index] > 0x7e {
			return nil
		}
	}
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme != "https" || parsed.Opaque != "" || parsed.User != nil || parsed.Hostname() == "" {
		return nil
	}
	if port := parsed.Port(); port != "" && port != "443" {
		return nil
	}
	if !strings.EqualFold(parsed.Hostname(), "login.tailscale.com") {
		return nil
	}
	if parsed.Fragment != "" || !strings.HasPrefix(parsed.Path, "/a/") || !strings.HasPrefix(parsed.EscapedPath(), "/a/") {
		return nil
	}
	safe := parsed.String()
	return &safe
}

func requiredString(value string) *string {
	if value == "" {
		return nil
	}
	copyValue := value
	return &copyValue
}

func protocolFailure(code string) error {
	return errors.New(code)
}

type controlSession struct {
	reader            *bufio.Reader
	lastHeartbeat     atomic.Pointer[time.Time]
	completionPending atomic.Bool
	done              chan struct{}
	lifecycleMu       sync.Mutex
	finished          bool
	failed            bool
	fatal             chan struct{}
	fatalCode         atomic.Value
	stopOnce          sync.Once
	stop              chan struct{}
	ackMu             sync.Mutex
	pendingSequence   uint64
	pendingAck        chan error
	config            brokerConfig
}

func newControlSession(reader *bufio.Reader, config brokerConfig) *controlSession {
	control := &controlSession{
		reader: reader,
		fatal:  make(chan struct{}),
		stop:   make(chan struct{}),
		done:   make(chan struct{}),
		config: config,
	}
	now := time.Now()
	control.lastHeartbeat.Store(&now)
	return control
}

func (c *controlSession) start() {
	go c.readLoop()
	go c.watchHeartbeat()
}

func (c *controlSession) readLoop() {
	for {
		line, err := readJSONLine(c.reader, maxFrameBytes)
		if err != nil {
			if c.isDone() {
				return
			}
			if errors.Is(err, io.EOF) && c.completionPending.Load() {
				// The parent closes stdin after receiving Complete. Wait for the
				// broker's deferred finish signal while the heartbeat watchdog
				// remains armed in case the parent actually vanished mid-write.
				select {
				case <-c.done:
					return
				case <-c.fatal:
					return
				}
			}
			if errors.Is(err, io.EOF) || errors.Is(err, errUnexpectedEOF) {
				c.fail("parent_eof")
			} else if errors.Is(err, errFrameTooLarge) {
				c.fail("frame_too_large")
			} else {
				c.fail("invalid_control")
			}
			return
		}
		var frame controlFrame
		if decodeStrictJSON(line, &frame) != nil {
			c.fail("invalid_control")
			return
		}
		kind, sequence, code := validateControlFrame(frame)
		if code != "" {
			c.fail(code)
			return
		}
		switch kind {
		case "heartbeat":
			now := time.Now()
			c.lastHeartbeat.Store(&now)
		case "stop":
			c.stopOnce.Do(func() { close(c.stop) })
			// Keep reading controls until the parent closes stdin. A graceful
			// tsnet Close may write one final state snapshot that still needs
			// an acknowledgement before Complete can be emitted.
		case "ack":
			c.resolveAck(sequence)
		}
	}
}

func (c *controlSession) watchHeartbeat() {
	interval := time.Second
	if quarter := c.config.heartbeatTimeout / 4; quarter > 0 && quarter < interval {
		interval = quarter
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-c.done:
			return
		case <-c.fatal:
			return
		case <-ticker.C:
			last := c.lastHeartbeat.Load()
			if last == nil || time.Since(*last) > c.config.heartbeatTimeout {
				c.fail("heartbeat_timeout")
				return
			}
		}
	}
}

func (c *controlSession) fail(code string) {
	c.lifecycleMu.Lock()
	if c.finished || c.failed {
		c.lifecycleMu.Unlock()
		return
	}
	c.failed = true
	c.fatalCode.Store(code)
	close(c.fatal)
	terminate := c.config.terminate
	c.lifecycleMu.Unlock()
	if terminate != nil {
		terminate()
	}
}

func (c *controlSession) emitComplete(writer *eventWriter, reason string) error {
	c.completionPending.Store(true)
	return writer.emit(completeEvent{Type: "complete", Reason: reason})
}

func (c *controlSession) finish() {
	c.lifecycleMu.Lock()
	if !c.finished {
		c.finished = true
		close(c.done)
	}
	c.lifecycleMu.Unlock()
}

func (c *controlSession) isDone() bool {
	select {
	case <-c.done:
		return true
	default:
		return false
	}
}

func (c *controlSession) failureCode() string {
	if code, ok := c.fatalCode.Load().(string); ok {
		return code
	}
	return "parent_protocol_error"
}

func (c *controlSession) hasFailed() bool {
	select {
	case <-c.fatal:
		return true
	default:
		return false
	}
}

func (c *controlSession) beginAck(sequence uint64) (<-chan error, error) {
	c.ackMu.Lock()
	defer c.ackMu.Unlock()
	select {
	case <-c.fatal:
		return nil, errors.New("parent control failed")
	default:
	}
	if c.pendingAck != nil {
		c.fail("invalid_control")
		return nil, errors.New("acknowledgement already pending")
	}
	c.pendingSequence = sequence
	c.pendingAck = make(chan error, 1)
	return c.pendingAck, nil
}

func (c *controlSession) cancelAck(sequence uint64) {
	c.ackMu.Lock()
	defer c.ackMu.Unlock()
	if c.pendingAck != nil && c.pendingSequence == sequence {
		c.pendingAck = nil
		c.pendingSequence = 0
	}
}

func (c *controlSession) resolveAck(sequence uint64) {
	c.ackMu.Lock()
	defer c.ackMu.Unlock()
	if c.pendingAck == nil || c.pendingSequence != sequence {
		c.fail("invalid_control")
		return
	}
	ack := c.pendingAck
	c.pendingAck = nil
	c.pendingSequence = 0
	ack <- nil
}

func (c *controlSession) persistState(writer *eventWriter, sequence uint64, state map[string]string) error {
	ack, err := c.beginAck(sequence)
	if err != nil {
		return err
	}
	if err := writer.emit(stateEvent{Type: "state", Sequence: sequence, State: state}); err != nil {
		c.cancelAck(sequence)
		c.fail("output_failed")
		return err
	}
	timer := time.NewTimer(c.config.ackTimeout)
	defer timer.Stop()
	select {
	case err := <-ack:
		if err != nil {
			c.fail("state_persist_failed")
			return errors.New("state persistence acknowledgement failed")
		}
		return nil
	case <-timer.C:
		c.fail("state_ack_timeout")
		return errors.New("state persistence acknowledgement timed out")
	case <-c.fatal:
		return errors.New("parent control failed")
	}
}

func (c *controlSession) closeInput(input io.Reader) {
	c.finish()
	if closer, ok := input.(io.Closer); ok {
		_ = closer.Close()
	}
}
