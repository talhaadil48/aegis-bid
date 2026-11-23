package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"github.com/gorilla/websocket"
	"log"
	"net/http"
	"os"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	address := flag.String("url", "", "Full auction ws:// or wss:// URL")
	count := flag.Int("connections", 100, "Number of sockets")
	parallel := flag.Int("ramp", 100, "Concurrent handshakes")
	hold := flag.Duration("hold", 60*time.Second, "Hold duration after ramp")
	output := flag.String("output", "/results/shard.json", "JSON result")
	flag.Parse()
	cookie := os.Getenv("WS_COOKIE")
	if *address == "" || cookie == "" || *count < 1 || *parallel < 1 {
		log.Fatal("url, WS_COOKIE, positive connections and ramp required")
	}
	var established, active, peak, errors, messages atomic.Int64
	var mu sync.Mutex
	latencies := []float64{}
	sockets := []*websocket.Conn{}
	jobs := make(chan int)
	var ramps, readers sync.WaitGroup
	start := time.Now()
	for worker := 0; worker < *parallel; worker++ {
		ramps.Add(1)
		go func() {
			defer ramps.Done()
			for range jobs {
				begin := time.Now()
				dialer := websocket.Dialer{HandshakeTimeout: 15 * time.Second, ReadBufferSize: 1024, WriteBufferSize: 1024}
				c, _, err := dialer.Dial(*address, http.Header{"Cookie": []string{"aegis_session=" + cookie}})
				if err != nil {
					errors.Add(1)
					continue
				}
				_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
				_, data, err := c.ReadMessage()
				var snapshot map[string]any
				if err != nil || json.Unmarshal(data, &snapshot) != nil || snapshot["type"] != "auction.snapshot" {
					errors.Add(1)
					c.Close()
					continue
				}
				established.Add(1)
				n := active.Add(1)
				for {
					old := peak.Load()
					if n <= old || peak.CompareAndSwap(old, n) {
						break
					}
				}
				mu.Lock()
				sockets = append(sockets, c)
				latencies = append(latencies, time.Since(begin).Seconds())
				mu.Unlock()
				messages.Add(1)
				readers.Add(1)
				go func() {
					defer readers.Done()
					defer active.Add(-1)
					defer c.Close()
					for {
						_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
						if _, _, err := c.ReadMessage(); err != nil {
							return
						}
						messages.Add(1)
					}
				}()
			}
		}()
	}
	for index := 0; index < *count; index++ {
		jobs <- index
	}
	close(jobs)
	ramps.Wait()
	rampDone := time.Now()
	heldStart := active.Load()
	time.Sleep(*hold)
	heldEnd := active.Load()
	mu.Lock()
	for _, c := range sockets {
		c.Close()
	}
	mu.Unlock()
	readers.Wait()
	sort.Float64s(latencies)
	quantile := func(q float64) any {
		if len(latencies) == 0 {
			return nil
		}
		return latencies[int(float64(len(latencies)-1)*q)]
	}
	report := map[string]any{"schema_version": 1, "run_id": os.Getenv("RUN_ID"), "shard": os.Getenv("SHARD_ID"), "target": *address, "requested": *count, "established": established.Load(), "peak": peak.Load(), "held_start": heldStart, "held_end": heldEnd, "handshake_errors": errors.Load(), "messages_received": messages.Load(), "ramp_started_at": start.UTC(), "hold_started_at": rampDone.UTC(), "hold_ended_at": time.Now().UTC(), "hold_seconds": hold.Seconds(), "ramp_seconds": rampDone.Sub(start).Seconds(), "p50_handshake_s": quantile(.5), "p95_handshake_s": quantile(.95), "p99_handshake_s": quantile(.99), "scope": "WebSocket capacity with real authenticated snapshots; not bid throughput or unique bidder count"}
	data, _ := json.MarshalIndent(report, "", "  ")
	if err := os.WriteFile(*output, data, 0644); err != nil {
		log.Fatal(err)
	}
	fmt.Println(string(data))
	if heldStart != int64(*count) || heldEnd != int64(*count) {
		os.Exit(1)
	}
}
