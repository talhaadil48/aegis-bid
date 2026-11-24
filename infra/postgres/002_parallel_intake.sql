ALTER TABLE auctions ADD COLUMN IF NOT EXISTS processed_intake_seq bigint NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION aegis_init_intake_sequence() RETURNS trigger
LANGUAGE plpgsql SET search_path=public,pg_catalog AS $$
BEGIN
 EXECUTE format('CREATE SEQUENCE IF NOT EXISTS public.%I AS bigint START WITH %s CACHE 1',
  'aegis_intake_'||replace(NEW.id::text,'-',''),greatest(NEW.intake_seq,0)+1);
 RETURN NEW;
END $$;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='aegis_init_intake' AND tgrelid='public.auctions'::regclass) THEN
  CREATE TRIGGER aegis_init_intake AFTER INSERT ON auctions FOR EACH ROW EXECUTE FUNCTION aegis_init_intake_sequence();
 END IF;
END $$;

CREATE OR REPLACE FUNCTION aegis_admit_batch(p_aid uuid,p_ids uuid[],p_users uuid[],p_amounts bigint[],p_capacity integer)
RETURNS TABLE(request_id uuid,auction_id uuid,bidder_id uuid,amount_cents bigint,admitted_at timestamptz,intake_seq bigint,state text,published_at timestamptz,error_code text)
LANGUAGE plpgsql VOLATILE SET search_path=public,pg_catalog AS $$
DECLARE
 a auctions%ROWTYPE;
 stamp timestamptz;
 expired boolean;
 last_seq bigint;
 pending bigint := 0;
 reserved bigint[];
 reserve_key text := 'aegis-reserve:'||p_aid::text;
 intake_key text := 'aegis-intake:'||p_aid::text;
 sequence_name text := 'aegis_intake_'||replace(p_aid::text,'-','');
 sequence_oid regclass;
BEGIN
 IF cardinality(p_ids) NOT BETWEEN 1 AND 1024 OR cardinality(p_users)<>cardinality(p_ids) OR cardinality(p_amounts)<>cardinality(p_ids) THEN
  RAISE EXCEPTION 'Invalid admission batch dimensions';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(ordered.rid::text,0))
 FROM (SELECT DISTINCT unnest(p_ids) rid ORDER BY rid) ordered;
 SELECT x.* INTO a FROM auctions x WHERE x.id=p_aid;
 IF NOT FOUND THEN
  RETURN QUERY SELECT i.rid,p_aid,i.uid,i.amount,NULL::timestamptz,NULL::bigint,NULL::text,NULL::timestamptz,'NO_AUCTION'::text
  FROM unnest(p_ids,p_users,p_amounts) i(rid,uid,amount);
  RETURN;
 END IF;
 -- This short session lock orders reservations and lock-mode acquisition only;
 -- it is released before inserts, so ordinary admission transactions overlap.
 PERFORM pg_advisory_lock(hashtextextended(reserve_key,0));
 BEGIN
  sequence_oid := to_regclass('public.'||sequence_name);
  IF sequence_oid IS NULL THEN
   SELECT greatest(a.intake_seq,coalesce(max(r.intake_seq),0))+1 INTO last_seq FROM bid_requests r WHERE r.auction_id=p_aid;
   BEGIN
    EXECUTE format('CREATE SEQUENCE public.%I AS bigint START WITH %s CACHE 1',sequence_name,last_seq);
   EXCEPTION WHEN duplicate_table OR unique_violation THEN
    -- A legacy auction may race first-time initialization; CREATE waits for
    -- the original creator to commit before this fresh lookup can proceed.
    NULL;
   END;
   sequence_oid := to_regclass('public.'||sequence_name);
  END IF;
  SELECT array_agg(nextval(sequence_oid) ORDER BY n) INTO reserved FROM generate_series(1,cardinality(p_ids)) n;
  SELECT x.* INTO a FROM auctions x WHERE x.id=p_aid;
  IF reserved[cardinality(reserved)]-a.processed_intake_seq<=p_capacity THEN
   PERFORM pg_advisory_xact_lock_shared(hashtextextended(intake_key,0));
  ELSE
   -- A possible full queue takes an exclusive lock and counts exactly. New
   -- reservations cannot overtake us while this reservation lock is held.
   PERFORM pg_advisory_xact_lock(hashtextextended(intake_key,0));
  END IF;
  stamp := clock_timestamp();
  PERFORM pg_advisory_unlock(hashtextextended(reserve_key,0));
 EXCEPTION WHEN OTHERS OR query_canceled THEN
  PERFORM pg_advisory_unlock(hashtextextended(reserve_key,0));
  RAISE;
 END;
 SELECT x.* INTO a FROM auctions x WHERE x.id=p_aid;
 expired := a.status='CLOSED' OR stamp>=a.closes_at;
 IF NOT expired AND reserved[cardinality(reserved)]-a.processed_intake_seq>p_capacity THEN
  SELECT count(*) INTO pending FROM bid_requests r WHERE r.auction_id=p_aid AND r.state='QUEUED';
 END IF;
 WITH firsts AS (
  SELECT DISTINCT ON(i.rid) i.rid,i.uid,i.amount,i.seq,i.ord
  FROM unnest(p_ids,p_users,p_amounts,reserved) WITH ORDINALITY i(rid,uid,amount,seq,ord)
  ORDER BY i.rid,i.ord
 ), fresh AS (
  SELECT f.*,row_number() OVER(ORDER BY f.ord) pos
  FROM firsts f LEFT JOIN bid_requests r ON r.request_id=f.rid WHERE r.request_id IS NULL
 ), introduced AS (
  INSERT INTO bid_requests(request_id,auction_id,bidder_id,amount_cents,intake_seq,admitted_at,state)
  SELECT f.rid,p_aid,f.uid,f.amount,f.seq,stamp,CASE WHEN expired THEN 'CLOSED' ELSE 'QUEUED' END
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
INSERT INTO schema_migrations VALUES(4) ON CONFLICT DO NOTHING;
