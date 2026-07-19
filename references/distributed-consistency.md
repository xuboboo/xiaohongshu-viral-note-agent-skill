# Distributed consistency

Use PostgreSQL state when more than one API, scheduler or publishing Pod is running.

- Store publication state, draft snapshots, approval digests, cancellation epochs, lease tokens and
  idempotency fingerprints in PostgreSQL.
- Claim scheduled work with a bounded lease and `FOR UPDATE SKIP LOCKED`.
- Re-check the cancellation epoch immediately before the irreversible external submit operation.
- Treat cancellation after the external submit begins as a reconciliation case; never claim that an
  already accepted platform side effect was rolled back.
- Write business state and Outbox events in one transaction. Deliver Outbox events with leases,
  retry limits and dead-letter handling.
- Use Redis Streams for distributed jobs and SSE, `XAUTOCLAIM` for stale consumer recovery, and
  acknowledge plus delete completed entries to keep bounded queues reusable.
- Use database unique constraints for publish idempotency. Application-level checks are advisory;
  the database constraint is authoritative.
