// Command assistant-launcher owns the exported Assistant pack lifecycle.
//
// It starts the bundled local server, verifies that the instance on the fixed
// loopback port is the one it started, launches Ren'Py, and finally shuts down
// only that server. Ren'Py itself is deliberately client-only.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"time"
)

const (
	serverHost        = "127.0.0.1"
	serverPort        = "8765"
	serverURL         = "http://127.0.0.1:8765"
	startupTimeout    = 15 * time.Second
	requestTimeout    = 1 * time.Second
	shutdownTimeout   = 3 * time.Second
	pollInterval      = 100 * time.Millisecond
	clientHeader      = "X-Amnesia-Client"
	clientHeaderValue = "local"
)

type healthResponse struct {
	Status     string `json:"status"`
	InstanceID string `json:"instance_id"`
}

func main() {
	if err := run(); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "Assistant launcher: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	root, err := packRoot()
	if err != nil {
		return err
	}
	serverPath, err := serverExecutable(root)
	if err != nil {
		return err
	}
	renpyPath, err := renpyExecutable(root)
	if err != nil {
		return err
	}
	instanceID, err := newInstanceID()
	if err != nil {
		return fmt.Errorf("create server instance id: %w", err)
	}

	server := exec.Command(
		serverPath,
		"--host", serverHost,
		"--port", serverPort,
		"--instance-id", instanceID,
	)
	server.Dir = root
	server.Stdout = os.Stdout
	server.Stderr = os.Stderr
	if err := server.Start(); err != nil {
		return fmt.Errorf("start bundled server %q: %w", serverPath, err)
	}
	serverDone := make(chan error, 1)
	go func() { serverDone <- server.Wait() }()

	if err := waitForHealth(serverDone, instanceID); err != nil {
		stopServer(server, serverDone, instanceID)
		return err
	}

	renpy := exec.Command(renpyPath)
	renpy.Dir = root
	renpy.Stdout = os.Stdout
	renpy.Stderr = os.Stderr
	renpy.Stdin = os.Stdin
	if err := renpy.Run(); err != nil {
		stopServer(server, serverDone, instanceID)
		return fmt.Errorf("Ren'Py exited with error: %w", err)
	}

	stopServer(server, serverDone, instanceID)
	return nil
}

func packRoot() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("locate launcher: %w", err)
	}
	root, err := filepath.Abs(filepath.Dir(executable))
	if err != nil {
		return "", fmt.Errorf("resolve pack root: %w", err)
	}
	return root, nil
}

func serverExecutable(root string) (string, error) {
	name := "amnesia-agent-local-server"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	return requiredFile(filepath.Join(root, "server", name), "bundled server")
}

func renpyExecutable(root string) (string, error) {
	var candidate string
	switch runtime.GOOS {
	case "windows":
		candidate = filepath.Join(root, "Assistant.exe")
	case "darwin":
		candidate = filepath.Join(root, "Assistant.app", "Contents", "MacOS", "Assistant")
	default:
		candidate = filepath.Join(root, "Assistant")
	}
	return requiredFile(candidate, "Ren'Py executable")
}

func requiredFile(path, label string) (string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("%s not found at %q: %w", label, path, err)
	}
	if info.IsDir() {
		return "", fmt.Errorf("%s path is a directory: %q", label, path)
	}
	return path, nil
}

func waitForHealth(serverDone chan error, expectedInstance string) error {
	client := &http.Client{Timeout: requestTimeout}
	deadline := time.NewTimer(startupTimeout)
	defer deadline.Stop()
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case err := <-serverDone:
			// Leave the result available for stopServer, which owns the final
			// cleanup path after this startup failure.
			serverDone <- err
			if err == nil {
				return errors.New("bundled server exited before becoming ready")
			}
			return fmt.Errorf("bundled server exited before becoming ready: %w", err)
		case <-deadline.C:
			return fmt.Errorf("bundled server did not become ready on %s", serverURL)
		case <-ticker.C:
			health, err := getHealth(client)
			if err != nil {
				continue
			}
			if health.Status != "ok" || health.InstanceID != expectedInstance {
				return fmt.Errorf("port %s is occupied by another local server", serverPort)
			}
			return nil
		}
	}
}

func getHealth(client *http.Client) (healthResponse, error) {
	request, err := http.NewRequest(http.MethodGet, serverURL+"/v1/health", nil)
	if err != nil {
		return healthResponse{}, err
	}
	response, err := client.Do(request)
	if err != nil {
		return healthResponse{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, response.Body)
		return healthResponse{}, fmt.Errorf("health returned HTTP %d", response.StatusCode)
	}
	var health healthResponse
	if err := json.NewDecoder(response.Body).Decode(&health); err != nil {
		return healthResponse{}, err
	}
	return health, nil
}

func stopServer(server *exec.Cmd, serverDone <-chan error, expectedInstance string) {
	if server.Process == nil {
		return
	}
	if health, err := getHealth(&http.Client{Timeout: requestTimeout}); err == nil && health.InstanceID == expectedInstance {
		ctx, cancel := context.WithTimeout(context.Background(), requestTimeout)
		defer cancel()
		request, requestErr := http.NewRequestWithContext(
			ctx,
			http.MethodPost,
			serverURL+"/v1/shutdown",
			nil,
		)
		if requestErr == nil {
			request.Header.Set(clientHeader, clientHeaderValue)
			if response, doErr := (&http.Client{Timeout: requestTimeout}).Do(request); doErr == nil {
				_ = response.Body.Close()
			}
		}
	}

	timer := time.NewTimer(shutdownTimeout)
	defer timer.Stop()
	select {
	case <-serverDone:
		return
	case <-timer.C:
		_ = server.Process.Kill()
		<-serverDone
	}
}

func newInstanceID() (string, error) {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes), nil
}
EOF