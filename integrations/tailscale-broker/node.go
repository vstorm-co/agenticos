package main

import (
	"context"
	"errors"

	"tailscale.com/client/local"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/tsnet"
)

type tailnetNode interface {
	Status(context.Context) (*ipnstate.Status, error)
	StartLoginInteractive(context.Context) error
	Logout(context.Context) error
	Close() error
}

type nodeFactory func(hostname, dir string, store *snapshotStore) (tailnetNode, error)

type tsnetNode struct {
	server *tsnet.Server
	client *local.Client
}

func productionNodeFactory(hostname, dir string, store *snapshotStore) (tailnetNode, error) {
	server := newTSNetServer(hostname, dir, store)
	client, err := server.LocalClient()
	if err != nil {
		_ = server.Close()
		return nil, errors.New("tsnet initialization failed")
	}
	return &tsnetNode{server: server, client: client}, nil
}

func newTSNetServer(hostname, dir string, store *snapshotStore) *tsnet.Server {
	silent := func(string, ...any) {}
	return &tsnet.Server{
		Dir:       dir,
		Store:     store,
		Hostname:  hostname,
		Ephemeral: false,
		Tun:       nil,
		Logf:      silent,
		UserLogf:  silent,
	}
}

func (n *tsnetNode) Status(ctx context.Context) (*ipnstate.Status, error) {
	status, err := n.client.Status(ctx)
	if err != nil {
		return nil, errors.New("tsnet status unavailable")
	}
	return status, nil
}

func (n *tsnetNode) StartLoginInteractive(ctx context.Context) error {
	if err := n.client.StartLoginInteractive(ctx); err != nil {
		return errors.New("interactive login unavailable")
	}
	return nil
}

func (n *tsnetNode) Logout(ctx context.Context) error {
	if err := n.client.Logout(ctx); err != nil {
		return errors.New("tsnet logout failed")
	}
	return nil
}

func (n *tsnetNode) Close() error {
	if err := n.server.Close(); err != nil {
		return errors.New("tsnet shutdown failed")
	}
	return nil
}
