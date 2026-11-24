package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type bidPayload struct {
	Request string `json:"request_id"`
	Amount  int64  `json:"amount_cents"`
	Session string `json:"session_cookie,omitempty"`
}
type admissionResult struct {
	Status  int    `json:"http_status"`
	Request string `json:"request_id,omitempty"`
	State   string `json:"state,omitempty"`
	Message string `json:"message,omitempty"`
	Detail  string `json:"detail,omitempty"`
}
type admissionJob struct {
	body   bidPayload
	result chan admissionResult
}
type admissionProxy struct {
	mu                    sync.Mutex
	groups                map[string]chan *admissionJob
	upstream, key, origin string
	client                *http.Client
}

func newAdmissionProxy(upstream, origin string) *admissionProxy {
	return &admissionProxy{groups: make(map[string]chan *admissionJob), upstream: upstream, key: os.Getenv("ADMISSION_SERVICE_KEY"), origin: origin, client: &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{MaxIdleConns: 64, MaxIdleConnsPerHost: 64, MaxConnsPerHost: 64, IdleConnTimeout: 60 * time.Second}}}
}
func (p *admissionProxy) serve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Content-Type", "application/json")
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", 405)
		return
	}
	parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(parts) != 4 || parts[0] != "v1" || parts[1] != "auctions" || parts[3] != "bids" || !uuidPattern.MatchString(parts[2]) {
		http.NotFound(w, r)
		return
	}
	if len(p.key) < 32 {
		http.Error(w, "Admission service unavailable", 503)
		return
	}
	if origin := r.Header.Get("Origin"); origin != "" && origin != p.origin {
		http.Error(w, "Origin denied", 403)
		return
	}
	cookie, err := r.Cookie("aegis_session")
	if err != nil || len(cookie.Value) > 4096 {
		http.Error(w, "Sign in required", 401)
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1024)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var incoming struct {
		Request string `json:"request_id"`
		Amount  int64  `json:"amount_cents"`
	}
	if err := decoder.Decode(&incoming); err != nil || !uuidPattern.MatchString(incoming.Request) || incoming.Amount <= 0 || incoming.Amount > 1000000000000 {
		http.Error(w, "Invalid bid", 422)
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		http.Error(w, "Invalid trailing payload", 422)
		return
	}
	job := &admissionJob{body: bidPayload{Request: incoming.Request, Amount: incoming.Amount, Session: cookie.Value}, result: make(chan admissionResult, 1)}
	auction := strings.ToLower(parts[2])
	p.mu.Lock()
	group, exists := p.groups[auction]
	if !exists {
		if len(p.groups) >= 100 {
			p.mu.Unlock()
			http.Error(w, "Auction intake capacity reached", 429)
			return
		}
		group = make(chan *admissionJob, 2048)
		p.groups[auction] = group
		go p.drain(auction, group)
	}
	select {
	case group <- job:
		p.mu.Unlock()
	default:
		p.mu.Unlock()
		w.Header().Set("Retry-After", "1")
		http.Error(w, "Intake capacity reached; retry UUID", 429)
		return
	}
	select {
	case result := <-job.result:
		if result.Status == 0 {
			result.Status = 503
		}
		if result.Status == 429 {
			w.Header().Set("Retry-After", "1")
		}
		w.WriteHeader(result.Status)
		_ = json.NewEncoder(w).Encode(result)
	case <-r.Context().Done():
		return
	}
}
func (p *admissionProxy) drain(auction string, group chan *admissionJob) {
	idle := time.NewTimer(30 * time.Second)
	slots := make(chan struct{}, 4)
	defer idle.Stop()
	for {
		var first *admissionJob
		select {
		case first = <-group:
		case <-idle.C:
			p.mu.Lock()
			if len(group) == 0 && len(slots) == 0 {
				delete(p.groups, auction)
				p.mu.Unlock()
				return
			}
			p.mu.Unlock()
			idle.Reset(30 * time.Second)
			continue
		}
		if !idle.Stop() {
			select {
			case <-idle.C:
			default:
			}
		}
		batch := []*admissionJob{first}
		timer := time.NewTimer(50 * time.Millisecond)
	collect:
		for len(batch) < 512 {
			select {
			case job := <-group:
				batch = append(batch, job)
			case <-timer.C:
				break collect
			}
		}
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		payloads := make([]bidPayload, len(batch))
		for i, job := range batch {
			payloads[i] = job.body
		}
		data, _ := json.Marshal(struct {
			Auction  string       `json:"auction_id"`
			Requests []bidPayload `json:"requests"`
		}{auction, payloads})
		slots <- struct{}{}
		go func(batch []*admissionJob, data []byte) {
			defer func() { <-slots }()
			request, _ := http.NewRequest(http.MethodPost, p.upstream+"/internal/v1/admissions", bytes.NewReader(data))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("X-Admission-Key", p.key)
			response, err := p.client.Do(request)
			var result struct {
				Results []admissionResult `json:"results"`
			}
			if err == nil {
				if response.StatusCode != 200 {
					err = io.ErrUnexpectedEOF
				} else {
					err = json.NewDecoder(io.LimitReader(response.Body, 1024*1024)).Decode(&result)
				}
				_ = response.Body.Close()
			}
			if err != nil || len(result.Results) != len(batch) {
				for _, job := range batch {
					job.result <- admissionResult{Status: 503, Detail: "Durability acknowledgment unavailable; retry the same UUID"}
				}
			} else {
				for i, job := range batch {
					job.result <- result.Results[i]
				}
			}
		}(batch, data)
		idle.Reset(30 * time.Second)
	}
}
