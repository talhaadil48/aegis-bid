CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS users (
 id uuid PRIMARY KEY, username text UNIQUE NOT NULL, password_hash text NOT NULL,
 role text NOT NULL CHECK(role IN ('bidder','seller','admin','auditor'))
);
CREATE TABLE IF NOT EXISTS auctions (
 id uuid PRIMARY KEY, seller_id uuid NOT NULL REFERENCES users(id), title text NOT NULL,
 stock integer NOT NULL CHECK(stock>0), min_price_cents bigint NOT NULL CHECK(min_price_cents>0),
 increment_cents bigint NOT NULL CHECK(increment_cents>0), opens_at timestamptz NOT NULL,
 closes_at timestamptz NOT NULL, status text NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')),
 version bigint NOT NULL DEFAULT 0, intake_seq bigint NOT NULL DEFAULT 0,
 CHECK(closes_at>opens_at)
);
CREATE TABLE IF NOT EXISTS bid_requests (
 request_id uuid PRIMARY KEY, auction_id uuid NOT NULL REFERENCES auctions(id),
 bidder_id uuid NOT NULL REFERENCES users(id), amount_cents bigint NOT NULL CHECK(amount_cents>0),
 admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(), intake_seq bigint NOT NULL,
 state text NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','ACCEPTED','REJECTED','CLOSED')),
 published_at timestamptz, UNIQUE(auction_id,intake_seq)
);
CREATE TABLE IF NOT EXISTS worker_leases (
 auction_id uuid PRIMARY KEY REFERENCES auctions(id), holder_id text NOT NULL,
 epoch bigint NOT NULL, lease_expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS bid_decisions (
 decision_id bigserial PRIMARY KEY, request_id uuid UNIQUE NOT NULL REFERENCES bid_requests(request_id),
 auction_id uuid NOT NULL REFERENCES auctions(id), bidder_id uuid NOT NULL REFERENCES users(id),
 status text NOT NULL CHECK(status IN ('ACCEPTED','REJECTED','CLOSED')), reason text NOT NULL,
 effective_amount_cents bigint NOT NULL, decision_seq bigint NOT NULL, epoch bigint NOT NULL,
 committed_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(auction_id,decision_seq)
);
CREATE TABLE IF NOT EXISTS bidder_offers (
 auction_id uuid REFERENCES auctions(id), bidder_id uuid REFERENCES users(id),
 current_amount_cents bigint NOT NULL CHECK(current_amount_cents>0), decision_seq bigint NOT NULL,
 PRIMARY KEY(auction_id,bidder_id)
);
CREATE TABLE IF NOT EXISTS auction_events (
 event_id bigserial PRIMARY KEY, auction_id uuid NOT NULL REFERENCES auctions(id), event_seq bigint NOT NULL,
 payload jsonb NOT NULL, prev_hash text NOT NULL, event_hash text NOT NULL, UNIQUE(auction_id,event_seq)
);
CREATE TABLE IF NOT EXISTS winners (
 auction_id uuid REFERENCES auctions(id), bidder_id uuid REFERENCES users(id), rank integer NOT NULL CHECK(rank>0),
 final_amount_cents bigint NOT NULL, PRIMARY KEY(auction_id,bidder_id), UNIQUE(auction_id,rank)
);
CREATE TABLE IF NOT EXISTS outbox (
 id bigserial PRIMARY KEY, auction_id uuid NOT NULL REFERENCES auctions(id),
 event_type text NOT NULL, body jsonb NOT NULL, published_at timestamptz
);
CREATE TABLE IF NOT EXISTS backup_jobs (
 job_id text PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL,
 artifact_path text NOT NULL, checksum text, metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS recovery_runs (
 run_id uuid PRIMARY KEY, backup_id text NOT NULL, rpo_s numeric, rto_s numeric,
 verified boolean NOT NULL, report_path text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS incidents (
 id bigserial PRIMARY KEY, scenario text NOT NULL, state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS requests_pending ON bid_requests(auction_id,intake_seq) WHERE state='QUEUED';
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(id) WHERE published_at IS NULL;
INSERT INTO schema_migrations VALUES(1) ON CONFLICT DO NOTHING;
