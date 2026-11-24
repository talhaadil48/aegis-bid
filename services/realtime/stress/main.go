// Distinct authenticated bidders: hold live sockets, then offer bids in one close window.
package main

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptrace"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

type Bidder struct {
	ID      string `json:"id"`
	Token   string `json:"token"`
	Request string `json:"request_id"`
	Amount  int64  `json:"amount_cents"`
	Index   int    `json:"index"`
}
type Config struct {
	Run     string   `json:"run_id"`
	Shard   int      `json:"shard"`
	URL     string   `json:"api_url"`
	WS      string   `json:"ws_url"`
	Auction string   `json:"auction_id"`
	Total   int      `json:"total"`
	Users   []Bidder `json:"users"`
	Live    bool     `json:"live_sockets"`
}
type Plan struct {
	Start  time.Time `json:"start"`
	Close  time.Time `json:"close"`
	Spread float64   `json:"spread_seconds"`
}
type Row struct {
	ID, Request                      string
	Amount                           int64
	Scheduled, Started, Written, End time.Time
	Status                           int
	State, Error                     string
}

func writeJSON(path string, value any) {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		log.Fatal(err)
	}
	tmp := path + ".tmp"
	if err = os.WriteFile(tmp, data, 0644); err != nil {
		log.Fatal(err)
	}
	if err = os.Rename(tmp, path); err != nil {
		log.Fatal(err)
	}
}
func readJSON(path string, value any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, value)
}
func main() {
	configFile := flag.String("config", "", "Private shard configuration")
	control := flag.String("control", "/control", "Read-only coordination directory")
	output := flag.String("output", "/results", "Safe output directory")
	ramp := flag.Int("ramp", 150, "Concurrent socket handshakes per shard")
	flag.Parse()
	var c Config
	if err := readJSON(*configFile, &c); err != nil {
		log.Fatal("Cannot read shard configuration")
	}
	if c.Total < 1 || len(c.Users) < 1 || *ramp < 1 {
		log.Fatal("Positive population and ramp required")
	}
	var active, wsErrors, messages, started, inflight, replied atomic.Int64
	var socketsMu sync.Mutex
	sockets := make([]*websocket.Conn, 0, len(c.Users))
	rows := make([]Row, len(c.Users))
	var ready, bids, readers sync.WaitGroup
	ready.Add(len(c.Users))
	bids.Add(len(c.Users))
	gate := make(chan struct{})
	handshakes := make(chan struct{}, *ramp)
	var plan Plan
	transport := &http.Transport{MaxIdleConns: 1024, MaxIdleConnsPerHost: 1024, MaxConnsPerHost: 1024, IdleConnTimeout: 60 * time.Second, DialContext: (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext}
	client := &http.Client{Transport: transport, Timeout: 90 * time.Second}
	beginRamp := time.Now().UTC()
	for i, profile := range c.Users {
		go func(i int, p Bidder) {
			defer bids.Done()
			if c.Live {
				handshakes <- struct{}{}
				dialer := websocket.Dialer{HandshakeTimeout: 45 * time.Second, ReadBufferSize: 1024, WriteBufferSize: 1024}
				socket, _, err := dialer.Dial(c.WS, http.Header{"Cookie": []string{"aegis_session=" + p.Token}})
				if err == nil {
					_ = socket.SetReadDeadline(time.Now().Add(45 * time.Second))
					_, body, readErr := socket.ReadMessage()
					var snapshot struct {
						Type string `json:"type"`
					}
					if readErr != nil || json.Unmarshal(body, &snapshot) != nil || snapshot.Type != "auction.snapshot" {
						err = fmt.Errorf("initial snapshot unavailable")
						_ = socket.Close()
					}
				}
				if err != nil {
					wsErrors.Add(1)
				} else {
					active.Add(1)
					messages.Add(1)
					socketsMu.Lock()
					sockets = append(sockets, socket)
					socketsMu.Unlock()
					readers.Add(1)
					go func() {
						defer readers.Done()
						defer active.Add(-1)
						defer socket.Close()
						for {
							_ = socket.SetReadDeadline(time.Now().Add(90 * time.Second))
							if _, _, err := socket.ReadMessage(); err != nil {
								return
							}
							messages.Add(1)
						}
					}()
				}
				<-handshakes
			}
			ready.Done()
			<-gate
			scheduled := plan.Start.Add(time.Duration(float64(p.Index) / float64(c.Total) * plan.Spread * float64(time.Second)))
			time.Sleep(time.Until(scheduled))
			payload, _ := json.Marshal(map[string]any{"request_id": p.Request, "amount_cents": p.Amount})
			request, _ := http.NewRequest(http.MethodPost, c.URL+"/v1/auctions/"+c.Auction+"/bids", bytes.NewReader(payload))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Cookie", "aegis_session="+p.Token)
			var written atomic.Int64
			trace := &httptrace.ClientTrace{WroteRequest: func(info httptrace.WroteRequestInfo) {
				if info.Err == nil {
					written.Store(time.Now().UnixNano())
				}
			}}
			request = request.WithContext(httptrace.WithClientTrace(request.Context(), trace))
			row := Row{ID: p.ID, Request: p.Request, Amount: p.Amount, Scheduled: scheduled, Started: time.Now().UTC()}
			started.Add(1)
			inflight.Add(1)
			response, requestErr := client.Do(request)
			row.End = time.Now().UTC()
			inflight.Add(-1)
			replied.Add(1)
			if ns := written.Load(); ns != 0 {
				row.Written = time.Unix(0, ns).UTC()
			}
			if requestErr != nil {
				row.Error = "transport failure"
			} else {
				row.Status = response.StatusCode
				var outcome struct {
					State   string `json:"state"`
					Request string `json:"request_id"`
				}
				decodeErr := json.NewDecoder(io.LimitReader(response.Body, 65536)).Decode(&outcome)
				_ = response.Body.Close()
				row.State = outcome.State
				if decodeErr != nil || outcome.Request != p.Request || !(row.Status == 200 || row.Status == 202) {
					row.Error = "non-admission response"
				}
			}
			rows[i] = row
		}(i, profile)
	}
	ready.Wait()
	// Prepare HTTP transport before the measured auction window; no bids or
	// business state are created by these public health requests.
	var warm sync.WaitGroup
	var warmErrors atomic.Int64
	for i := 0; i < 256; i++ {
		warm.Add(1)
		go func() {
			defer warm.Done()
			response, err := client.Get(c.URL + "/health")
			if err != nil {
				warmErrors.Add(1)
				return
			}
			_, _ = io.Copy(io.Discard, response.Body)
			_ = response.Body.Close()
			if response.StatusCode != 200 {
				warmErrors.Add(1)
			}
		}()
	}
	warm.Wait()
	writeJSON(filepath.Join(*output, fmt.Sprintf("ready-%d.json", c.Shard)), map[string]any{"run_id": c.Run, "shard": c.Shard, "requested": len(c.Users), "active": active.Load(), "ws_errors": wsErrors.Load(), "http_warmup_errors": warmErrors.Load(), "ramp_started": beginRamp, "ready_at": time.Now().UTC()})
	for readJSON(filepath.Join(*control, "start.json"), &plan) != nil {
		time.Sleep(100 * time.Millisecond)
	}
	close(gate)
	monitorDone := make(chan struct{})
	go func() {
		f, err := os.Create(filepath.Join(*output, fmt.Sprintf("live-%d.jsonl", c.Shard)))
		if err != nil {
			return
		}
		defer f.Close()
		ticker := time.NewTicker(time.Second)
		defer ticker.Stop()
		for {
			select {
			case now := <-ticker.C:
				_ = json.NewEncoder(f).Encode(map[string]any{"at": now.UTC(), "active": active.Load(), "started": started.Load(), "inflight": inflight.Load(), "responses": replied.Load()})
			case <-monitorDone:
				return
			}
		}
	}()
	time.Sleep(time.Until(plan.Start))
	activeStart := active.Load()
	heldStart := time.Now().UTC()
	bids.Wait()
	f, err := os.Create(filepath.Join(*output, fmt.Sprintf("requests-%d.csv", c.Shard)))
	if err != nil {
		log.Fatal(err)
	}
	writer := csv.NewWriter(f)
	_ = writer.Write([]string{"bidder_id", "request_id", "amount_cents", "scheduled_at", "started_at", "written_at", "response_at", "http_status", "initial_state", "error", "ingress_s"})
	responses := map[string]int{}
	statuses := map[int]int{}
	errors := 0
	writtenInWindow := 0
	startsInWindow := 0
	for _, row := range rows {
		statuses[row.Status]++
		responses[row.State]++
		if row.Error != "" {
			errors++
		}
		if !row.Started.Before(plan.Start) && row.Started.Before(plan.Close) {
			startsInWindow++
		}
		if !row.Written.Before(plan.Start) && row.Written.Before(plan.Close) {
			writtenInWindow++
		}
		_ = writer.Write([]string{row.ID, row.Request, strconv.FormatInt(row.Amount, 10), row.Scheduled.Format(time.RFC3339Nano), row.Started.Format(time.RFC3339Nano), row.Written.Format(time.RFC3339Nano), row.End.Format(time.RFC3339Nano), strconv.Itoa(row.Status), row.State, row.Error, strconv.FormatFloat(row.End.Sub(row.Started).Seconds(), 'f', 6, 64)})
	}
	writer.Flush()
	if writer.Error() != nil {
		log.Fatal(writer.Error())
	}
	_ = f.Close()
	summary := map[string]any{"run_id": c.Run, "shard": c.Shard, "requested": len(c.Users), "active_at_window_start": activeStart, "held_started_at": heldStart, "handshake_errors": wsErrors.Load(), "http_statuses": statuses, "initial_states": responses, "request_errors": errors, "starts_in_window": startsInWindow, "writes_in_window": writtenInWindow, "http_finished_at": time.Now().UTC()}
	writeJSON(filepath.Join(*output, fmt.Sprintf("ingress-%d.json", c.Shard)), summary)
	expires := time.Now().Add(180 * time.Second)
	for time.Now().Before(expires) {
		if _, err := os.Stat(filepath.Join(*control, "stop")); err == nil {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	summary["active_at_end"] = active.Load()
	summary["held_ended_at"] = time.Now().UTC()
	summary["snapshots_received"] = messages.Load()
	writeJSON(filepath.Join(*output, fmt.Sprintf("shard-%d.json", c.Shard)), summary)
	close(monitorDone)
	for _, socket := range sockets {
		_ = socket.Close()
	}
	readers.Wait()
	transport.CloseIdleConnections()
	log.Printf("shard %d: %d bidders; %d request errors", c.Shard, len(c.Users), errors)
}
