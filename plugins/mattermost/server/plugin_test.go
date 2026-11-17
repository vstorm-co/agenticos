package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/plugin"
)

const orgID = "11111111-1111-4111-8111-111111111111"
const agentID = "22222222-2222-4222-8222-222222222222"
const remoteID = "33333333-3333-4333-8333-333333333333"
const userID = "aaaaaaaaaaaaaaaaaaaaaaaaaa"
const botID = "bbbbbbbbbbbbbbbbbbbbbbbbbb"
const teamID = "cccccccccccccccccccccccccc"
const channelID = "dddddddddddddddddddddddddd"
const setupToken = "test-admin-access-token"
const botToken = "test-bot-token-only"

type fakeAPI struct {
	plugin.API
	mu      sync.Mutex
	kv      map[string][]byte
	cfg     configuration
	isAdmin bool
	revoked int
	invites int
	dialogs []model.OpenDialogRequest
	posts   []string
}

func newFake() *fakeAPI {
	return &fakeAPI{kv: map[string][]byte{}, cfg: configuration{"https://agenticos.example", orgID, agentID}, isAdmin: true}
}
func (f *fakeAPI) KVGet(k string) ([]byte, *model.AppError) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]byte(nil), f.kv[k]...), nil
}
func (f *fakeAPI) KVSet(k string, v []byte) *model.AppError {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.kv[k] = append([]byte(nil), v...)
	return nil
}
func (f *fakeAPI) KVDelete(k string) *model.AppError {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.kv, k)
	return nil
}
func (f *fakeAPI) KVSetWithExpiry(k string, v []byte, _ int64) *model.AppError { return f.KVSet(k, v) }
func (f *fakeAPI) KVCompareAndDelete(k string, old []byte) (bool, *model.AppError) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if string(f.kv[k]) != string(old) {
		return false, nil
	}
	delete(f.kv, k)
	return true, nil
}
func (f *fakeAPI) KVSetWithOptions(k string, v []byte, o model.PluginKVSetOptions) (bool, *model.AppError) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if o.Atomic && string(f.kv[k]) != string(o.OldValue) {
		return false, nil
	}
	if len(v) == 0 {
		delete(f.kv, k)
	} else {
		f.kv[k] = append([]byte(nil), v...)
	}
	return true, nil
}
func (f *fakeAPI) LogError(string, ...interface{}) {}
func (f *fakeAPI) LoadPluginConfiguration(dest interface{}) error {
	data, _ := json.Marshal(f.cfg)
	return json.Unmarshal(data, dest)
}
func (f *fakeAPI) GetUser(string) (*model.User, *model.AppError) {
	roles := "system_user"
	if f.isAdmin {
		roles += " system_admin"
	}
	return &model.User{Id: userID, Roles: roles}, nil
}
func (f *fakeAPI) OpenInteractiveDialog(d model.OpenDialogRequest) *model.AppError {
	f.dialogs = append(f.dialogs, d)
	return nil
}
func (f *fakeAPI) SendEphemeralPost(_ string, p *model.Post) *model.Post {
	f.posts = append(f.posts, p.Message)
	return p
}
func (f *fakeAPI) GetConfig() *model.Config {
	site := "https://mattermost.example"
	return &model.Config{ServiceSettings: model.ServiceSettings{SiteURL: &site}}
}
func (f *fakeAPI) EnsureBotUser(*model.Bot) (string, error) { return botID, nil }
func (f *fakeAPI) GetChannel(string) (*model.Channel, *model.AppError) {
	return &model.Channel{Id: channelID, TeamId: teamID}, nil
}
func missing() *model.AppError { return &model.AppError{StatusCode: 404} }
func (f *fakeAPI) GetTeamMember(string, string) (*model.TeamMember, *model.AppError) {
	return nil, missing()
}
func (f *fakeAPI) CreateTeamMember(string, string) (*model.TeamMember, *model.AppError) {
	return &model.TeamMember{}, nil
}
func (f *fakeAPI) GetChannelMember(string, string) (*model.ChannelMember, *model.AppError) {
	return nil, missing()
}
func (f *fakeAPI) AddChannelMember(string, string) (*model.ChannelMember, *model.AppError) {
	f.invites++
	return &model.ChannelMember{}, nil
}
func (f *fakeAPI) CreateUserAccessToken(*model.UserAccessToken) (*model.UserAccessToken, *model.AppError) {
	return &model.UserAccessToken{Id: "eeeeeeeeeeeeeeeeeeeeeeeeee", Token: botToken}, nil
}
func (f *fakeAPI) RevokeUserAccessToken(string) *model.AppError { f.revoked++; return nil }
func instance(t *testing.T, h http.HandlerFunc) (*httptest.Server, instanceClient) {
	t.Helper()
	s := httptest.NewTLSServer(h)
	t.Cleanup(s.Close)
	c := s.Client()
	c.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return s, instanceClient{c, configuration{s.URL, orgID, agentID}, setupToken}
}
func state(c configuration) dialogState {
	return dialogState{userID, channelID, teamID, "connect", c, time.Now().Add(time.Minute).Unix()}
}

func TestConnectAndDisconnect(t *testing.T) {
	requests := 0
	s, client := instance(t, func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.Header.Get("Authorization") != "Bearer "+setupToken || r.Header.Get("X-Organization-Id") != orgID {
			t.Error("wrong authority")
		}
		switch r.Method + " " + r.URL.Path {
		case "POST /api/v1/channels/bots":
			var b botRegistration
			_ = json.NewDecoder(r.Body).Decode(&b)
			if b.Token != botToken || b.Platform != "mattermost" || b.AccessPolicy.Mode != "jwt_linked" || b.WebhookMode || b.APIBaseURL != "https://mattermost.example" {
				t.Error("unsafe registration")
			}
			w.WriteHeader(201)
			_, _ = w.Write([]byte(`{"id":"` + remoteID + `"}`))
		case "POST /api/v1/agents/" + agentID + "/exposures":
			var e exposureRegistration
			_ = json.NewDecoder(r.Body).Decode(&e)
			if e.ChannelBotID != remoteID {
				t.Error("wrong binding")
			}
			w.WriteHeader(201)
			_, _ = w.Write([]byte(`{"id":"` + remoteID + `"}`))
		case "DELETE /api/v1/channels/bots/" + remoteID:
			w.WriteHeader(204)
		default:
			t.Error("unexpected request")
			w.WriteHeader(500)
		}
	})
	f := newFake()
	f.cfg.AgenticOSURL = s.URL
	p := &Plugin{}
	p.SetAPI(f)
	if err := p.connect(context.Background(), client, state(f.cfg)); err != nil {
		t.Fatal(err)
	}
	c, _ := p.loadConnection()
	if c == nil || c.Phase != "connected" || f.invites != 1 {
		t.Fatal("missing connection")
	}
	if p.connect(context.Background(), client, state(f.cfg)) == nil {
		t.Fatal("duplicate accepted")
	}
	for _, v := range f.kv {
		if strings.Contains(string(v), setupToken) || strings.Contains(string(v), botToken) {
			t.Fatal("credential persisted")
		}
	}
	if err := p.disconnect(context.Background(), client); err != nil {
		t.Fatal(err)
	}
	if f.revoked != 1 || requests != 3 {
		t.Fatal("wrong cleanup")
	}
	c, _ = p.loadConnection()
	if c != nil {
		t.Fatal("connection retained")
	}
}
func TestFailedSetupRevokesAndKeepsJournal(t *testing.T) {
	for _, stage := range []string{"register", "bind", "deferred", "malformed"} {
		t.Run(stage, func(t *testing.T) {
			s, client := instance(t, func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/api/v1/channels/bots" && stage != "register" {
					w.WriteHeader(201)
					if stage == "malformed" {
						_, _ = w.Write([]byte(`{"id":"bad"}`))
					} else {
						_, _ = w.Write([]byte(`{"id":"` + remoteID + `"}`))
					}
					return
				}
				if stage == "deferred" {
					w.WriteHeader(202)
				} else {
					w.WriteHeader(403)
				}
				_, _ = w.Write([]byte(setupToken))
			})
			f := newFake()
			f.cfg.AgenticOSURL = s.URL
			p := &Plugin{}
			p.SetAPI(f)
			err := p.connect(context.Background(), client, state(f.cfg))
			if err == nil || strings.Contains(err.Error(), setupToken) {
				t.Fatal("unsafe result")
			}
			c, _ := p.loadConnection()
			if c == nil || c.Phase != "setup_pending" || f.revoked != 1 {
				t.Fatal("missing journal/revocation")
			}
		})
	}
}
func TestClientRefusesUnsafeResponse(t *testing.T) {
	reached := false
	target := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { reached = true }))
	defer target.Close()
	for _, mode := range []string{"redirect", "oversize", "secret"} {
		t.Run(mode, func(t *testing.T) {
			_, c := instance(t, func(w http.ResponseWriter, r *http.Request) {
				if mode == "redirect" {
					http.Redirect(w, r, target.URL, 307)
					return
				}
				if mode == "secret" {
					w.WriteHeader(500)
					_, _ = w.Write([]byte(setupToken))
					return
				}
				w.WriteHeader(201)
				_, _ = w.Write([]byte(strings.Repeat(" ", 65537) + `{"id":"` + remoteID + `"}`))
			})
			var id resourceID
			if c.request(context.Background(), "POST", "/channels/bots", nil, &id) != errRemote {
				t.Fatal("unsafe response accepted")
			}
		})
	}
	if reached {
		t.Fatal("credential redirect followed")
	}
}
func TestOrigins(t *testing.T) {
	for _, bad := range []string{"http://localhost", "https://user:pass@host", "https://host/path", "https://host?x=1", "https://host#x", "https://host?", "file:///tmp/x"} {
		if validOrigin(bad) {
			t.Errorf("accepted %s", bad)
		}
	}
	if !validOrigin("https://agenticos.internal:8443") {
		t.Fatal("private origin refused")
	}
}
func TestDialogAdmission(t *testing.T) {
	for _, test := range []string{"nonadmin", "identity", "expired", "changed", "replay", "valid"} {
		t.Run(test, func(t *testing.T) {
			f := newFake()
			p := &Plugin{}
			p.SetAPI(f)
			_, _ = p.ExecuteCommand(nil, &model.CommandArgs{UserId: userID, ChannelId: channelID, TeamId: teamID, Command: "/agenticos connect"})
			if len(f.dialogs) != 1 || f.dialogs[0].Dialog.Elements[0].SubType != "password" {
				t.Fatal("missing private dialog")
			}
			if err := f.dialogs[0].Dialog.IsValid(); err != nil {
				t.Fatal(err)
			}
			nonce := f.dialogs[0].Dialog.State
			data := state(f.cfg)
			if test == "expired" {
				data.Expires = 1
			}
			raw, _ := json.Marshal(data)
			_ = f.KVSet("dialog-"+nonce, raw)
			body := model.SubmitDialogRequest{UserId: userID, ChannelId: channelID, TeamId: teamID, State: nonce, CallbackId: "connect", Submission: map[string]interface{}{"access_token": setupToken}}
			switch test {
			case "nonadmin":
				f.isAdmin = false
			case "identity":
				body.UserId = botID
			case "changed":
				f.cfg.AgentID = remoteID
			case "replay":
				_ = f.KVDelete("dialog-" + nonce)
			}
			_ = p.saveConnection(connection{Config: data.Config, Phase: "connected"})
			encoded, _ := json.Marshal(body)
			r := httptest.NewRequest("POST", "/setup", strings.NewReader(string(encoded)))
			r.Header.Set("Mattermost-User-ID", userID)
			w := httptest.NewRecorder()
			p.ServeHTTP(nil, w, r)
			if test == "valid" {
				if w.Code != 200 || len(f.posts) != 1 {
					t.Fatal("valid refused")
				}
				left, _ := f.KVGet("dialog-" + nonce)
				if len(left) != 0 {
					t.Fatal("reusable nonce")
				}
			} else if test == "changed" {
				if !strings.Contains(w.Body.String(), "Configuration changed") {
					t.Fatal("change accepted")
				}
			} else if w.Code < 400 {
				t.Fatal("invalid admitted")
			}
			if strings.Contains(w.Body.String(), setupToken) {
				t.Fatal("token exposed")
			}
		})
	}
}
func TestDisconnectUnavailable(t *testing.T) {
	_, client := instance(t, func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(503) })
	f := newFake()
	p := &Plugin{}
	p.SetAPI(f)
	_ = p.saveConnection(connection{Config: client.config, TokenID: "token-id", RemoteBotID: remoteID, Phase: "connected"})
	if p.disconnect(context.Background(), client) == nil || f.revoked != 1 {
		t.Fatal("cleanup claimed success")
	}
	c, _ := p.loadConnection()
	if c == nil || c.Phase != "disconnect_pending" {
		t.Fatal("lost cleanup handle")
	}
}

func TestConcurrentDialogIsSingleUse(t *testing.T) {
	f := newFake()
	p := &Plugin{}
	p.SetAPI(f)
	_, _ = p.ExecuteCommand(nil, &model.CommandArgs{UserId: userID, ChannelId: channelID, TeamId: teamID, Command: "/agenticos connect"})
	nonce := f.dialogs[0].Dialog.State
	_ = p.saveConnection(connection{Config: f.cfg, Phase: "connected"})
	body, _ := json.Marshal(model.SubmitDialogRequest{UserId: userID, ChannelId: channelID, TeamId: teamID, State: nonce, CallbackId: "connect", Submission: map[string]interface{}{"access_token": setupToken}})
	var wg sync.WaitGroup
	codes := make(chan int, 10)
	for range 10 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r := httptest.NewRequest("POST", "/setup", strings.NewReader(string(body)))
			r.Header.Set("Mattermost-User-ID", userID)
			w := httptest.NewRecorder()
			p.ServeHTTP(nil, w, r)
			codes <- w.Code
		}()
	}
	wg.Wait()
	close(codes)
	accepted := 0
	for code := range codes {
		if code == 200 {
			accepted++
		}
	}
	if accepted != 1 || len(f.posts) != 1 {
		t.Fatalf("admitted %d copies", accepted)
	}
}

func TestHTTPAndCommandBoundaries(t *testing.T) {
	f := newFake()
	p := &Plugin{}
	p.SetAPI(f)
	for _, tc := range []struct {
		method, path, body, user string
		status                   int
	}{
		{"GET", "/setup", "", userID, 405},
		{"POST", "/other", "", userID, 404},
		{"POST", "/setup", "{}", "", 403},
		{"POST", "/setup", strings.Repeat("x", 20000), userID, 400},
		{"POST", "/setup", "{} {}", userID, 400},
	} {
		r := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
		r.Header.Set("Mattermost-User-ID", tc.user)
		w := httptest.NewRecorder()
		p.ServeHTTP(nil, w, r)
		if w.Code != tc.status {
			t.Fatalf("%s %s: %d", tc.method, tc.path, w.Code)
		}
	}
	f.isAdmin = false
	result, _ := p.ExecuteCommand(nil, &model.CommandArgs{UserId: userID, Command: "/agenticos connect"})
	if !strings.Contains(result.Text, "Only a Mattermost system administrator") || len(f.dialogs) != 0 {
		t.Fatal("nonadmin command admitted")
	}
	f.isAdmin = true
	f.cfg.AgenticOSURL = "http://insecure.example"
	_, _ = p.ExecuteCommand(nil, &model.CommandArgs{UserId: userID, TeamId: teamID, ChannelId: channelID, Command: "/agenticos connect"})
	if len(f.dialogs) != 0 {
		t.Fatal("insecure setup admitted")
	}
}

func TestDisconnectTargetsOriginalInstance(t *testing.T) {
	f := newFake()
	p := &Plugin{}
	p.SetAPI(f)
	old := f.cfg
	old.AgenticOSURL = "https://original.example"
	_ = p.saveConnection(connection{Config: old, Phase: "connected", RemoteBotID: remoteID})
	_, _ = p.ExecuteCommand(nil, &model.CommandArgs{UserId: userID, TeamId: teamID, ChannelId: channelID, Command: "/agenticos disconnect"})
	raw, _ := f.KVGet("dialog-" + f.dialogs[0].Dialog.State)
	var saved dialogState
	_ = json.Unmarshal(raw, &saved)
	if saved.Config != old || !strings.Contains(f.dialogs[0].Dialog.IntroductionText, old.AgenticOSURL) {
		t.Fatal("disconnect authority moved to a different instance")
	}
	if p.disconnect(context.Background(), instanceClient{newHTTPClient(), f.cfg, setupToken}) == nil {
		t.Fatal("changed target admitted")
	}
}

func TestRequestCancellation(t *testing.T) {
	_, client := instance(t, func(w http.ResponseWriter, _ *http.Request) { t.Error("cancelled request reached instance") })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var id resourceID
	if client.request(ctx, "POST", "/channels/bots", nil, &id) != errRemote {
		t.Fatal("cancellation hidden as success")
	}
}
