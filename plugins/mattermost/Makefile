SHELL := /bin/sh
export GOTOOLCHAIN := go1.26.11
PLUGIN_ID := co.vstorm.agenticos
VERSION := $(shell python3 -c 'import json; print(json.load(open("plugin.json"))["version"])')
BUNDLE := dist/$(PLUGIN_ID)-$(VERSION).tar.gz

.PHONY: check test audit bundle clean
check:
	@test -z "$$(gofmt -l server)" || (gofmt -l server; exit 1)
	go vet -mod=readonly ./server
	go test -mod=readonly -race -count=1 ./server
	$(MAKE) audit

test:
	go test -mod=readonly ./server

audit:
	go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./server

bundle:
	mkdir -p dist/$(PLUGIN_ID)/server/dist dist/$(PLUGIN_ID)/assets
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -mod=readonly -trimpath -ldflags='-s -w' -o dist/$(PLUGIN_ID)/server/dist/plugin-linux-amd64 ./server
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -mod=readonly -trimpath -ldflags='-s -w' -o dist/$(PLUGIN_ID)/server/dist/plugin-linux-arm64 ./server
	cp plugin.json README.md ../../LICENSE dist/$(PLUGIN_ID)/
	cp ../../docs/assets/logo.svg dist/$(PLUGIN_ID)/assets/logo.svg
	tar -C dist -czf $(BUNDLE) $(PLUGIN_ID)
	python3 scripts/check_bundle.py $(BUNDLE)

clean:
	rm -rf dist
