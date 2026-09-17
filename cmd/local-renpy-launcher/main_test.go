package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNewInstanceIDIsUniqueAndHexEncoded(t *testing.T) {
	first, err := newInstanceID()
	if err != nil {
		t.Fatal(err)
	}
	second, err := newInstanceID()
	if err != nil {
		t.Fatal(err)
	}
	if first == second || len(first) != 32 || len(second) != 32 {
		t.Fatalf("unexpected instance ids: %q %q", first, second)
	}
}

func TestPairingLinkArgument(t *testing.T) {
	if got := pairingLinkArgument([]string{"--debug", "amnesia://pair?v=1"}); got != "amnesia://pair?v=1" {
		t.Fatalf("pairingLinkArgument() = %q", got)
	}
	if got := pairingLinkArgument([]string{"--debug"}); got != "" {
		t.Fatalf("pairingLinkArgument() accepted %q", got)
	}
}

func TestRequiredFile(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "child")
	if err := os.WriteFile(path, []byte("x"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := requiredFile(path, "child")
	if err != nil || got != path {
		t.Fatalf("requiredFile(%q) = %q, %v", path, got, err)
	}
	if _, err := requiredFile(filepath.Join(directory, "missing"), "child"); err == nil {
		t.Fatal("requiredFile accepted a missing path")
	}
}
