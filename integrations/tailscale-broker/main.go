package main

import (
	"io"
	"log"
	"os"
	"strings"

	"tailscale.com/envknob"
)

func main() {
	// Capture the OS-selected temporary directory before stripping the
	// environment. No environment variable is forwarded into tsnet.
	tempRoot := os.TempDir()
	applyEnvironmentPolicy(os.Environ())
	log.SetOutput(io.Discard)

	config := defaultBrokerConfig()
	config.terminate = func() { os.Exit(1) }
	if err := runBroker(os.Stdin, os.Stdout, tempRoot, productionNodeFactory, config); err != nil {
		os.Exit(1)
	}
}

// safeEnvironment returns the only environment setting the broker intentionally
// supplies to Tailscale. In particular, nothing from the parent environment is
// inherited.
func safeEnvironment(_ []string) []string {
	return []string{"TS_NO_LOGS_NO_SUPPORT=true"}
}

func applyEnvironmentPolicy(inherited []string) {
	// Tailscale's envknob package can cache TS_* settings during dependency
	// initialization, before main runs. Clear those cached values as well as the
	// process environment. Set the one explicit policy knob only after clearing.
	for _, entry := range inherited {
		name, _, ok := strings.Cut(entry, "=")
		if !ok {
			continue
		}
		upper := strings.ToUpper(name)
		if strings.HasPrefix(upper, "TS_") || strings.HasPrefix(upper, "TSNET_") {
			envknob.Setenv(name, "")
		}
	}
	os.Clearenv()
	for _, entry := range safeEnvironment(inherited) {
		name, value, _ := strings.Cut(entry, "=")
		envknob.Setenv(name, value)
	}
}
