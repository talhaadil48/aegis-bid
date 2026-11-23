# Production extension deployment and proof

This runbook separates deployable mechanisms from measured infrastructure. A one-host result does not establish independent zones or offsite survival.

## Scalable realtime gateway and socket workload

`docker compose --env-file .env -f infra/compose.yaml -f infra/compose.scale.yaml up -d --build gateway web` enables the Go gateway and routes `/v1/live/` through it. The gateway fetches one authoritative snapshot per active auction per second and shares prepared frames among subscribers. Each connection has a single bounded update slot, a read limit, ping/pong expiry and a write deadline. API remains the authenticated decision/admission authority. Session identity is verified through the API and cached for at most 30 seconds. Snapshot source failure closes subscribers after three failed polls so reconnect can reconcile.

Default per-user socket quota is 10; total/per-auction quota is 60,000 per gateway process. For an **isolated socket-capacity test only**, set `MAX_USER_CONNECTIONS=60000` in the invoking shell and recreate gateway. Do not deploy that quota as a production anti-abuse policy. Tests sharing a demo identity establish socket capacity, not unique bidder capacity.

Run `python -m scripts.socket_capacity --connections 100 --shards 1 --hold 30`, then 1,000, 10,000 and, if resources permit, 50,000 with five shards. Export `DEMO_PASSWORD` into the shell. Results contain each shard's actual opened and retained connections, handshake latency, failure counts and timestamps. The aggregator rejects missing reports, duplicate shards, mixed runs, disjoint hold intervals and dropped sockets. Five source containers avoid exhausting one source IP's ephemeral port range. Results identify the shared host and explicitly exclude bid throughput.

On independent generator hosts, run `/usr/local/bin/load -url wss://<public-host>/v1/live/auctions/<id> -connections 10000 -ramp 50 -hold 120s -output shard.json` from the realtime image, passing `WS_COOKIE`, a common `RUN_ID`, and a unique `SHARD_ID` through a protected environment. Collect reports and use `scripts.socket_capacity.aggregate` with required=50000 and a common hold of at least 30 seconds. Every generator must read real auction snapshots. Match aggregate reports against gateway metrics and resource telemetry; do not sum non-overlapping peak counts.

Reference: [Gorilla concurrency and control frames](https://pkg.go.dev/github.com/gorilla/websocket).
