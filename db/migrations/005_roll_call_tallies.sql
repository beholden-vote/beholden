-- 005_roll_call_tallies.sql · Chamber-wide vote tallies on roll calls (WO-12)
-- yea_count / nay_count come VERBATIM from the Voteview rollcalls CSV — the same
-- fields the key-vote closeness score already reads from raw at build time
-- (sources/voteview.to_rollcall_meta). Persisted so the published per-vote tally
-- is warehouse-backed like every other roll-call fact. Nullable on purpose: a
-- row whose snapshot lacks a tally publishes honest absence, never a fabricated 0.

ALTER TABLE roll_calls ADD COLUMN yea_count INTEGER;
ALTER TABLE roll_calls ADD COLUMN nay_count INTEGER;
