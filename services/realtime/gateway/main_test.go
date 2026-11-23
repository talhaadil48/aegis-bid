package main

import (
	"github.com/gorilla/websocket"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestOriginAndIDs(t *testing.T) {
	s := newServer()
	r := httptest.NewRequest("GET", "http://gateway/live", nil)
	r.Header.Set("Origin", "https://evil.example")
	if s.originOK(r) {
		t.Fatal("cross origin accepted")
	}
	r.Header.Set("Origin", "http://gateway")
	if !s.originOK(r) {
		t.Fatal("same origin rejected")
	}
	if uuidPattern.MatchString("../../admin") {
		t.Fatal("unsafe path")
	}
}
func TestLiveSharedSnapshotAndQuota(t *testing.T) {
	calls := 0
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v1/auth/me" {
			w.Write([]byte(`{"id":"user"}`))
			return
		}
		calls++
		w.Write([]byte(`{"version":1,"status":"OPEN"}`))
	}))
	defer upstream.Close()
	s := newServer()
	s.upstream = upstream.URL
	s.maxUser = 1
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/live/auctions/", s.live)
	server := httptest.NewServer(mux)
	defer server.Close()
	address := "ws" + strings.TrimPrefix(server.URL, "http") + "/v1/live/auctions/00000000-0000-0000-0000-000000000001"
	header := http.Header{"Cookie": []string{"aegis_session=test"}}
	socket, _, err := websocket.DefaultDialer.Dial(address, header)
	if err != nil {
		t.Fatal(err)
	}
	defer socket.Close()
	socket.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, data, err := socket.ReadMessage()
	if err != nil || !strings.Contains(string(data), "auction.snapshot") {
		t.Fatal("missing authoritative snapshot", err)
	}
	_, response, err := websocket.DefaultDialer.Dial(address, header)
	if err == nil || response.StatusCode != 429 {
		t.Fatal("quota not enforced")
	}
	response.Body.Close()
	if calls != 1 {
		t.Fatal("initial snapshot was fetched per connection")
	}
}
