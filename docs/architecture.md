# Implemented consistency policy

PostgreSQL is the only decision authority. Admission locks the auction and assigns a strictly increasing intake sequence and database-generated timestamp. A stable global request UUID binds one immutable bidder/auction/amount tuple; payload changes return a conflict. A durable SQL intake journal closes the database-to-JetStream publication gap: failed publication leaves a pending record for relay retry.

Workers lock the auction before its lease and process the first pending SQL intake sequence. JetStream delivery is a wake-up journal; workers reconcile SQL pending records as well, so restore does not depend on exact cross-system snapshot alignment. The worker checks holder, expiry and epoch under the same transaction lock. Decisions, offers, ledger events and outbox commit together. Notifications are eventually delivered and may duplicate.

Strict global increments apply: the next eligible amount is max(reserve, highest current offer + increment). At most one same-price concurrent bid succeeds. Distinct current bidders are ranked by amount descending then decision sequence ascending. Allocation happens only after the server deadline and draining queued commands. Admission before the deadline remains eligible even when processed later. Manual close moves the deadline under the auction lock; it does not discard already admitted requests.

PostgreSQL row locks serialize a hot auction. Independent auctions may process concurrently. This is a correctness-first local implementation, not evidence of multi-zone HA or 50,000-client capacity.

Reference semantics: [PostgreSQL row locks](https://www.postgresql.org/docs/18/explicit-locking.html), [JetStream at-least-once delivery](https://docs.nats.io/concepts/jetstream).
