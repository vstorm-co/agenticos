package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

var uuidPattern = regexp.MustCompile(`^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$`)
var errRemote = errors.New("AgenticOS did not confirm the operation. Check the instance URL, permissions and connectivity; do not retry an uncertain registration before disconnecting")

type configuration struct {
	AgenticOSURL   string
	OrganizationID string
	AgentID        string
}

func validOrigin(raw string) bool {
	u, err := url.Parse(raw)
	return err == nil && u.Scheme == "https" && u.Hostname() != "" && u.User == nil && u.RawQuery == "" && u.Fragment == "" && (u.Path == "" || u.Path == "/") && u.Opaque == "" && !u.ForceQuery
}

func (c configuration) valid() bool {
	return validOrigin(c.AgenticOSURL) && uuidPattern.MatchString(c.OrganizationID) && uuidPattern.MatchString(c.AgentID)
}

func newHTTPClient() *http.Client {
	// Setup credentials must reach only the configured instance, without environment proxies.
	transport := &http.Transport{
		DialContext:         (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSHandshakeTimeout: 10 * time.Second,
		IdleConnTimeout:     30 * time.Second,
		MaxIdleConns:        10,
		ForceAttemptHTTP2:   true,
	}
	return &http.Client{Timeout: 15 * time.Second, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

type instanceClient struct {
	http   *http.Client
	config configuration
	bearer string
}

type botRegistration struct {
	Platform     string `json:"platform"`
	Name         string `json:"name"`
	Token        string `json:"token"`
	APIBaseURL   string `json:"api_base_url"`
	WebhookMode  bool   `json:"webhook_mode"`
	AccessPolicy struct {
		Mode string `json:"mode"`
	} `json:"access_policy"`
}
type registration interface{ registrationBody() }

func (botRegistration) registrationBody()      {}
func (exposureRegistration) registrationBody() {}

type resourceID struct {
	ID string `json:"id"`
}
type exposureRegistration struct {
	ChannelBotID string `json:"channel_bot_id"`
}

// Provider responses and transport errors can contain credentials; never return them.
func (c instanceClient) request(ctx context.Context, method, path string, body registration, result *resourceID) error {
	var payload bytes.Buffer
	if body != nil {
		if err := json.NewEncoder(&payload).Encode(body); err != nil {
			return errRemote
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(c.config.AgenticOSURL, "/")+"/api/v1"+path, &payload)
	if err != nil {
		return errRemote
	}
	req.Header.Set("Authorization", "Bearer "+c.bearer)
	req.Header.Set("X-Organization-Id", c.config.OrganizationID)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return errRemote
	}
	defer resp.Body.Close()
	expected := http.StatusCreated
	if method == http.MethodDelete {
		expected = http.StatusNoContent
	}
	if resp.StatusCode != expected {
		if method == http.MethodDelete && resp.StatusCode == http.StatusNotFound {
			return nil
		}
		return errRemote
	}
	if result == nil {
		return nil
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
	if err != nil || len(data) > 65536 || json.Unmarshal(data, result) != nil || !uuidPattern.MatchString(result.ID) {
		return errRemote
	}
	return nil
}
