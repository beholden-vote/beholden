-- 007_nominate_dim2.sql · DW-NOMINATE second dimension (WO-36, DATA-CONTRACTS 8.7)
-- Voteview publishes nominate_dim2 in the same members CSV as dim1; it was landed
-- and never read. Stored beside the dim1 row it was estimated with (scheme
-- 'dw_nominate_dim1'), under the same vote floor. Nullable on purpose: a blank
-- cell or a member below the floor is honest absence, never a 0.

ALTER TABLE ideology_scores ADD COLUMN nominate_dim2 NUMERIC(6,4);
