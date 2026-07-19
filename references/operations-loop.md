# Operations loop

After a verified publication, schedule authorized metric synchronization at the configured delays
(default T+1h, T+24h and T+72h). Local development uses SQLite leases; multi-Pod enterprise mode
uses PostgreSQL leases and `SKIP LOCKED` so another worker can recover expired work.

The operations loop includes:

- published-note metric snapshots;
- cautious performance attribution with explicit correlation caveats;
- account-weight history and trend;
- content calendars and series planning;
- deterministic A/B/n assignment and experiment analysis;
- LinUCB contextual-bandit decisions and updates;
- tenant-isolated asset metadata referenced only by `asset_id`;
- post-performance retrospectives and next-note recommendations.

Do not optimize for fake engagement or infer causal effects from observational data. Experiments must
respect tenant policy, audience safety, commercial disclosure and publication approval requirements.
