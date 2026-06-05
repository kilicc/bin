"""5 mod profilleri — JSON; canlı .env değişmez."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.mode_registry import (
    MODE_IDS,
    resolve_mode_id,
)

_ROOT = Path(__file__).resolve().parent.parent
_PROFILES_PATH = _ROOT / "data" / "mode_profiles.json"

_BUILTIN_MODES: dict[str, dict[str, Any]] = {
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
        "spike_enabled": True,
        "spike_min_age_sec": 7,
        "spike_fee_mult": 1.12,
        "spike_max_tp_frac": 0.82,
        "stale_enabled": True,
        "stale_min_age_min": 0.20,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 180,
        "active_capital_pct": 0.60,
        "max_open": 10,
        "same_symbol_max_open": 1,
        "entry_max_open": 10,
        "default_paper": False,
        "can_trade_live": True,
        "scan_interval_sec": 0.8,
        "position_check_sec": 0.15,
        "trade_top_n": 150,
        "sl_em_veto_count": 1,
        "sl_em_cooldown_min": 15,
        "min_hold_before_sl_sec": 8,
        "sl_emergency_mult": 1.12,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.0,
        "entry_skip_cautious": False,
        "entry_block_weak": False,
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
        "evrim_v2_slippage_tp_veto_frac": 0.50,
        "evrim_v2_exploration_idle_min": 20,
        "evrim_v2_config_auto_apply": False,
        "evrim_min_total_score": 52,
        "evrim_max_tier": "aggressive",
        "evrim_live_training": True,
        "evrim_unified_engine_enabled": True,
        "evrim_trading_mode": "demo",
        "evrim_live_trading_enabled": False,
        "evrim_news_shock_sec": 90,
        "evrim_chop_trade_enabled": True,
        "evrim_spread_hard_veto_tp_frac": 0.55,
        "evrim_radar_hard_veto_only_extreme": True,
        "evrim_fee_hard_block": False,
        "evrim_flow_recovery_enabled": True,
        "evrim_expectancy_min_net_usd": 0.01,
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
        "spike_enabled": True,
        "spike_min_age_sec": 4,
        "spike_fee_mult": 1.08,
        "spike_max_tp_frac": 0.88,
        "stale_enabled": True,
        "stale_min_age_min": 0.15,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 120,
        "active_capital_pct": 0.70,
        "max_open": 14,
        "entry_max_open": 14,
        "scan_interval_sec": 0.35,
        "position_check_sec": 0.06,
        "trade_top_n": 220,
        "sl_em_veto_count": 0,
        "sl_em_cooldown_min": 4,
        "min_hold_before_sl_sec": 8,
        "berserk_tp_grace_sec": 25.0,
        "berserk_spike_grace_min_age_sec": 2.0,
        "berserk_spike_grace_max_tp_frac": 0.52,
        "berserk_sl_to_tp_enabled": True,
        "berserk_sl_recover_sec": 90.0,
        "berserk_sl_catastrophic_stake_pct": 0.08,
        "berserk_sl_hard_mult": 8.0,
        "berserk_sl_min_age_sec": 120.0,
        "berserk_sl_soft_stake_pct": 0.025,
        "berserk_sl_peak_extend_age_sec": 90.0,
        "berserk_stale_dip_min_age_sec": 50.0,
        "berserk_sl_cliff_preempt_sec": 18.0,
        "berserk_spike_min_net_fee_mult": 1.22,
        "berserk_stale_min_age_sec": 45.0,
        "berserk_stale_peak_hold_sec": 60.0,
        "berserk_sl_recover_min_age_sec": 10.0,
        "berserk_sl_recover_dip_frac": 0.50,
        "berserk_sl_recover_fee_mult": 1.05,
        "berserk_sl_peak_hold_min_usd": 0.06,
        "berserk_sl_peak_hold_sec": 45.0,
        "berserk_sl_peak_hard_mult": 2.8,
        "berserk_peak_spike_min_tp_frac": 0.08,
        "berserk_peak_spike_pullback_frac": 0.55,
        "berserk_peak_spike_loss_fee_mult": 1.5,
        "sl_emergency_mult": 1.25,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.05,
        "entry_skip_cautious": False,
        "entry_block_weak": False,
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
        "live_permission": "conditional_if_active_futures_mode",
    },
    "berserk2": {
        "label": "Berserk2",
        "short_label": "Brk2",
        "description": "Top-20 hızlı TP scalp — her tick 20 coin sinyal, berserk'ten bağımsız ölçek.",
        "role": "v2_top20_mover_btc_aware_scalp",
        "trading_style": "focused_top20_micro_scalp",
        "learning_access": "own_data_only",
        "spread_policy": "dynamic_micro",
        "max_spread_pct": 0.075,
        "berserk2_max_spread_pct": 0.075,
        "soft_spread_start_pct": 0.035,
        "min_edge": 0.018,
        "min_formula_score": 0.38,
        "berserk2_skip_edge_formula": True,
        "berserk2_skip_risk_gate": True,
        "market_cooldown_min": 4.0,
        "tp_stake_pct": 0.0048,
        "sl_stake_pct": 0.0020,
        "tp_trigger_frac": 0.99,
        "berserk2_tp_stake_pct": 0.0048,
        "berserk2_sl_stake_pct": 0.0020,
        "berserk2_net_tp_usd": 0.50,
        "berserk2_spike_quick_gross_usd": 0.0,
        "no_loss_close": True,
        "berserk2_sl_enabled": False,
        "spike_enabled": True,
        "spike_min_age_sec": 0.12,
        "berserk2_spike_min_age_sec": 0.12,
        "spike_fee_mult": 1.04,
        "spike_max_tp_frac": 0.42,
        "exit_slippage_buffer_usd": 0.04,
        "exit_slippage_buffer_pct": 0.08,
        "stale_enabled": False,
        "exit_tp_only": True,
        "stale_min_age_min": 0.10,
        "stale_mode": "flat_release",
        "starting_balance": 30000,
        "min_stake_usd": 3000,
        "max_stake_usd": 3000,
        "active_capital_pct": 0.38,
        "max_open": 10,
        "entry_max_open": 10,
        "scan_interval_sec": 0.22,
        "position_check_sec": 0.02,
        "trade_top_n": 20,
        "berserk2_top_n": 12,
        "berserk2_chop_score_boost": 0,
        "berserk2_min_volume_usdt": 2000000,
        "berserk2_btc_soft_veto": True,
        "berserk2_min_score": 28,
        "berserk2_min_move_pct": 0.010,
        "berserk2_pulse_min_score": 22,
        "berserk2_skip_weak_volume": True,
        "berserk2_min_expected_net_usd": 0.15,
        "berserk2_tp_fee_mult": 1.08,
        "exit_min_net_usd": 0.40,
        "berserk2_min_final_net_usd": 0.40,
        "entry_min_net_usd": 0.15,
        "entry_require_net_tp": True,
        "berserk2_entry_min_net_usd": 0.15,
        "exit_require_net_positive": True,
        "berserk2_fast_scan_enabled": True,
        "berserk2_flash_reversal_enabled": True,
        "berserk2_flash_drop_min_pct": 0.15,
        "berserk2_flash_bounce_min_pct": 0.03,
        "berserk2_flash_recovery_min_frac": 0.06,
        "berserk2_flash_recovery_max_frac": 0.42,
        "berserk2_flash_tp_recovery_frac": 0.72,
        "berserk2_flash_tp_floor_mult": 1.35,
        "sl_em_veto_count": 0,
        "sl_em_cooldown_min": 2,
        "min_hold_before_sl_sec": 5,
        "berserk_tp_grace_sec": 2.0,
        "berserk2_tp_grace_sec": 2.0,
        "berserk_spike_grace_min_age_sec": 0.12,
        "berserk_spike_grace_max_tp_frac": 0.28,
        "berserk_sl_to_tp_enabled": True,
        "berserk_sl_recover_sec": 75.0,
        "berserk_sl_catastrophic_stake_pct": 0.08,
        "berserk_sl_hard_mult": 8.0,
        "berserk_sl_min_age_sec": 100.0,
        "berserk_sl_soft_stake_pct": 0.025,
        "berserk_sl_peak_extend_age_sec": 80.0,
        "berserk_stale_dip_min_age_sec": 120.0,
        "berserk2_stale_dip_enabled": False,
        "berserk_sl_cliff_preempt_sec": 16.0,
        "berserk_spike_min_net_fee_mult": 1.05,
        "berserk_stale_min_age_sec": 40.0,
        "berserk_stale_peak_hold_sec": 55.0,
        "berserk_sl_recover_min_age_sec": 8.0,
        "berserk_sl_recover_dip_frac": 0.50,
        "berserk_sl_recover_fee_mult": 1.05,
        "berserk_sl_peak_hold_min_usd": 0.04,
        "berserk_sl_peak_hold_sec": 25.0,
        "berserk_sl_peak_hard_mult": 2.8,
        "berserk_peak_spike_min_tp_frac": 0.04,
        "berserk_peak_spike_pullback_frac": 0.88,
        "berserk_instant_scalp_mult": 1.03,
        "berserk_instant_scalp_min_age_sec": 0.12,
        "berserk_instant_scalp_peak_frac": 0.94,
        "berserk_peak_spike_loss_fee_mult": 0.0,
        "sl_emergency_mult": 1.22,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.08,
        "entry_skip_cautious": False,
        "entry_block_weak": False,
        "berserk_min_move_pct": 0.03,
        "berserk_min_score": 26,
        "berserk_normal_score": 48,
        "berserk_aggressive_score": 62,
        "berserk_recovery_fee_gross_pct": 0.75,
        "berserk_reentry_max_failures": 3,
        "berserk_reentry_ban_min": 2.5,
        "weak_stake_multiplier": 0.48,
        "medium_stake_multiplier": 0.78,
        "strong_stake_multiplier": 1.0,
        "paper_fee_side": 0.0004,
        "same_symbol_max_open": 3,
        "live_permission": "conditional_if_active_futures_mode",
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
        "min_edge": 0.065,
        "min_formula_score": 0.52,
        "market_cooldown_min": 0.8,
        "tp_stake_pct": 0.0095,
        "sl_stake_pct": 0.0042,
        "tp_trigger_frac": 1.00,
        "spike_enabled": True,
        "spike_min_age_sec": 8,
        "spike_fee_mult": 1.18,
        "spike_max_tp_frac": 0.72,
        "stale_enabled": True,
        "stale_min_age_min": 0.8,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 160,
        "active_capital_pct": 0.50,
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
        "entry_skip_cautious": False,
        "entry_block_weak": False,
        "hunter_min_spike_change_pct": 0.14,
        "hunter_min_spike_vol_ratio": 1.12,
        "hunter_breakout_change_pct": 0.18,
        "hunter_breakout_vol_ratio": 1.20,
        "hunter_liquidation_proxy_min": 0.22,
        "hunter_spike_min_confirmation_sec": 2,
        "hunter_spike_max_confirmation_sec": 8,
        "hunter_min_breakout_score": 38,
        "hunter_strong_breakout_score": 62,
        "hunter_explosive_score": 78,
        "hunter_chop_trade_enabled": False,
        "same_symbol_max_open": 1,
        "evrim_min_total_score": 62,
        "evrim_chop_trade_enabled": False,
        "minimum_data_mode_enabled": True,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": True,
        "minimum_data_never_live": True,
        "hunter_explore_breakout_score_min": 50,
        "hunter_explore_fake_risk_max": 78,
        "hunter_explore_stake_mult": 0.35,
        "hunter_explore_max_open": 2,
        "hunter_explore_cooldown_min": 2.0,
        "hunter_explore_only_paper": True,
        "hunter_explore_learning_tag": "hunter_exploration_breakout_test",
    },
    "mega": {
        "label": "Mega",
        "short_label": "Mega",
        "description": "Volatilite scalp — SL yok; $500–$1500 stake; 5x–10x; hızlı yüksek TP.",
        "role": "v2_volatility_scalp_live",
        "trading_style": "volatility_relative_scalp",
        "learning_access": "own_data_only",
        "spread_policy": "hunter_medium_penalty",
        "max_spread_pct": 0.16,
        "soft_spread_start_pct": 0.07,
        "min_edge": 0.04,
        "min_formula_score": 0.48,
        "mega_skip_edge_formula": True,
        "mega_skip_risk_gate": True,
        "market_cooldown_min": 1.5,
        "tp_stake_pct": 0.04,
        "sl_stake_pct": 0.0,
        "tp_trigger_frac": 0.98,
        "exit_tp_only": True,
        "no_loss_close": True,
        "stale_enabled": False,
        "spike_enabled": True,
        "spike_min_age_sec": 1.5,
        "spike_fee_mult": 1.08,
        "spike_max_tp_frac": 0.92,
        "starting_balance": 5000,
        "min_stake_usd": 500,
        "max_stake_usd": 1500,
        "active_capital_pct": 0.68,
        "max_open": 4,
        "entry_max_open": 4,
        "same_symbol_max_open": 1,
        "scan_interval_sec": 0.9,
        "position_check_sec": 0.08,
        "trade_top_n": 40,
        "sl_em_veto_count": 0,
        "sl_em_cooldown_min": 0,
        "min_hold_before_sl_sec": 99999,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 1.0,
        "entry_skip_cautious": False,
        "entry_block_weak": False,
        "mega_min_move_pct": 0.022,
        "mega_top_mover_min_move_pct": 0.012,
        "mega_min_score": 32,
        "mega_medium_score": 52,
        "mega_strong_score": 68,
        "mega_weak_score": 44,
        "mega_min_spike_change_pct": 0.025,
        "mega_min_vol_ratio": 1.02,
        "mega_require_top_mover": False,
        "mega_leverage_weak": 5,
        "mega_leverage_medium": 7,
        "mega_leverage_strong": 10,
        "exit_min_net_usd": 10.0,
        "entry_min_net_usd": 1.5,
        "exit_require_net_positive": True,
        "default_paper": True,
        "can_trade_live": False,
        "paper_fee_side": 0.0004,
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
        "chop_min_score_trade": 48,
        "chop_observation_min": 38,
        "chop_strong_score": 80,
        "chop_mr_min_score": 65,
        "chop_min_range_width_mult": 3.0,
        "chop_min_expected_move_mult": 1.4,
        "chop_hunter_breakout_veto": 70,
        "min_edge": 0.055,
        "min_formula_score": 0.50,
        "market_cooldown_min": 0.4,
        "tp_stake_pct": 0.0028,
        "sl_stake_pct": 0.0018,
        "tp_trigger_frac": 0.99,
        "spike_enabled": False,
        "spike_min_age_sec": 20,
        "spike_fee_mult": 1.05,
        "spike_max_tp_frac": 0.60,
        "stale_enabled": True,
        "stale_min_age_min": 0.15,
        "stale_mode": "flat_release",
        "starting_balance": 5000,
        "min_stake_usd": 120,
        "active_capital_pct": 0.40,
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
        "entry_skip_cautious": False,
        "entry_block_weak": False,
        "default_paper": True,
        "can_trade_live": True,
        "evrim_min_total_score": 52,
        "evrim_chop_trade_enabled": True,
        "evrim_chop_stake_mult": 0.35,
        "evrim_chop_max_open": 4,
        "minimum_data_mode_enabled": True,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": True,
        "minimum_data_never_live": True,
        "chop_explore_chop_score_min": 54,
        "chop_explore_observation_min": 48,
        "chop_explore_range_cost_mult": 2.5,
        "chop_explore_stake_mult": 0.30,
        "chop_explore_max_open": 2,
        "chop_explore_cooldown_min": 2.5,
        "chop_explore_only_paper": True,
        "chop_explore_learning_tag": "chop_exploration_mean_reversion_test",
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
        "min_edge": 0.072,
        "min_formula_score": 0.48,
        "market_cooldown_min": 3.0,
        "tp_stake_pct": 0.0095,
        "sl_stake_pct": 0.0042,
        "tp_trigger_frac": 1.02,
        "spike_enabled": True,
        "spike_min_age_sec": 25,
        "spike_fee_mult": 1.25,
        "spike_max_tp_frac": 0.60,
        "stale_enabled": True,
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
        "sl_emergency_mult": 0.90,
        "entry_min_strength": "Weak",
        "entry_stake_mult": 0.9,
        "entry_skip_cautious": False,
        "entry_block_weak": False,
        "medium_stake_multiplier": 0.60,
        "strong_stake_multiplier": 1.00,
        "same_symbol_max_open": 1,
        "default_paper": True,
        "can_trade_live": True,
        "sentinel_min_quality_score": 46,
        "sentinel_min_formula_score_engine": 0.50,
        "sentinel_chop_min_quality_score": 72,
        "sentinel_chop_premium_min_score": 85,
        "sentinel_allow_medium_if_quality": True,
        "sentinel_news_risk_mode": "risk_off",
        "sentinel_trend_misalignment_mode": "veto",
        "evrim_min_total_score": 68,
        "evrim_chop_trade_enabled": False,
        "minimum_data_mode_enabled": True,
        "minimum_data_window_min": 30,
        "minimum_data_min_trades": 0,
        "minimum_data_only_paper": True,
        "minimum_data_never_live": True,
        "sentinel_explore_quality_min": 60,
        "sentinel_explore_execution_min": 68,
        "sentinel_explore_stake_mult": 0.25,
        "sentinel_explore_max_open": 1,
        "sentinel_explore_cooldown_min": 5.0,
        "sentinel_explore_only_paper": True,
        "sentinel_explore_learning_tag": "sentinel_exploration_quality_test",
    },
}

PARALLEL_IDS = MODE_IDS
ALL_MODE_IDS = MODE_IDS


def _load_file() -> dict[str, Any]:
    if not _PROFILES_PATH.is_file():
        return {"version": 2, "modes": deepcopy(_BUILTIN_MODES)}
    try:
        return json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 2, "modes": deepcopy(_BUILTIN_MODES)}


def _merge_mode(mid: str, builtin: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    base = deepcopy(builtin)
    over = raw.get(mid) if isinstance(raw.get(mid), dict) else {}
    base.update(over)
    base["id"] = mid
    return base


def parallel_profiles() -> dict[str, dict[str, Any]]:
    return all_mode_profiles()


def all_mode_profiles() -> dict[str, dict[str, Any]]:
    raw = _load_file().get("modes") or {}
    out: dict[str, dict[str, Any]] = {}
    for mid in MODE_IDS:
        builtin = _BUILTIN_MODES.get(mid, {})
        out[mid] = _merge_mode(mid, builtin, raw)
    return out


def _apply_mega_env(prof: dict[str, Any]) -> dict[str, Any]:
    """9006.env — MEGA stake / TP / giriş eşiği override (canlı profil)."""
    import os

    out = dict(prof)
    for env_key, prof_key, parser in (
        ("MEGA_MIN_STAKE_USD", "min_stake_usd", float),
        ("MEGA_MAX_STAKE_USD", "max_stake_usd", float),
        ("MEGA_TP_STAKE_PCT", "tp_stake_pct", float),
        ("MEGA_TP_TRIGGER_FRAC", "tp_trigger_frac", float),
        ("MEGA_EXIT_MIN_NET_USD", "exit_min_net_usd", float),
        ("MEGA_ENTRY_MIN_NET_USD", "entry_min_net_usd", float),
        ("MEGA_MIN_MOVE_PCT", "mega_min_move_pct", float),
        ("MEGA_TOP_MOVER_MIN_MOVE_PCT", "mega_top_mover_min_move_pct", float),
        ("MEGA_MIN_SCORE", "mega_min_score", float),
        ("MEGA_MIN_SPIKE_CHANGE_PCT", "mega_min_spike_change_pct", float),
        ("MEGA_MIN_VOL_RATIO", "mega_min_vol_ratio", float),
        ("MEGA_LEVERAGE_WEAK", "mega_leverage_weak", int),
        ("MEGA_LEVERAGE_MEDIUM", "mega_leverage_medium", int),
        ("MEGA_LEVERAGE_STRONG", "mega_leverage_strong", int),
        ("MEGA_SPIKE_MIN_AGE_SEC", "spike_min_age_sec", float),
    ):
        raw = os.getenv(env_key, "").strip()
        if not raw:
            continue
        try:
            out[prof_key] = parser(raw)
        except ValueError:
            pass
    exit_vals: list[float] = []
    for env_key in ("MEGA_EXIT_MIN_NET_USD", "MEGA_MIN_CLOSE_NET_USD"):
        raw = os.getenv(env_key, "").strip()
        if not raw:
            continue
        try:
            exit_vals.append(float(raw))
        except ValueError:
            pass
    if exit_vals:
        out["exit_min_net_usd"] = max(exit_vals)
    top_mover = os.getenv("MEGA_REQUIRE_TOP_MOVER", "").strip().lower()
    if top_mover:
        out["mega_require_top_mover"] = top_mover in ("1", "true", "yes")
    return out


def _apply_berserk2_env(prof: dict[str, Any]) -> dict[str, Any]:
    """9005.env — BERSERK2 stake/TP override."""
    import os

    out = dict(prof)
    for env_key, prof_key, parser in (
        ("BERSERK2_NET_TP_USD", "berserk2_net_tp_usd", float),
        ("BERSERK2_TP_STAKE_PCT", "berserk2_tp_stake_pct", float),
        ("BERSERK2_SL_STAKE_PCT", "berserk2_sl_stake_pct", float),
        ("BERSERK2_ENTRY_MIN_NET_USD", "berserk2_entry_min_net_usd", float),
        ("BERSERK2_ENTRY_MIN_NET_USD", "entry_min_net_usd", float),
    ):
        raw = os.getenv(env_key, "").strip()
        if not raw:
            continue
        try:
            out[prof_key] = parser(raw)
            if prof_key.startswith("berserk2_") and prof_key.endswith("_pct"):
                base = prof_key.replace("berserk2_", "")
                out[base] = parser(raw)
        except ValueError:
            pass
    return out


def get_profile(mode_id: str) -> dict[str, Any] | None:
    mid = resolve_mode_id(mode_id)
    p = all_mode_profiles().get(mid)
    if mid == "mega" and p:
        return _apply_mega_env(p)
    if mid == "berserk2" and p:
        return _apply_berserk2_env(p)
    return p


def live_profile() -> dict[str, Any]:
    """Geriye uyumluluk — aktif futures mod profili."""
    from elite_trader.panel_strategy import active_execution_mode

    return get_profile(active_execution_mode()) or get_profile("evrim") or {}


def save_profile(mode_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    mid = resolve_mode_id(mode_id)
    if mid not in MODE_IDS:
        raise ValueError(f"unknown mode: {mode_id}")
    data = _load_file()
    modes = data.setdefault("modes", {})
    builtin = _BUILTIN_MODES[mid]
    cur = dict(modes.get(mid) or builtin)
    cur.update(patch)
    modes[mid] = cur
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["version"] = 2
    _PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return all_mode_profiles()[mid]


def reset_profile(mode_id: str) -> dict[str, Any]:
    mid = resolve_mode_id(mode_id)
    if mid not in MODE_IDS:
        raise ValueError(f"unknown mode: {mode_id}")
    data = _load_file()
    modes = data.setdefault("modes", {})
    modes[mid] = deepcopy(_BUILTIN_MODES[mid])
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _PROFILES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from elite_trader.system_checkpoint_md import on_profile_reset

        on_profile_reset(mid)
    except Exception:
        pass
    return all_mode_profiles()[mid]
