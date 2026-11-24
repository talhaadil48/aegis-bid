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
-- Admission refusals are durable receipts, not events appended after a sealed auction.
CREATE TABLE IF NOT EXISTS admission_outcomes (
 request_id uuid PRIMARY KEY REFERENCES bid_requests(request_id),
 status text NOT NULL CHECK(status='CLOSED'), reason text NOT NULL,
 finalized_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO schema_migrations VALUES(2) ON CONFLICT DO NOTHING;

-- One server-side admission operation avoids application round trips while the
-- per-auction intake lock is held. Decision workers use their separate row lock.
CREATE OR REPLACE FUNCTION aegis_admit_batch(p_aid uuid,p_ids uuid[],p_users uuid[],p_amounts bigint[],p_capacity integer)
RETURNS TABLE(request_id uuid,auction_id uuid,bidder_id uuid,amount_cents bigint,admitted_at timestamptz,intake_seq bigint,state text,published_at timestamptz,error_code text)
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
 a auctions%ROWTYPE;
 stamp timestamptz;
 expired boolean;
 last_seq bigint;
 pending bigint := 0;
BEGIN
 IF cardinality(p_ids) NOT BETWEEN 1 AND 1024 OR cardinality(p_users)<>cardinality(p_ids) OR cardinality(p_amounts)<>cardinality(p_ids) THEN
  RAISE EXCEPTION 'Invalid admission batch dimensions';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(ordered.rid::text,0))
 FROM (SELECT DISTINCT unnest(p_ids) rid ORDER BY rid) ordered;
 PERFORM pg_advisory_xact_lock(hashtextextended('aegis-intake:'||p_aid::text,0));
 SELECT x.* INTO a FROM auctions x WHERE x.id=p_aid;
 IF NOT FOUND THEN
  RETURN QUERY SELECT i.rid,p_aid,i.uid,i.amount,NULL::timestamptz,NULL::bigint,NULL::text,NULL::timestamptz,'NO_AUCTION'::text
  FROM unnest(p_ids,p_users,p_amounts) i(rid,uid,amount);
  RETURN;
 END IF;
 stamp := clock_timestamp();
 expired := a.status='CLOSED' OR stamp>=a.closes_at;
 SELECT greatest(a.intake_seq,coalesce(max(r.intake_seq),0)) INTO last_seq FROM bid_requests r WHERE r.auction_id=p_aid;
 IF NOT expired AND last_seq+cardinality(p_ids)>p_capacity THEN
  SELECT count(*) INTO pending FROM bid_requests r WHERE r.auction_id=p_aid AND r.state='QUEUED';
 END IF;
 WITH firsts AS (
  SELECT DISTINCT ON(i.rid) i.rid,i.uid,i.amount,i.ord
  FROM unnest(p_ids,p_users,p_amounts) WITH ORDINALITY i(rid,uid,amount,ord)
  ORDER BY i.rid,i.ord
 ), fresh AS (
  SELECT f.*,row_number() OVER(ORDER BY f.ord) pos
  FROM firsts f LEFT JOIN bid_requests r ON r.request_id=f.rid WHERE r.request_id IS NULL
 ), introduced AS (
  INSERT INTO bid_requests(request_id,auction_id,bidder_id,amount_cents,intake_seq,admitted_at,state)
  SELECT f.rid,p_aid,f.uid,f.amount,last_seq+f.pos,stamp,CASE WHEN expired THEN 'CLOSED' ELSE 'QUEUED' END
  FROM fresh f WHERE expired OR f.pos<=p_capacity-pending
  RETURNING bid_requests.request_id
 )
 INSERT INTO admission_outcomes(request_id,status,reason)
 SELECT n.request_id,'CLOSED','Auction deadline passed' FROM introduced n WHERE expired;
 RETURN QUERY
 SELECT i.rid,r.auction_id,r.bidder_id,r.amount_cents,r.admitted_at,r.intake_seq,r.state,r.published_at,
  CASE WHEN r.request_id IS NULL THEN 'CAPACITY'
   WHEN ROW(r.auction_id,r.bidder_id,r.amount_cents) IS DISTINCT FROM ROW(p_aid,i.uid,i.amount) THEN 'CONFLICT'
   ELSE NULL END
 FROM unnest(p_ids,p_users,p_amounts) WITH ORDINALITY i(rid,uid,amount,ord)
 LEFT JOIN bid_requests r ON r.request_id=i.rid ORDER BY i.ord;
END $$;
INSERT INTO schema_migrations VALUES(3) ON CONFLICT DO NOTHING;
