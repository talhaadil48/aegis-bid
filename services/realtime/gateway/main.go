package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
)

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

type authEntry struct {
	subject string
	until   time.Time
}
type authFlight struct {
	done    chan struct{}
	subject string
	err     error
}
type client struct {
	socket  *websocket.Conn
	updates chan *websocket.PreparedMessage
	subject string
}
type hub struct {
	id, cookie string
	clients    map[*client]bool
	latest     *websocket.PreparedMessage
	failures   int
}
type server struct {
	mu                                   sync.Mutex
	authMu                               sync.Mutex
	hubs                                 map[string]*hub
	counts                               map[string]int
	auth                                 map[string]authEntry
	flights                              map[string]*authFlight
	authSlots                            chan struct{}
	http                                 *http.Client
	upstream, origin                     string
	total, maxTotal, maxAuction, maxUser int
	sent, slow, failed                   atomic.Int64
}

func integer(name string, fallback int) int {
	if value, err := strconv.Atoi(os.Getenv(name)); err == nil && value > 0 {
		return value
	}
	return fallback
}
func newServer() *server {
	upstream := os.Getenv("API_URL")
	if upstream == "" {
		upstream = "http://api:8000"
	}
	transport := &http.Transport{MaxIdleConns: 512, MaxIdleConnsPerHost: 256, MaxConnsPerHost: 256, IdleConnTimeout: 60 * time.Second}
	return &server{hubs: map[string]*hub{}, counts: map[string]int{}, auth: map[string]authEntry{}, flights: map[string]*authFlight{}, authSlots: make(chan struct{}, 256), http: &http.Client{Timeout: 5 * time.Second, Transport: transport}, upstream: strings.TrimRight(upstream, "/"), origin: os.Getenv("PUBLIC_ORIGIN"), maxTotal: integer("MAX_CONNECTIONS", 60000), maxAuction: integer("MAX_AUCTION_CONNECTIONS", 60000), maxUser: integer("MAX_USER_CONNECTIONS", 10)}
}
func (s *server) get(path, cookie string) ([]byte, int, error) {
	req, err := http.NewRequest("GET", s.upstream+path, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Cookie", "aegis_session="+cookie)
	response, err := s.http.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 1024*1024))
	return data, response.StatusCode, err
}
func (s *server) authenticate(cookie string) (string, error) {
	if cookie == "" {
		return "", fmt.Errorf("missing session")
	}
	digest := sha256.Sum256([]byte(cookie))
	key := hex.EncodeToString(digest[:])
	// Coalesce only identical sessions; distinct users must not wait on a global network lock.
	s.authMu.Lock()
	if entry, ok := s.auth[key]; ok && time.Now().Before(entry.until) {
		s.authMu.Unlock()
		return entry.subject, nil
	}
	if pending, ok := s.flights[key]; ok {
		s.authMu.Unlock()
		<-pending.done
		return pending.subject, pending.err
	}
	flight := &authFlight{done: make(chan struct{})}
	s.flights[key] = flight
	s.authMu.Unlock()
	s.authSlots <- struct{}{}
	data, status, err := s.get("/v1/auth/me", cookie)
	<-s.authSlots
	var identity struct {
		ID string `json:"id"`
	}
	if err != nil || status != 200 {
		err = fmt.Errorf("session verification failed")
	} else if json.Unmarshal(data, &identity) != nil || identity.ID == "" {
		err = fmt.Errorf("invalid identity")
	}
	s.authMu.Lock()
	if len(s.auth) > 100000 {
		for key, value := range s.auth {
			if time.Now().After(value.until) {
				delete(s.auth, key)
			}
		}
	}
	if err == nil {
		s.auth[key] = authEntry{identity.ID, time.Now().Add(30 * time.Second)}
	}
	flight.subject, flight.err = identity.ID, err
	delete(s.flights, key)
	close(flight.done)
	s.authMu.Unlock()
	return flight.subject, flight.err
}
func (s *server) snapshot(h *hub) (*websocket.PreparedMessage, error) {
	data, status, err := s.get("/v1/auctions/"+h.id, h.cookie)
	if err != nil || status != 200 {
		return nil, fmt.Errorf("snapshot unavailable: %d", status)
	}
	var body map[string]any
	if err = json.Unmarshal(data, &body); err != nil {
		return nil, err
	}
	body["type"] = "auction.snapshot"
	data, err = json.Marshal(body)
	if err != nil {
		return nil, err
	}
	return websocket.NewPreparedMessage(websocket.TextMessage, data)
}
func (s *server) originOK(r *http.Request) bool {
	origin := r.Header.Get("Origin")
	if origin == "" {
		return true
	}
	if s.origin != "" {
		return origin == s.origin
	}
	u, err := url.Parse(origin)
	return err == nil && u.Host == r.Host && (u.Scheme == "http" || u.Scheme == "https")
}
func (s *server) live(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/v1/live/auctions/")
	if !uuidPattern.MatchString(id) {
		http.Error(w, "Invalid auction", 400)
		return
	}
	cookie, err := r.Cookie("aegis_session")
	if err != nil {
		http.Error(w, "Sign in required", 401)
		return
	}
	subject, err := s.authenticate(cookie.Value)
	if err != nil {
		s.failed.Add(1)
		http.Error(w, "Sign in required", 401)
		return
	}
	if !s.originOK(r) {
		http.Error(w, "Origin denied", 403)
		return
	}
	s.mu.Lock()
	h, exists := s.hubs[id]
	if !exists {
		h = &hub{id: id, cookie: cookie.Value, clients: map[*client]bool{}}
		h.latest, err = s.snapshot(h)
		if err != nil {
			s.mu.Unlock()
			http.Error(w, "Auction unavailable", 503)
			return
		}
		s.hubs[id] = h
	}
	if s.total >= s.maxTotal || len(h.clients) >= s.maxAuction || s.counts[subject] >= s.maxUser {
		s.mu.Unlock()
		http.Error(w, "Connection quota exceeded", 429)
		return
	}
	upgrader := websocket.Upgrader{CheckOrigin: s.originOK, ReadBufferSize: 1024, WriteBufferSize: 1024, HandshakeTimeout: 5 * time.Second}
	socket, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		s.mu.Unlock()
		return
	}
	c := &client{socket: socket, updates: make(chan *websocket.PreparedMessage, 1), subject: subject}
	h.clients[c] = true
	s.counts[subject]++
	s.total++
	c.updates <- h.latest
	s.mu.Unlock()
	if !exists {
		go s.poll(h)
	}
	go s.write(c)
	socket.SetReadLimit(1024)
	_ = socket.SetReadDeadline(time.Now().Add(60 * time.Second))
	socket.SetPongHandler(func(string) error { return socket.SetReadDeadline(time.Now().Add(60 * time.Second)) })
	for {
		if _, _, err = socket.ReadMessage(); err != nil {
			break
		}
	}
	s.mu.Lock()
	delete(h.clients, c)
	s.total--
	s.counts[subject]--
	if s.counts[subject] == 0 {
		delete(s.counts, subject)
	}
	close(c.updates)
	s.mu.Unlock()
	_ = socket.Close()
}
func (s *server) poll(h *hub) {
	interval := integer("SNAPSHOT_INTERVAL_MS", 1000)
	if interval < 250 || interval > 10000 {
		interval = 1000
	}
	ticker := time.NewTicker(time.Duration(interval) * time.Millisecond)
	defer ticker.Stop()
	for range ticker.C {
		s.mu.Lock()
		if len(h.clients) == 0 {
			delete(s.hubs, h.id)
			s.mu.Unlock()
			return
		}
		s.mu.Unlock()
		update, err := s.snapshot(h)
		s.mu.Lock()
		if err != nil {
			h.failures++
			if h.failures >= 3 {
				for c := range h.clients {
					_ = c.socket.Close()
				}
			}
			s.mu.Unlock()
			continue
		}
		h.failures = 0
		h.latest = update
		for c := range h.clients {
			select {
			case c.updates <- update:
			default:
				select {
				case <-c.updates:
				default:
				}
				select {
				case c.updates <- update:
				default:
				}
			}
		}
		s.mu.Unlock()
	}
}
func (s *server) write(c *client) {
	ping := time.NewTicker(20 * time.Second)
	defer ping.Stop()
	defer c.socket.Close()
	for {
		select {
		case message, ok := <-c.updates:
			if !ok {
				return
			}
			_ = c.socket.SetWriteDeadline(time.Now().Add(5 * time.Second))
			if c.socket.WritePreparedMessage(message) != nil {
				s.slow.Add(1)
				return
			}
			s.sent.Add(1)
		case <-ping.C:
			if c.socket.WriteControl(websocket.PingMessage, nil, time.Now().Add(5*time.Second)) != nil {
				return
			}
		}
	}
}
func (s *server) metrics(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	total, hubs := s.total, len(s.hubs)
	s.mu.Unlock()
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "gateway_connected_clients %d\ngateway_auction_hubs %d\ngateway_snapshots_sent_total %d\ngateway_slow_disconnects_total %d\ngateway_auth_failures_total %d\n", total, hubs, s.sent.Load(), s.slow.Load(), s.failed.Load())
}
func main() {
	s := newServer()
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/live/auctions/", s.live)
	admission := newAdmissionProxy(s.upstream, s.origin)
	target, err := url.Parse(s.upstream)
	if err != nil {
		log.Fatal("Invalid API upstream")
	}
	reads := httputil.NewSingleHostReverseProxy(target)
	auctionRoutes := func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/bids") {
			admission.serve(w, r)
		} else {
			reads.ServeHTTP(w, r)
		}
	}
	mux.HandleFunc("/v1/auctions/", auctionRoutes)
	mux.HandleFunc("/v1/auctions", auctionRoutes)
	mux.HandleFunc("/metrics", s.metrics)
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	httpServer := &http.Server{Addr: ":8081", Handler: mux, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal(err)
		}
	}()
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	<-stop
	s.mu.Lock()
	for _, h := range s.hubs {
		for c := range h.clients {
			_ = c.socket.Close()
		}
	}
	s.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(ctx)
}
