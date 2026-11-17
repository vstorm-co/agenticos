package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/mattermost/mattermost/server/public/model"
	"github.com/mattermost/mattermost/server/public/plugin"
	"github.com/mattermost/mattermost/server/public/pluginapi/cluster"
)

const pluginID = "co.vstorm.agenticos"
const connectionKey = "connection-v1"
const setupError = "Setup failed. Check plugin configuration and Mattermost bot-account permissions. Use /agenticos status before trying again."

type Plugin struct{ plugin.MattermostPlugin }

type dialogState struct {
	UserID    string
	ChannelID string
	TeamID    string
	Action    string
	Config    configuration
	Expires   int64
}

// Only identifiers and configuration are persisted. Neither bearer token is stored here.
type connection struct {
	Config      configuration
	BotID       string
	TokenID     string
	RemoteBotID string
	Phase       string
}

func (p *Plugin) OnActivate() error {
	return p.API.RegisterCommand(&model.Command{Trigger: "agenticos", AutoComplete: true, AutoCompleteDesc: "Connect your AgenticOS instance (system administrators)", AutoCompleteHint: "connect | status | invite | disconnect"})
}

func (p *Plugin) config() configuration {
	var c configuration
	if p.API.LoadPluginConfiguration(&c) != nil {
		return configuration{}
	}
	return c
}
func (p *Plugin) admin(id string) bool {
	if !model.IsValidId(id) {
		return false
	}
	u, e := p.API.GetUser(id)
	return e == nil && u != nil && u.DeleteAt == 0 && u.IsSystemAdmin()
}
func response(text string) *model.CommandResponse {
	return &model.CommandResponse{ResponseType: model.CommandResponseTypeEphemeral, Text: text}
}

func (p *Plugin) ExecuteCommand(_ *plugin.Context, args *model.CommandArgs) (*model.CommandResponse, *model.AppError) {
	if !p.admin(args.UserId) {
		return response("Only a Mattermost system administrator can configure AgenticOS."), nil
	}
	parts := strings.Fields(args.Command)
	if len(parts) != 2 {
		return response("Use /agenticos connect, status, invite or disconnect. Never include a token in a command."), nil
	}
	action := parts[1]
	if action == "status" {
		c, err := p.loadConnection()
		if err != nil {
			return response(setupError), nil
		}
		if c == nil {
			return response("AgenticOS is not connected. Configure the plugin in System Console, then use /agenticos connect in the target channel."), nil
		}
		return response("AgenticOS setup state: **" + c.Phase + "**. This reports registration, not live agent health. Manage the channel in AgenticOS → Channels."), nil
	}
	if action == "invite" {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		err := p.withLock(ctx, func() error {
			c, e := p.loadConnection()
			if e != nil {
				return e
			}
			if c == nil || c.Phase != "connected" {
				return errors.New("Connect an agent first.")
			}
			return p.invite(c.BotID, args.TeamId, args.ChannelId)
		})
		if err != nil {
			return response("Could not invite the bot. Confirm a connected agent and run this command in a team channel."), nil
		}
		return response("Added @agenticos to this channel. Each person must link their own AgenticOS identity before using the agent."), nil
	}
	if action != "connect" && action != "disconnect" {
		return response("Use /agenticos connect, status, invite or disconnect."), nil
	}
	cfg := p.config()
	if action == "disconnect" {
		c, e := p.loadConnection()
		if e != nil {
			return response(setupError), nil
		}
		if c == nil {
			return response("No connection to disconnect."), nil
		}
		cfg = c.Config
	}
	if !cfg.valid() {
		return response("Set an HTTPS AgenticOS origin, organization UUID and agent UUID in System Console → Plugins → AgenticOS."), nil
	}
	if action == "connect" && (!model.IsValidId(args.TeamId) || !model.IsValidId(args.ChannelId)) {
		return response("Run /agenticos connect in the team channel where the bot should be added."), nil
	}
	var nonce [32]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return response(setupError), nil
	}
	state := hex.EncodeToString(nonce[:])
	data, _ := json.Marshal(dialogState{args.UserId, args.ChannelId, args.TeamId, action, cfg, time.Now().Add(5 * time.Minute).Unix()})
	if p.API.KVSetWithExpiry("dialog-"+state, data, 300) != nil {
		return response(setupError), nil
	}
	err := p.API.OpenInteractiveDialog(model.OpenDialogRequest{TriggerId: args.TriggerId, URL: "/plugins/" + pluginID + "/setup", Dialog: model.Dialog{
		CallbackId: action, Title: "AgenticOS " + action, SubmitLabel: "Confirm", State: state,
		IntroductionText: "Target: " + cfg.AgenticOSURL + " · organization " + cfg.OrganizationID + ". Enter a short-lived AgenticOS access token with channels:manage and permission to publish this agent. It is used once and is not saved by this plugin.",
		Elements:         []model.DialogElement{{DisplayName: "AgenticOS access token", Name: "access_token", Type: "text", SubType: "password", MinLength: 10, MaxLength: 4096, HelpText: "Obtain an access token through your instance's documented login API. Do not use a provider or bot token."}},
	}})
	if err != nil {
		_ = p.API.KVDelete("dialog-" + state)
		return response(setupError), nil
	}
	return response("Complete the private setup dialog."), nil
}

func (p *Plugin) ServeHTTP(_ *plugin.Context, w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	if r.URL.Path != "/setup" {
		http.NotFound(w, r)
		return
	}
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	user := r.Header.Get("Mattermost-User-ID")
	if !p.admin(user) {
		w.WriteHeader(http.StatusForbidden)
		return
	}
	var submission model.SubmitDialogRequest
	r.Body = http.MaxBytesReader(w, r.Body, 16384)
	dec := json.NewDecoder(r.Body)
	if dec.Decode(&submission) != nil || dec.Decode(new(json.RawMessage)) != io.EOF || submission.UserId != user || len(submission.State) != 64 {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	raw, e := p.API.KVGet("dialog-" + submission.State)
	var state dialogState
	if e != nil || len(raw) == 0 || json.Unmarshal(raw, &state) != nil || state.UserID != user || state.Expires <= time.Now().Unix() || state.Action != submission.CallbackId || state.ChannelID != submission.ChannelId || state.TeamID != submission.TeamId {
		w.WriteHeader(http.StatusForbidden)
		return
	}
	if state.Action == "connect" && state.Config != p.config() {
		writeDialog(w, "Configuration changed. Open a new setup dialog.")
		return
	}
	token, ok := submission.Submission["access_token"].(string)
	if !ok || len(token) < 10 || len(token) > 4096 || strings.ContainsAny(token, "\r\n\x00 \t") {
		writeDialog(w, "Enter a valid access token without whitespace.")
		return
	}
	consumed, err := p.API.KVCompareAndDelete("dialog-"+submission.State, raw)
	if err != nil || !consumed {
		w.WriteHeader(http.StatusConflict)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 50*time.Second)
	defer cancel()
	client := instanceClient{newHTTPClient(), state.Config, token}
	defer client.http.CloseIdleConnections()
	result := p.withLock(ctx, func() error {
		if state.Action == "disconnect" {
			return p.disconnect(ctx, client)
		}
		return p.connect(ctx, client, state)
	})
	// The dialog nonce is consumed even on failure; repeating a POST must never create another bot.
	message := "Setup complete. Use /agenticos status. Each person must link their own AgenticOS identity before chatting."
	if result != nil {
		message = result.Error() + " Open a new dialog to continue."
	}
	_ = p.API.SendEphemeralPost(user, &model.Post{ChannelId: state.ChannelID, Message: message})
	writeDialog(w, "")
}

func writeDialog(w http.ResponseWriter, message string) {
	_ = json.NewEncoder(w).Encode(model.SubmitDialogResponse{Error: message})
}
func (p *Plugin) withLock(ctx context.Context, fn func() error) error {
	lock, err := cluster.NewMutex(p.API, "setup-v1")
	if err != nil {
		return errors.New(setupError)
	}
	if lock.LockWithContext(ctx) != nil {
		return errors.New("Another setup operation is running. Check status before retrying.")
	}
	defer lock.Unlock()
	return fn()
}
func (p *Plugin) loadConnection() (*connection, error) {
	raw, e := p.API.KVGet(connectionKey)
	if e != nil {
		return nil, errors.New(setupError)
	}
	if len(raw) == 0 {
		return nil, nil
	}
	var c connection
	if json.Unmarshal(raw, &c) != nil || !c.Config.valid() {
		return nil, errors.New(setupError)
	}
	return &c, nil
}
func (p *Plugin) saveConnection(c connection) error {
	raw, err := json.Marshal(c)
	if err != nil || p.API.KVSet(connectionKey, raw) != nil {
		return errors.New(setupError)
	}
	return nil
}
func (p *Plugin) invite(bot, team, channel string) error {
	if !model.IsValidId(team) || !model.IsValidId(channel) {
		return errors.New(setupError)
	}
	ch, e := p.API.GetChannel(channel)
	if e != nil || ch == nil || ch.TeamId != team || ch.DeleteAt != 0 {
		return errors.New(setupError)
	}
	if _, e = p.API.GetTeamMember(team, bot); e != nil {
		if e.StatusCode != http.StatusNotFound {
			return errors.New(setupError)
		}
		if _, e = p.API.CreateTeamMember(team, bot); e != nil {
			return errors.New(setupError)
		}
	}
	if _, e = p.API.GetChannelMember(channel, bot); e != nil {
		if e.StatusCode != http.StatusNotFound {
			return errors.New(setupError)
		}
		if _, e = p.API.AddChannelMember(channel, bot); e != nil {
			return errors.New(setupError)
		}
	}
	return nil
}

func (p *Plugin) connect(ctx context.Context, client instanceClient, state dialogState) error {
	existing, err := p.loadConnection()
	if err != nil {
		return err
	}
	if existing != nil {
		return errors.New("A connection or unfinished setup already exists. Disconnect it before connecting again.")
	}
	if state.Config != p.config() {
		return errors.New("Configuration changed. Open a new setup dialog.")
	}
	site := p.API.GetConfig().ServiceSettings.SiteURL
	if site == nil || !validOrigin(*site) {
		return errors.New("Configure a reachable HTTPS Mattermost SiteURL first.")
	}
	c := connection{Config: state.Config, Phase: "setup_pending"}
	if err = p.saveConnection(c); err != nil {
		return err
	}
	bot, err := p.API.EnsureBotUser(&model.Bot{Username: "agenticos", DisplayName: "AgenticOS", Description: "Agent connected to this server's own AgenticOS instance"})
	if err != nil {
		return errors.New(setupError)
	}
	c.BotID = bot
	if err = p.saveConnection(c); err != nil {
		return err
	}
	if err = p.invite(bot, state.TeamID, state.ChannelID); err != nil {
		return err
	}
	pat, e := p.API.CreateUserAccessToken(&model.UserAccessToken{UserId: bot, Description: "AgenticOS plugin connection"})
	if e != nil || pat == nil {
		return errors.New(setupError)
	}
	c.TokenID = pat.Id
	// Persist the revocation handle before making any remote call.
	if err = p.saveConnection(c); err != nil {
		if p.API.RevokeUserAccessToken(pat.Id) != nil {
			return errors.New("Could not save the token revocation ID. Revoke 'AgenticOS plugin connection' in Mattermost immediately, then disconnect.")
		}
		return err
	}
	input := botRegistration{Platform: "mattermost", Name: "Mattermost plugin " + bot, Token: pat.Token, APIBaseURL: strings.TrimRight(*site, "/")}
	input.AccessPolicy.Mode = "jwt_linked"
	var remote resourceID
	err = client.request(ctx, http.MethodPost, "/channels/bots", input, &remote)
	if err == nil {
		c.RemoteBotID = remote.ID
		err = p.saveConnection(c)
	}
	if err == nil {
		var exposure resourceID
		err = client.request(ctx, http.MethodPost, "/agents/"+state.Config.AgentID+"/exposures", exposureRegistration{c.RemoteBotID}, &exposure)
	}
	if err != nil {
		// Keep the journal for explicit disconnect, including unknown remote acceptance.
		if p.API.RevokeUserAccessToken(c.TokenID) != nil {
			return errors.New("Setup was not confirmed and token revocation failed. Revoke the AgenticOS bot token in Mattermost immediately, then disconnect.")
		}
		return errors.New("Setup was not confirmed. The new bot token was revoked. Use /agenticos disconnect to clean up before retrying; inspect AgenticOS Channels if registration was interrupted.")
	}
	c.Phase = "connected"
	if p.saveConnection(c) != nil {
		if p.API.RevokeUserAccessToken(c.TokenID) != nil {
			return errors.New("Could not record setup. Revoke the bot token in Mattermost immediately, then disconnect.")
		}
		return errors.New("Could not record setup. Bot token revoked; disconnect before retrying.")
	}
	return nil
}

func (p *Plugin) disconnect(ctx context.Context, client instanceClient) error {
	c, err := p.loadConnection()
	if err != nil {
		return err
	}
	if c == nil {
		return errors.New("No connection to disconnect.")
	}
	if c.Config != client.config {
		return errors.New("Connection changed. Open a new disconnect dialog.")
	}
	previousPhase := c.Phase
	c.Phase = "disconnect_pending"
	if err = p.saveConnection(*c); err != nil {
		return err
	}
	// Local revocation comes first, including when the remote instance is unavailable.
	if c.TokenID != "" {
		if revokeErr := p.API.RevokeUserAccessToken(c.TokenID); revokeErr != nil && revokeErr.StatusCode != http.StatusNotFound {
			return errors.New("Could not revoke the bot token. Revoke it in Mattermost before continuing.")
		}
	}
	if c.RemoteBotID != "" {
		if err = client.request(ctx, http.MethodDelete, "/channels/bots/"+c.RemoteBotID, nil, nil); err != nil {
			return errors.New("Bot token revoked, but AgenticOS cleanup was not confirmed. Check access and open another disconnect dialog.")
		}
	}
	if p.API.KVDelete(connectionKey) != nil {
		return errors.New(setupError)
	}
	if previousPhase != "connected" && c.RemoteBotID == "" {
		return errors.New("Local token revoked and setup reset. Check AgenticOS Channels for an orphaned 'Mattermost plugin' registration before reconnecting.")
	}
	return nil
}
