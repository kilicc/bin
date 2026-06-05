# EVRIM_ACTIVE_SNAPSHOT_SYNC_REPORT

**Timestamp:** 20260523_144519

## 1. Backup path
`data/backups/evrim_active_snapshot_sync_20260523_144519`

## 2. Before values (active_snapshot)

| Field | Value |
|-------|-------|
| max_open | 18 |
| active_capital_pct | 0.92 |
| min_stake_usd | 140 |
| evrim_v2_normal_min | None |

## 3. After values (active_snapshot)

| Field | Value |
|-------|-------|
| max_open | 10 |
| active_capital_pct | 0.6 |
| min_stake_usd | 180 |
| evrim_v2_normal_min | 65 |

## 4. Effective trading profile values

| Field | profile | trading | active_snap |
|-------|---------|---------|-------------|
| max_open | 10 | 10 | 10 |
| active_capital_pct | 0.6 | 0.6 | 0.6 |
| min_stake_usd | 180 | 180 | 180 |
| evrim_v2_normal_min | 65 | 65 | 65 |

## 5. Candidate config status
- candidate_config_version: `evrim_cfg_candidate_20260523_143105_46665`
- candidate_status: `backtest`
- candidate NOT auto-applied to active

## 6. Pending approval status
- pending_approval: **True**
- evrim_v2_config_auto_apply: **False**

## 7. Other modes touched?
**no** — only `data/evrim_config_versions.json` active_snapshot updated; mode_profiles.json unchanged.

## 8. READY_FOR_RESTART
**YES**
