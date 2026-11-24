package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func TestAdmissionBatchPreservesCookiesAndRejectsSpoofedBody(t *testing.T) {
	key := "service-key-with-at-least-thirty-two-characters"
	t.Setenv("ADMISSION_SERVICE_KEY", key)
	var calls, items atomic.Int64
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Admission-Key") != key {
			t.Error("Missing service authentication")
		}
		var body struct {
			Auction  string       `json:"auction_id"`
			Requests []bidPayload `json:"requests"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		calls.Add(1)
		items.Add(int64(len(body.Requests)))
		results := make([]admissionResult, len(body.Requests))
		for i, item := range body.Requests {
			if !strings.HasPrefix(item.Session, "session-") {
				t.Error("Cookie was not forwarded per user")
			}
			results[i] = admissionResult{Status: 202, Request: item.Request, State: "QUEUED"}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"results": results})
	}))
	defer upstream.Close()
	proxy := newAdmissionProxy(upstream.URL, "http://demo")
	var group sync.WaitGroup
	for i := 0; i < 60; i++ {
		group.Add(1)
		go func(i int) {
			defer group.Done()
			rid := fmt.Sprintf("00000000-0000-0000-0000-%012d", i)
			r := httptest.NewRequest("POST", "http://demo/v1/auctions/00000000-0000-0000-0000-000000000001/bids", strings.NewReader(fmt.Sprintf(`{"request_id":"%s","amount_cents":100}`, rid)))
			r.AddCookie(&http.Cookie{Name: "aegis_session", Value: fmt.Sprintf("session-%d", i)})
			w := httptest.NewRecorder()
			proxy.serve(w, r)
			if w.Code != 202 {
				t.Errorf("Unexpected result %d", w.Code)
			}
		}(i)
	}
	group.Wait()
	if items.Load() != 60 || calls.Load() >= 60 {
		t.Fatal("Individual clients were not coalesced into bounded batches")
	}
	for _, body := range []string{`{"request_id":"00000000-0000-0000-0000-000000000002","amount_cents":100,"session_cookie":"spoofed"}`, `{"request_id":"00000000-0000-0000-0000-000000000002","amount_cents":100.5}`} {
		r := httptest.NewRequest("POST", "http://demo/v1/auctions/00000000-0000-0000-0000-000000000001/bids", strings.NewReader(body))
		r.AddCookie(&http.Cookie{Name: "aegis_session", Value: "session-user"})
		w := httptest.NewRecorder()
		proxy.serve(w, r)
		if w.Code != 422 {
			t.Fatal("Untrusted identity or non-integer cents accepted")
		}
	}
}
