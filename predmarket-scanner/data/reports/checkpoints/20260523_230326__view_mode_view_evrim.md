# Checkpoint — Görünüm berserk → evrim

## CHECKPOINT_META

| Alan | Değer |
|------|-------|
| checkpoint_id | `20260523_230326__view_mode_view_evrim` |
| created_at | `2026-05-23T23:03:26.746927+00:00` |
| event_type | `view_mode` |
| label | Görünüm berserk → evrim |
| project_root | `predmarket-scanner` |
| md_path | `data/reports/checkpoints/20260523_230326__view_mode_view_evrim.md` |

## EVENT_DETAILS

```json
{
  "old_view": "berserk",
  "new_view": "evrim",
  "view_mode": "evrim"
}
```

## AI_RESTORE_PLAYBOOK

Bu checkpoint'e dönmek için aşağıdaki adımları uygula. **9005 state DB, lessons ve evrim_persistent_learning.json silinmemeli** (DATA_PRESERVATION).

### 1. Panel görünümü
- `view_mode`: `evrim`
```python
from elite_trader.panel_strategy import set_view_mode
set_view_mode("evrim")
```

### 2. panel_strategy_state.json (tam)
```json
{
  "execution_mode": "evrim",
  "active_futures_mode": "evrim",
  "view_mode": "evrim",
  "current_mode": "evrim",
  "last_execution_change_at": "2026-05-23T14:31:05.551732+00:00",
  "last_execution_note": "emir motoru evrim → evrim"
}
```

### Koruma — dokunma
- `data/binance_elite_8300_9005_state.db`
- `data/evrim_persistent_learning.json`
- `data/deleted_archives/`

## FULL_STATE_SNAPSHOT

```json
{
  "collected_at": "2026-05-23T23:03:26.746290+00:00",
  "panel_strategy_state": {
    "execution_mode": "evrim",
    "active_futures_mode": "evrim",
    "view_mode": "evrim",
    "current_mode": "evrim",
    "last_execution_change_at": "2026-05-23T14:31:05.551732+00:00",
    "last_execution_note": "emir motoru evrim → evrim"
  },
  "mode_profiles": {
    "version": 2,
    "modes": {
      "evrim": {
        "label": "Evrim",
        "short_label": "Evrim",
        "description": "V2 meta-adaptive live brain — diğer 4 moddan read-only özet; canlı aday.",
        "role": "v2_live_meta_adaptive_brain",
        "trading_style": "adaptive_multi_mode_meta_trader",
        "learning_access": "all_modes_summary_read",
        "spread_policy": "evrim_adaptive",
        "min_edge": 0.08,
        "min_formula_score": 0.56,
        "market_cooldown_min": 0.35,
        "tp_stake_pct": 0.0042,
        "sl_stake_pct": 0.0024,
        "tp_trigger_frac": 1.0,
        "spike_enabled": true,
        "spike_min_age_sec": 7,
        "spike_fee_mult": 1.12,
        "spike_max_tp_frac": 0.82,
        "stale_enabled": true,
        "stale_min_age_min": 0.2,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 180,
        "active_capital_pct": 0.6,
        "max_open": 10,
        "entry_max_open": 10,
        "default_paper": false,
        "can_trade_live": true,
        "scan_interval_sec": 0.8,
        "position_check_sec": 0.15,
        "trade_top_n": 150,
        "sl_em_veto_count": 1,
        "sl_em_cooldown_min": 15,
        "min_hold_before_sl_sec": 8,
        "sl_emergency_mult": 1.12,
        "entry_min_strength": "Medium",
        "entry_stake_mult": 1.0,
        "entry_skip_cautious": false,
        "entry_block_weak": false,
        "evrim_v2_min_final_score": 55,
        "evrim_v2_normal_min": 65,
        "evrim_v2_aggressive_min": 78,
        "evrim_v2_high_conviction_min": 88,
        "evrim_v2_hourly_target_pct": 4.0,
        "evrim_v2_daily_2x_mult": 2.0,
        "evrim_v2_max_daily_drawdown_pct": 12,
        "evrim_v2_half_risk_drawdown_pct": 8,
        "evrim_v2_fee_gross_caution": 0.45,
        "evrim_v2_fee_gross_recovery": 0.75,
        "evrim_v2_spread_tp_veto_frac": 0.65,
        "evrim_v2_slippage_tp_veto_frac": 0.5,
        "evrim_v2_exploration_idle_min": 20,
        "evrim_v2_config_auto_apply": false,
        "evrim_min_total_score": 50,
        "evrim_max_tier": "aggressive",
        "evrim_live_training": true,
        "evrim_unified_engine_enabled": true,
        "evrim_trading_mode": "demo",
        "evrim_live_trading_enabled": false,
        "evrim_news_shock_sec": 90,
        "evrim_chop_trade_enabled": true,
        "evrim_spread_hard_veto_tp_frac": 0.55,
        "evrim_radar_hard_veto_only_extreme": true,
        "evrim_fee_hard_block": false,
        "evrim_flow_recovery_enabled": true,
        "evrim_expectancy_min_net_usd": 0.05,
        "evrim_mtf_enabled": true,
        "evrim_mtf_timeframes": [
          "5m",
          "15m",
          "1h"
        ],
        "evrim_adx_chop_threshold": 18,
        "evrim_atr_stake_floor_mult": 0.8,
        "evrim_pa_enabled": true,
        "evrim_pa_fake_veto_threshold": 0.72,
        "evrim_pa_fake_stake_mult": 0.55,
        "evrim_vo_enabled": true,
        "evrim_vo_rel_vol_boost": 1.2,
        "evrim_vo_aggressive_rel_vol": 1.8,
        "evrim_vo_spread_veto_pct": 0.12,
        "evrim_vo_slippage_stake_bps": 25,
        "evrim_vo_slippage_stake_mult": 0.7,
        "evrim_regime_enabled": true,
        "evrim_regime_news_spread_pct": 0.15,
        "evrim_regime_fake_pump_prob": 0.6,
        "evrim_dynamic_exit_enabled": true,
        "evrim_partial_tp_frac": 0.5,
        "evrim_trailing_enabled": true,
        "evrim_momentum_weak_exit": true,
        "evrim_breakeven_buffer_pct": 0.08,
        "evrim_expectancy_enabled": true,
        "evrim_trade_learning_enabled": true,
        "evrim_param_auto_test_enabled": true,
        "evrim_market_radar_enabled": true,
        "evrim_radar_spread_spike_pct": 0.18,
        "evrim_radar_news_spread_wait_pct": 0.14,
        "evrim_radar_api_max_ms": 2500,
        "regime_overrides": {
          "chop": {
            "min_score_delta": 5,
            "stake_mult": 0.5
          }
        },
        "dynamic_exit_overrides": {
          "tp_mult": 0.92,
          "sl_mult": 1.05
        },
        "expectancy_overrides": {
          "stake_mult": 0.85,
          "min_score_delta": 1
        }
      },
      "berserk": {
        "label": "Berserk",
        "short_label": "Berserk",
        "description": "V2 micro momentum velocity lab — yüksek sirkülasyon paper veri + koşullu live.",
        "role": "v2_micro_momentum_velocity_lab",
        "trading_style": "ultra_fast_micro_scalp",
        "learning_access": "own_data_only",
        "spread_policy": "dynamic_micro",
        "max_spread_pct": 0.12,
        "soft_spread_start_pct": 0.06,
        "min_edge": 0.032,
        "min_formula_score": 0.44,
        "market_cooldown_min": 0.02,
        "tp_stake_pct": 0.0042,
        "sl_stake_pct": 0.0024,
        "tp_trigger_frac": 0.99,
        "spike_enabled": true,
        "spike_min_age_sec": 4,
        "spike_fee_mult": 1.08,
        "spike_max_tp_frac": 0.88,
        "stale_enabled": true,
        "stale_min_age_min": 0.15,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 120,
        "active_capital_pct": 0.7,
        "max_open": 14,
        "entry_max_open": 14,
        "scan_interval_sec": 0.35,
        "position_check_sec": 0.06,
        "trade_top_n": 220,
        "sl_em_veto_count": 0,
        "sl_em_cooldown_min": 4,
        "min_hold_before_sl_sec": 2,
        "sl_emergency_mult": 1.25,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.05,
        "entry_skip_cautious": false,
        "entry_block_weak": false,
        "berserk_min_move_pct": 0.08,
        "berserk_min_score": 40,
        "berserk_normal_score": 57,
        "berserk_aggressive_score": 75,
        "berserk_recovery_fee_gross_pct": 0.75,
        "berserk_reentry_max_failures": 3,
        "berserk_reentry_ban_min": 3.0,
        "weak_stake_multiplier": 0.45,
        "medium_stake_multiplier": 0.75,
        "strong_stake_multiplier": 1.0,
        "paper_fee_side": 0.0004,
        "same_symbol_max_open": 1,
        "live_permission": "conditional_if_active_futures_mode"
      },
      "hunter": {
        "label": "Hunter",
        "short_label": "Hunter",
        "description": "V2 breakout / spike / liquidation avcısı — büyük hareket yakalama.",
        "role": "v2_breakout_spike_liquidation_hunter",
        "trading_style": "explosive_move_capture",
        "learning_access": "own_data_only",
        "spread_policy": "hunter_medium_penalty",
        "max_spread_pct": 0.18,
        "soft_spread_start_pct": 0.08,
        "min_edge": 0.055,
        "min_formula_score": 0.48,
        "market_cooldown_min": 0.8,
        "tp_stake_pct": 0.0095,
        "sl_stake_pct": 0.0042,
        "tp_trigger_frac": 1.0,
        "spike_enabled": true,
        "spike_min_age_sec": 8,
        "spike_fee_mult": 1.18,
        "spike_max_tp_frac": 0.72,
        "stale_enabled": true,
        "stale_min_age_min": 0.8,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 160,
        "active_capital_pct": 0.5,
        "max_open": 6,
        "entry_max_open": 6,
        "scan_interval_sec": 1.0,
        "position_check_sec": 0.15,
        "trade_top_n": 160,
        "sl_em_veto_count": 1,
        "sl_em_cooldown_min": 20,
        "min_hold_before_sl_sec": 12,
        "sl_emergency_mult": 1.05,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.0,
        "entry_skip_cautious": false,
        "entry_block_weak": false,
        "hunter_min_spike_change_pct": 0.18,
        "hunter_min_spike_vol_ratio": 1.15,
        "hunter_breakout_change_pct": 0.24,
        "hunter_breakout_vol_ratio": 1.2,
        "hunter_liquidation_proxy_min": 0.25,
        "hunter_spike_min_confirmation_sec": 3,
        "hunter_spike_max_confirmation_sec": 8,
        "hunter_min_breakout_score": 42,
        "hunter_strong_breakout_score": 70,
        "hunter_explosive_score": 85,
        "hunter_chop_trade_enabled": false,
        "same_symbol_max_open": 1,
        "evrim_min_total_score": 62,
        "evrim_chop_trade_enabled": false,
        "minimum_data_mode_enabled": true,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": true,
        "minimum_data_never_live": true,
        "hunter_explore_breakout_score_min": 42,
        "hunter_explore_fake_risk_max": 78,
        "hunter_explore_stake_mult": 0.35,
        "hunter_explore_max_open": 2,
        "hunter_explore_cooldown_min": 2.0,
        "hunter_explore_only_paper": true,
        "hunter_explore_learning_tag": "hunter_exploration_breakout_test"
      },
      "chop_master": {
        "label": "Chop Master",
        "short_label": "Chop",
        "description": "V2 yatay piyasa mean reversion / range reversal micro scalp.",
        "role": "v2_chop_mean_reversion_lab",
        "trading_style": "range_reversal_micro_scalp",
        "learning_access": "own_data_only",
        "spread_policy": "chop_tight",
        "chop_max_spread_pct": 0.12,
        "chop_spread_soft_start": 0.05,
        "chop_spread_limit_start": 0.09,
        "chop_min_score_trade": 50,
        "chop_observation_min": 38,
        "chop_strong_score": 80,
        "chop_mr_min_score": 58,
        "chop_min_range_width_mult": 2.2,
        "chop_min_expected_move_mult": 1.15,
        "chop_hunter_breakout_veto": 78,
        "min_edge": 0.045,
        "min_formula_score": 0.45,
        "market_cooldown_min": 0.4,
        "tp_stake_pct": 0.0028,
        "sl_stake_pct": 0.0018,
        "tp_trigger_frac": 0.99,
        "spike_enabled": false,
        "spike_min_age_sec": 20,
        "spike_fee_mult": 1.05,
        "spike_max_tp_frac": 0.6,
        "stale_enabled": true,
        "stale_min_age_min": 0.15,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 120,
        "active_capital_pct": 0.4,
        "max_open": 5,
        "entry_max_open": 5,
        "same_symbol_max_open": 1,
        "scan_interval_sec": 0.8,
        "position_check_sec": 0.12,
        "trade_top_n": 120,
        "sl_em_veto_count": 1,
        "sl_em_cooldown_min": 10,
        "min_hold_before_sl_sec": 5,
        "sl_emergency_mult": 1.0,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 0.85,
        "entry_skip_cautious": false,
        "entry_block_weak": false,
        "default_paper": true,
        "can_trade_live": true,
        "evrim_min_total_score": 52,
        "evrim_chop_trade_enabled": true,
        "evrim_chop_stake_mult": 0.35,
        "evrim_chop_max_open": 4,
        "minimum_data_mode_enabled": true,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": true,
        "minimum_data_never_live": true,
        "chop_explore_chop_score_min": 48,
        "chop_explore_observation_min": 42,
        "chop_explore_range_cost_mult": 2.5,
        "chop_explore_stake_mult": 0.3,
        "chop_explore_max_open": 2,
        "chop_explore_cooldown_min": 2.5,
        "chop_explore_only_paper": true,
        "chop_explore_learning_tag": "chop_exploration_mean_reversion_test"
      },
      "sentinel": {
        "label": "Sentinel",
        "short_label": "Sentinel",
        "description": "V2 kalite trend / risk benchmark — düşük DD, yüksek PF, Evrim radar.",
        "role": "v2_quality_trend_risk_benchmark",
        "trading_style": "selective_trend_following",
        "learning_access": "own_data_only",
        "spread_policy": "sentinel_strict",
        "max_spread_pct": 0.12,
        "soft_spread_start_pct": 0.08,
        "min_edge": 0.075,
        "min_formula_score": 0.48,
        "market_cooldown_min": 3.0,
        "tp_stake_pct": 0.0095,
        "sl_stake_pct": 0.0042,
        "tp_trigger_frac": 1.02,
        "spike_enabled": true,
        "spike_min_age_sec": 25,
        "spike_fee_mult": 1.25,
        "spike_max_tp_frac": 0.6,
        "stale_enabled": true,
        "stale_min_age_min": 1.2,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 180,
        "active_capital_pct": 0.32,
        "max_open": 3,
        "entry_max_open": 3,
        "scan_interval_sec": 3.0,
        "position_check_sec": 0.5,
        "trade_top_n": 80,
        "sl_em_veto_count": 2,
        "sl_em_cooldown_min": 45,
        "min_hold_before_sl_sec": 30,
        "sl_emergency_mult": 0.9,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 0.9,
        "entry_skip_cautious": false,
        "entry_block_weak": false,
        "medium_stake_multiplier": 0.6,
        "strong_stake_multiplier": 1.0,
        "same_symbol_max_open": 1,
        "default_paper": true,
        "can_trade_live": true,
        "sentinel_min_quality_score": 50,
        "sentinel_min_formula_score_engine": 0.5,
        "sentinel_min_execution_score": 58,
        "sentinel_chop_min_quality_score": 72,
        "sentinel_chop_premium_min_score": 85,
        "sentinel_allow_medium_if_quality": true,
        "sentinel_news_risk_mode": "risk_off",
        "sentinel_trend_misalignment_mode": "veto",
        "evrim_min_total_score": 68,
        "evrim_chop_trade_enabled": false,
        "minimum_data_mode_enabled": true,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": true,
        "minimum_data_never_live": true,
        "sentinel_explore_quality_min": 55,
        "sentinel_explore_execution_min": 62,
        "sentinel_explore_stake_mult": 0.25,
        "sentinel_explore_max_open": 1,
        "sentinel_explore_cooldown_min": 5.0,
        "sentinel_explore_only_paper": true,
        "sentinel_explore_learning_tag": "sentinel_exploration_quality_test"
      }
    },
    "updated_at": "2026-05-23T23:01:07.093638+00:00"
  },
  "evrim_config_versions": {
    "active_config_version": "evrim_cfg_active_20260523_214344_72624",
    "active_snapshot": {
      "evrim_v2_fee_gross_caution": 0.45,
      "min_stake_usd": 180,
      "max_open": 10,
      "active_capital_pct": 0.6,
      "evrim_v2_hourly_target_pct": 4.0,
      "same_symbol_max_open": 1,
      "evrim_max_tier": "aggressive",
      "min_edge": 0.08,
      "evrim_v2_high_conviction_min": 88,
      "learning_access": "all_modes_summary_read",
      "tp_stake_pct": 0.0042,
      "evrim_v2_fee_gross_recovery": 0.75,
      "evrim_v2_half_risk_drawdown_pct": 8,
      "evrim_v2_spread_tp_veto_frac": 0.65,
      "tp_trigger_frac": 1.0,
      "entry_stake_mult": 1.0,
      "evrim_v2_max_daily_drawdown_pct": 12,
      "trading_style": "adaptive_multi_mode_meta_trader",
      "position_check_sec": 0.15,
      "evrim_v2_min_final_score": 55,
      "min_formula_score": 0.56,
      "role": "v2_live_meta_adaptive_brain",
      "sl_stake_pct": 0.0024,
      "market_cooldown_min": 0.35,
      "spread_policy": "evrim_adaptive",
      "evrim_v2_aggressive_min": 78,
      "evrim_v2_daily_2x_mult": 2.0,
      "scan_interval_sec": 0.8,
      "trade_top_n": 150,
      "entry_block_weak": false,
      "evrim_v2_exploration_idle_min": 20,
      "entry_max_open": 10,
      "entry_skip_cautious": false,
      "starting_balance": 5000,
      "evrim_min_total_score": 50,
      "evrim_v2_config_auto_apply": false,
      "evrim_v2_slippage_tp_veto_frac": 0.5
    },
    "active_hash": "98baff91f6a7",
    "candidate_config_version": "evrim_cfg_candidate_20260523_230108_77268",
    "candidate_snapshot": {
      "evrim_v2_fee_gross_caution": 0.45,
      "min_stake_usd": 180,
      "max_open": 10,
      "active_capital_pct": 0.6,
      "evrim_v2_hourly_target_pct": 4.0,
      "same_symbol_max_open": 1,
      "evrim_max_tier": "aggressive",
      "min_edge": 0.08,
      "evrim_v2_high_conviction_min": 88,
      "learning_access": "all_modes_summary_read",
      "tp_stake_pct": 0.0042,
      "evrim_v2_fee_gross_recovery": 0.75,
      "evrim_v2_half_risk_drawdown_pct": 8,
      "evrim_v2_spread_tp_veto_frac": 0.65,
      "tp_trigger_frac": 1.0,
      "entry_stake_mult": 1.0,
      "evrim_v2_max_daily_drawdown_pct": 12,
      "trading_style": "adaptive_multi_mode_meta_trader",
      "position_check_sec": 0.15,
      "evrim_v2_min_final_score": 55,
      "min_formula_score": 0.56,
      "role": "v2_live_meta_adaptive_brain",
      "sl_stake_pct": 0.0024,
      "market_cooldown_min": 0.35,
      "spread_policy": "evrim_adaptive",
      "evrim_v2_aggressive_min": 78,
      "evrim_v2_daily_2x_mult": 2.0,
      "scan_interval_sec": 0.8,
      "trade_top_n": 150,
      "entry_block_weak": false,
      "evrim_v2_exploration_idle_min": 20,
      "entry_max_open": 10,
      "entry_skip_cautious": false,
      "starting_balance": 5000,
      "evrim_min_total_score": 52,
      "evrim_v2_config_auto_apply": false,
      "evrim_v2_slippage_tp_veto_frac": 0.5,
      "evrim_pa_fake_veto_threshold": 0.72,
      "evrim_vo_spread_veto_pct": 0.12,
      "regime_overrides": {
        "chop": {
          "min_score_delta": 5,
          "stake_mult": 0.5
        }
      },
      "dynamic_exit_overrides": {
        "tp_mult": 0.92,
        "sl_mult": 1.05
      },
      "expectancy_overrides": {
        "stake_mult": 0.7,
        "min_score_delta": 2
      }
    },
    "candidate_status": "pending",
    "pending_approval": true,
    "candidate_meta": {
      "source": "maybe_tune",
      "task_type": "maybe_tune",
      "risk_change": "",
      "expected_improvement": "",
      "source_modes": [
        "berserk",
        "hunter",
        "chop_master",
        "sentinel"
      ],
      "approval_required": false,
      "backtest_passed": null,
      "created_at": "2026-05-23T23:01:08.313688+00:00"
    },
    "updated_at": "2026-05-23T23:01:08.313703+00:00"
  },
  "evrim_persistent_learning": {
    "version": 1,
    "created_at": "2026-05-23T21:49:45.522099+00:00",
    "updated_at": "2026-05-23T23:02:50.372294+00:00",
    "learning_level": 1,
    "peak_level": 1,
    "total_xp": 10,
    "stats": {
      "evrim_signals": 6,
      "evrim_rejects": 6,
      "evrim_entries": 0,
      "mode_decisions": 36,
      "analysis_cycles": 3
    },
    "reject_reasons": {
      "not in universe": 6
    },
    "mode_stats": {
      "berserk": {
        "allowed": 0,
        "rejected": 9,
        "reasons": {
          "berserk_score_low": 4,
          "edge": 5
        },
        "data_status": "normal_trade",
        "evrim_zero_data_guard": false
      },
      "evrim": {
        "allowed": 0,
        "rejected": 6,
        "reasons": {
          "not in universe": 6
        }
      },
      "hunter": {
        "allowed": 0,
        "rejected": 9,
        "reasons": {
          "HYPEUSDT: 1 SL-EMERGENCY / 72sa": 2,
          "spike_await_confirmation": 7
        },
        "data_status": "normal_trade",
        "evrim_zero_data_guard": false
      },
      "chop_master": {
        "allowed": 0,
        "rejected": 8,
        "reasons": {
          "edge": 7,
          "chop_explore_chop_score_low": 1
        },
        "data_status": "exploration_trade",
        "evrim_zero_data_guard": false
      },
      "sentinel": {
        "allowed": 0,
        "rejected": 4,
        "reasons": {
          "edge": 4
        },
        "data_status": "exploration_trade",
        "evrim_zero_data_guard": false
      }
    },
    "recent_rejects": [
      {
        "ts": "2026-05-23T21:49:45.638159+00:00",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "reason": "not in universe",
        "execution_path": "live",
        "change": -0.07616146230007306,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      },
      {
        "ts": "2026-05-23T21:49:45.763345+00:00",
        "symbol": "ALGOUSDT",
        "side": "SHORT",
        "reason": "not in universe",
        "execution_path": "live",
        "change": -0.07525649082900752,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      },
      {
        "ts": "2026-05-23T21:49:46.057485+00:00",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "reason": "not in universe",
        "execution_path": "live",
        "change": -0.07616146230007306,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      },
      {
        "ts": "2026-05-23T21:49:46.195060+00:00",
        "symbol": "1000LUNCUSDT",
        "side": "SHORT",
        "reason": "not in universe",
        "execution_path": "live",
        "change": -0.07384615384615938,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      },
      {
        "ts": "2026-05-23T21:49:46.839256+00:00",
        "symbol": "ATUSDT",
        "side": "SHORT",
        "reason": "not in universe",
        "execution_path": "live",
        "change": -0.1484655216330398,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      },
      {
        "ts": "2026-05-23T21:49:46.981213+00:00",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "reason": "not in universe",
        "execution_path": "live",
        "change": 0.1452257049497744,
        "strength": "Weak",
        "formula_score": null,
        "edge": null,
        "market_regime": null,
        "final_score": null,
        "meta_tier": null,
        "total_score": null,
        "tier": null,
        "reason_skip": null
      }
    ],
    "recent_cross": [
      {
        "ts": "2026-05-23T21:49:45.623382+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "berserk_score_low",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.638151+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.675697+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "HYPEUSDT: 1 SL-EMERGENCY / 72sa",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.728773+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.763338+00:00",
        "batch_key": "ALGOUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "ALGOUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.805206+00:00",
        "batch_key": "GMTUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "GMTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "berserk_score_low",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.832849+00:00",
        "batch_key": "GMTUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "GMTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.861706+00:00",
        "batch_key": "GMTUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "GMTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.875669+00:00",
        "batch_key": "GMTUSDT:118638199",
        "mode_id": "sentinel",
        "symbol": "GMTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.925100+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:45.981172+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.004407+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.018314+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "sentinel",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.057478+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.195053+00:00",
        "batch_key": "1000LUNCUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "1000LUNCUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.231757+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.278882+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.320191+00:00",
        "batch_key": "CGPTUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "CGPTUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.408663+00:00",
        "batch_key": "1000LUNCUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "1000LUNCUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.454584+00:00",
        "batch_key": "1000LUNCUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "1000LUNCUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.480828+00:00",
        "batch_key": "1000LUNCUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "1000LUNCUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.544485+00:00",
        "batch_key": "BOMEUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "BOMEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.614360+00:00",
        "batch_key": "BOMEUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "BOMEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.671775+00:00",
        "batch_key": "BOMEUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "BOMEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.721935+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.748190+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "HYPEUSDT: 1 SL-EMERGENCY / 72sa",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.768387+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.783100+00:00",
        "batch_key": "HYPEUSDT:118638199",
        "mode_id": "sentinel",
        "symbol": "HYPEUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.839249+00:00",
        "batch_key": "ATUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "ATUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:46.981206+00:00",
        "batch_key": "ALTUSDT:118638199",
        "mode_id": "evrim",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "not in universe",
        "execution_path": "live",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.031423+00:00",
        "batch_key": "ATUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "ATUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "berserk_score_low",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.110796+00:00",
        "batch_key": "ATUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "ATUSDT",
        "side": "SHORT",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.141303+00:00",
        "batch_key": "ALTUSDT:118638199",
        "mode_id": "berserk",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "berserk_score_low",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.218085+00:00",
        "batch_key": "ALTUSDT:118638199",
        "mode_id": "hunter",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "spike_await_confirmation",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.253709+00:00",
        "batch_key": "ALTUSDT:118638199",
        "mode_id": "chop_master",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "chop_explore_chop_score_low",
        "execution_path": "paper",
        "regime": null,
        "score": null
      },
      {
        "ts": "2026-05-23T21:49:47.268173+00:00",
        "batch_key": "ALTUSDT:118638199",
        "mode_id": "sentinel",
        "symbol": "ALTUSDT",
        "side": "LONG",
        "allowed": false,
        "reason": "edge",
        "execution_path": "paper",
        "regime": null,
        "score": null
      }
    ],
    "cross_insights": {
      "regime_best_mode": {},
      "evrim_miss_vs_other": [],
      "strategy_notes": [
        "2026-05-23T22:01:44 backtest WR=44.7% PF=None"
      ]
    },
    "strategy_hints": {
      "score_boost_by_regime": {},
      "favor_symbols": [
        "SLERFUSDT",
        "GUAUSDT",
        "NILUSDT",
        "TRUUSDT",
        "GMTUSDT",
        "PLAYUSDT",
        "BOBUSDT",
        "BICOUSDT"
      ],
      "caution_symbols": [
        "42USDT",
        "1000XUSDT",
        "NTRNUSDT",
        "DMCUSDT",
        "HIPPOUSDT",
        "RDNTUSDT",
        "CHESSUSDT",
        "FIOUSDT",
        "PHBUSDT",
        "1000WHYUSDT",
        "FISUSDT",
        "PORT3USDT",
        "YALAUSDT",
        "FXSUSDT",
        "FORTHUSDT"
      ],
      "learned_min_score_delta": 0
    },
    "backtest_memory": {
      "last_at": "2026-05-23T22:01:44.985541+00:00",
      "win_rate_pct": 44.7,
      "profit_factor": null,
      "dominant_regime": "high_volatility",
      "regime_wr": {
        "chop": 0.0,
        "breakout": 38.7,
        "high_volatility": 45.4,
        "low_volatility": 0.0,
        "trending": 38.9,
        "fake_pump_dump": 0.0
      },
      "param_validation": {
        "at": "2026-05-23T22:01:44.971705+00:00",
        "backup_path": "/Users/macbook/Desktop/binancex/predmarket-scanner/data/backups/evrim_profile_20260523_220000.json",
        "patch": {
          "min_edge": 0.1,
          "evrim_min_total_score": 51,
          "tp_stake_pct": 0.00441,
          "sl_stake_pct": 0.00228,
          "max_open": 9
        },
        "baseline_journal_n": 500,
        "baseline": {
          "trade_count": 500,
          "net_pnl": -456.0975,
          "max_drawdown": 456.0975,
          "fee_ratio_pct": 100.0,
          "profit_factor": 0.0,
          "avg_win": 0.0,
          "avg_loss": -0.9122,
          "pnl_velocity": -10.9463,
          "consecutive_loss_max": 500,
          "liquidation_risk": -3.258,
          "slippage_efficiency": -45609.75,
          "avg_slippage_bps": 0.0,
          "win_rate_pct": 0.0
        },
        "candidate": {
          "trade_count": 860,
          "net_pnl": -707.4656,
          "max_drawdown": 707.4656,
          "fee_ratio_pct": 50.0,
          "profit_factor": 0.0,
          "avg_win": 0.0,
          "avg_loss": -0.4113,
          "pnl_velocity": -7.9927,
          "consecutive_loss_max": 860,
          "liquidation_risk": 0.0,
          "slippage_efficiency": -1070.469,
          "avg_slippage_bps": 4.59,
          "win_rate_pct": 0.0
        },
        "comparison": {
          "passed": false,
          "checks": [
            {
              "name": "net_pnl_better",
              "ok": false,
              "detail": "candidate $-707.47 vs baseline $-456.10"
            },
            {
              "name": "drawdown_not_worse",
              "ok": false,
              "detail": "candidate DD $707.47 vs baseline $456.10"
            },
            {
              "name": "fee_ratio_ok",
              "ok": true,
              "detail": "candidate fee/gross 50.0% (max 72.0%)"
            },
            {
              "name": "profit_factor_min",
              "ok": false,
              "detail": "PF=0.00 need >=1.15"
            },
            {
              "name": "slippage_controlled",
              "ok": false,
              "detail": "slip_eff -1070.47 vs -45609.75"
            }
          ],
          "baseline": {
            "trade_count": 500,
            "net_pnl": -456.0975,
            "max_drawdown": 456.0975,
            "fee_ratio_pct": 100.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": -0.9122,
            "pnl_velocity": -10.9463,
            "consecutive_loss_max": 500,
            "liquidation_risk": -3.258,
            "slippage_efficiency": -45609.75,
            "avg_slippage_bps": 0.0,
            "win_rate_pct": 0.0
          },
          "candidate": {
            "trade_count": 860,
            "net_pnl": -707.4656,
            "max_drawdown": 707.4656,
            "fee_ratio_pct": 50.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": -0.4113,
            "pnl_velocity": -7.9927,
            "consecutive_loss_max": 860,
            "liquidation_risk": 0.0,
            "slippage_efficiency": -1070.469,
            "avg_slippage_bps": 4.59,
            "win_rate_pct": 0.0
          },
          "delta": {
            "net_pnl": -251.3681,
            "max_drawdown": 251.3681,
            "fee_ratio_pct": -50.0,
            "profit_factor": 0.0,
            "trade_count": 360.0,
            "pnl_velocity": 2.9536
          }
        },
        "backtest_block": {
          "ok": true,
          "wr": 41.0,
          "trades": 860
        },
        "forward_block": {
          "ok": true,
          "minutes": 30,
          "trades": 0
        },
        "accepted": false
      },
      "learning_analysis": {
        "trades_n": 50,
        "win_rate_pct": 0.0,
        "profitable_signals": [],
        "losing_signals": [
          "price_action",
          "volatility_atr",
          "trend_ema"
        ],
        "best_symbols": [
          [
            "OPUSDT",
            -52.06069999999997
          ]
        ],
        "worst_symbols": [
          [
            "OPUSDT",
            -52.06069999999997
          ]
        ],
        "best_hours": [
          [
            "?",
            -52.06069999999997
          ]
        ],
        "worst_hours": [
          [
            "?",
            -52.06069999999997
          ]
        ],
        "regime_pnl": {
          "high_volatility": -52.06069999999997
        },
        "harmful_regimes": [
          "high_volatility"
        ],
        "tp_sl_ratio": 0.52,
        "tp_sl_ok": false,
        "edge_threshold_low": false,
        "avg_edge_win": 0,
        "avg_edge_loss": 0.0,
        "net_pnl_sum": -52.06
      }
    },
    "last_report": {
      "learning_level": 1,
      "peak_level": 1,
      "level_title": "Çırak",
      "total_xp": 10,
      "level_never_decreases": true,
      "stats": {
        "evrim_signals": 6,
        "evrim_rejects": 6,
        "evrim_entries": 0,
        "mode_decisions": 36,
        "analysis_cycles": 3
      },
      "top_reject_reasons": [
        {
          "reason": "not in universe",
          "count": 6
        }
      ],
      "recent_rejects": [
        {
          "ts": "2026-05-23T21:49:46.981213+00:00",
          "symbol": "ALTUSDT",
          "side": "LONG",
          "reason": "not in universe",
          "execution_path": "live",
          "change": 0.1452257049497744,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        },
        {
          "ts": "2026-05-23T21:49:46.839256+00:00",
          "symbol": "ATUSDT",
          "side": "SHORT",
          "reason": "not in universe",
          "execution_path": "live",
          "change": -0.1484655216330398,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        },
        {
          "ts": "2026-05-23T21:49:46.195060+00:00",
          "symbol": "1000LUNCUSDT",
          "side": "SHORT",
          "reason": "not in universe",
          "execution_path": "live",
          "change": -0.07384615384615938,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        },
        {
          "ts": "2026-05-23T21:49:46.057485+00:00",
          "symbol": "CGPTUSDT",
          "side": "SHORT",
          "reason": "not in universe",
          "execution_path": "live",
          "change": -0.07616146230007306,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        },
        {
          "ts": "2026-05-23T21:49:45.763345+00:00",
          "symbol": "ALGOUSDT",
          "side": "SHORT",
          "reason": "not in universe",
          "execution_path": "live",
          "change": -0.07525649082900752,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        },
        {
          "ts": "2026-05-23T21:49:45.638159+00:00",
          "symbol": "CGPTUSDT",
          "side": "SHORT",
          "reason": "not in universe",
          "execution_path": "live",
          "change": -0.07616146230007306,
          "strength": "Weak",
          "formula_score": null,
          "edge": null,
          "market_regime": null,
          "final_score": null,
          "meta_tier": null,
          "total_score": null,
          "tier": null,
          "reason_skip": null
        }
      ],
      "cross_mode_stats": {
        "berserk": {
          "allowed": 0,
          "rejected": 9,
          "reasons": {
            "berserk_score_low": 4,
            "edge": 5
          },
          "data_status": "normal_trade",
          "evrim_zero_data_guard": false
        },
        "evrim": {
          "allowed": 0,
          "rejected": 6,
          "reasons": {
            "not in universe": 6
          }
        },
        "hunter": {
          "allowed": 0,
          "rejected": 9,
          "reasons": {
            "HYPEUSDT: 1 SL-EMERGENCY / 72sa": 2,
            "spike_await_confirmation": 7
          },
          "data_status": "normal_trade",
          "evrim_zero_data_guard": false
        },
        "chop_master": {
          "allowed": 0,
          "rejected": 8,
          "reasons": {
            "edge": 7,
            "chop_explore_chop_score_low": 1
          },
          "data_status": "exploration_trade",
          "evrim_zero_data_guard": false
        },
        "sentinel": {
          "allowed": 0,
          "rejected": 4,
          "reasons": {
            "edge": 4
          },
          "data_status": "exploration_trade",
          "evrim_zero_data_guard": false
        }
      },
      "regime_best_mode": {},
      "evrim_miss_vs_other": [],
      "strategy_notes": [
        "2026-05-23T22:01:44 backtest WR=44.7% PF=None"
      ],
      "strategy_hints": {
        "score_boost_by_regime": {},
        "favor_symbols": [
          "SLERFUSDT",
          "GUAUSDT",
          "NILUSDT",
          "TRUUSDT",
          "GMTUSDT",
          "PLAYUSDT",
          "BOBUSDT",
          "BICOUSDT"
        ],
        "caution_symbols": [
          "42USDT",
          "1000XUSDT",
          "NTRNUSDT",
          "DMCUSDT",
          "HIPPOUSDT",
          "RDNTUSDT",
          "CHESSUSDT",
          "FIOUSDT",
          "PHBUSDT",
          "1000WHYUSDT",
          "FISUSDT",
          "PORT3USDT",
          "YALAUSDT",
          "FXSUSDT",
          "FORTHUSDT"
        ],
        "learned_min_score_delta": 0
      },
      "backtest_memory": {
        "last_at": "2026-05-23T22:01:44.985541+00:00",
        "win_rate_pct": 44.7,
        "profit_factor": null,
        "dominant_regime": "high_volatility",
        "regime_wr": {
          "chop": 0.0,
          "breakout": 38.7,
          "high_volatility": 45.4,
          "low_volatility": 0.0,
          "trending": 38.9,
          "fake_pump_dump": 0.0
        },
        "param_validation": {
          "at": "2026-05-23T22:01:44.971705+00:00",
          "backup_path": "/Users/macbook/Desktop/binancex/predmarket-scanner/data/backups/evrim_profile_20260523_220000.json",
          "patch": {
            "min_edge": 0.1,
            "evrim_min_total_score": 51,
            "tp_stake_pct": 0.00441,
            "sl_stake_pct": 0.00228,
            "max_open": 9
          },
          "baseline_journal_n": 500,
          "baseline": {
            "trade_count": 500,
            "net_pnl": -456.0975,
            "max_drawdown": 456.0975,
            "fee_ratio_pct": 100.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": -0.9122,
            "pnl_velocity": -10.9463,
            "consecutive_loss_max": 500,
            "liquidation_risk": -3.258,
            "slippage_efficiency": -45609.75,
            "avg_slippage_bps": 0.0,
            "win_rate_pct": 0.0
          },
          "candidate": {
            "trade_count": 860,
            "net_pnl": -707.4656,
            "max_drawdown": 707.4656,
            "fee_ratio_pct": 50.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": -0.4113,
            "pnl_velocity": -7.9927,
            "consecutive_loss_max": 860,
            "liquidation_risk": 0.0,
            "slippage_efficiency": -1070.469,
            "avg_slippage_bps": 4.59,
            "win_rate_pct": 0.0
          },
          "comparison": {
            "passed": false,
            "checks": [
              {
                "name": "net_pnl_better",
                "ok": false,
                "detail": "candidate $-707.47 vs baseline $-456.10"
              },
              {
                "name": "drawdown_not_worse",
                "ok": false,
                "detail": "candidate DD $707.47 vs baseline $456.10"
              },
              {
                "name": "fee_ratio_ok",
                "ok": true,
                "detail": "candidate fee/gross 50.0% (max 72.0%)"
              },
              {
                "name": "profit_factor_min",
                "ok": false,
                "detail": "PF=0.00 need >=1.15"
              },
              {
                "name": "slippage_controlled",
                "ok": false,
                "detail": "slip_eff -1070.47 vs -45609.75"
              }
            ],
            "baseline": {
              "trade_count": 500,
              "net_pnl": -456.0975,
              "max_drawdown": 456.0975,
              "fee_ratio_pct": 100.0,
              "profit_factor": 0.0,
              "avg_win": 0.0,
              "avg_loss": -0.9122,
              "pnl_velocity": -10.9463,
              "consecutive_loss_max": 500,
              "liquidation_risk": -3.258,
              "slippage_efficiency": -45609.75,
              "avg_slippage_bps": 0.0,
              "win_rate_pct": 0.0
            },
            "candidate": {
              "trade_count": 860,
              "net_pnl": -707.4656,
              "max_drawdown": 707.4656,
              "fee_ratio_pct": 50.0,
              "profit_factor": 0.0,
              "avg_win": 0.0,
              "avg_loss": -0.4113,
              "pnl_velocity": -7.992
```
