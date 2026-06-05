# V2_DATA_FLOW_CALIBRATION_REPORT

**Timestamp:** 20260523_151315  
**Backup:** `data/backups/v2_data_flow_calibration_20260523_151315`

## 1. Before counts

| Mod | paper open | paper closed |
|-----|------------|--------------|
| evrim | 0 | 0 |
| berserk | 6 | 75 |
| hunter | 0 | 0 |
| chop_master | 0 | 0 |
| sentinel | 0 | 0 |

## 2. Why only Berserk was trading

Routing doğru: evrim=live, diğerleri=paper. Berserk en agresif filtreler. Hunter/Chop/Sentinel sıkı V2 eşikleri + erken rejectler yetersiz loglanıyordu (düzeltildi).

## 3. Hunter calibration

`minimum_data` + `hunter_paper_exploration`: breakout 62, fake_risk<70, weak→watchlist, `hunter_exploration_breakout_test`

## 4. Chop calibration

chop_score observation/trade, trend_guard→observation, `chop_not_safe` log

## 5. Sentinel calibration

quality≥68 + exec≥75 explore; benchmark 5 dk (`force_benchmark`)

## 6. Evrim live visibility

`evrim_live_decisions.py` + `/api/evrim/live-decisions` + `evrimLivePanel` dashboard

## 7. Zero-data guard

`no_trade_due_to_filters` when decisions>0 trades=0

## 8. Reject logging

`mode_reject_buffer` 500/mod + `_reject_entry` hooks

## 9. Tests

27 passed (`test_minimum_data_flow` + `test_live_vs_paper_parallel` + `test_evrim_v2_mode`)

## 10. Restart required?

**YES**

## Changed files

- elite_trader/mode_reject_buffer.py
- elite_trader/mode_minimum_data.py
- elite_trader/hunter_paper_exploration.py
- elite_trader/chop_paper_exploration.py
- elite_trader/sentinel_paper_exploration.py
- elite_trader/evrim_live_decisions.py
- elite_trader/evrim_zero_data_guard.py
- elite_trader/parallel_universe_engine.py
- elite_trader/sentinel_benchmark.py
- elite_trader/evrim_meta_score.py
- elite_trader/evrim_cross_strategy_lab.py
- elite_trader/order_gate.py
- binance_elite_pro.py
- elite_pro_template.html
- data/mode_profiles.json
- elite_trader/mode_profiles.py
- scripts/post_restart_data_flow_diagnosis.py
- tests/test_minimum_data_flow.py
