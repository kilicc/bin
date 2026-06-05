# POST_RESTART_DATA_FLOW_DIAGNOSIS

**Generated:** 2026-05-23T15:11:18.709500+00:00
**Since restart checkpoint:** 2026-05-23T14:50:07Z

## Soru-Cevap Analizi

### A) Hunter neden 0 işlem?
- Karar sayısı: 3747, paper closed: 0
- Dominant reject: `spike_await_confirmation`
- Muhtemel: fake_breakout_risk, spike_await_confirmation, strength/edge/formula veya cooldown.

### B) Chop neden 0 işlem?
- Karar sayısı: 371, paper closed: 0
- Dominant reject: `chop_score_low`
- Muhtemel: chop_score düşük, trend_guard, hunter breakout veto.

### C) Sentinel neden 0 işlem?
- Karar sayısı: 3536, paper closed: 0
- Dominant reject: `sentinel_weak_observation`
- Muhtemel: sentinel_watch, quality/execution eşik, spread_strict.

### D) Evrim live görünürlük
- Live karar (DB): 0, reject dominant: `—`
- Parallel paper open: 0 (beklenen: 0 — live motor)
- Evrim kararları live/demo panel + order_route_log; parallel tabloda görünmemesi normal.

## Mod Metrikleri

### evrim

```json
{
  "signal_received_count": 0,
  "candidate_count": 0,
  "decision_count": 0,
  "paper_open_count": 0,
  "paper_closed_count": 0,
  "live_open_count": 0,
  "live_closed_count": 0,
  "reject_count": 0,
  "top_10_reject_reasons": [],
  "avg_score": null,
  "avg_expected_net_pnl": null,
  "avg_spread": null,
  "avg_fee_gross": null,
  "last_20_decisions": [],
  "last_20_rejects": []
}
```

### berserk

```json
{
  "signal_received_count": 67,
  "candidate_count": 67,
  "decision_count": 67,
  "paper_open_count": 8,
  "paper_closed_count": 138,
  "live_open_count": 0,
  "live_closed_count": 0,
  "reject_count": 0,
  "top_10_reject_reasons": [],
  "avg_score": null,
  "avg_expected_net_pnl": null,
  "avg_spread": null,
  "avg_fee_gross": null,
  "last_20_decisions": [
    {
      "symbol": "GUAUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "QUICKUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "DODOXUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "DODOXUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "SXPUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "SXPUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "SXPUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "SXPUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MYXUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MELANIAUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "MEUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "GMTUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    },
    {
      "symbol": "AIUSDT",
      "allowed": true,
      "reason": "",
      "execution_path": "paper"
    }
  ],
  "last_20_rejects": []
}
```

### hunter

```json
{
  "signal_received_count": 13562,
  "candidate_count": 3747,
  "decision_count": 3747,
  "paper_open_count": 0,
  "paper_closed_count": 0,
  "live_open_count": 0,
  "live_closed_count": 0,
  "reject_count": 13562,
  "top_10_reject_reasons": [
    {
      "reason": "spike_await_confirmation",
      "count": 12970
    },
    {
      "reason": "GUAUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 74
    },
    {
      "reason": "fake_spike",
      "count": 69
    },
    {
      "reason": "PLAYUSDT: 4 SL-EMERGENCY / 72sa",
      "count": 66
    },
    {
      "reason": "BANANAS31USDT: 1 SL-EMERGENCY / 72sa",
      "count": 55
    },
    {
      "reason": "BEATUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 43
    },
    {
      "reason": "FIDAUSDT: 2 SL-EMERGENCY / 72sa",
      "count": 28
    },
    {
      "reason": "HYPEUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 27
    },
    {
      "reason": "UBUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 26
    },
    {
      "reason": "KOMAUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 24
    }
  ],
  "avg_score": null,
  "avg_expected_net_pnl": null,
  "avg_spread": 0.0,
  "avg_fee_gross": null,
  "last_20_decisions": [
    {
      "symbol": "GMTUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SQDUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAHARAUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ZILUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "BANUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "NAORISUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELOUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "JTOUSDT",
      "allowed": false,
      "reason": "JTOUSDT: 2 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "RUNEUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "MANAUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAGAUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "APRUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "HANAUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ARPAUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "OPUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELRUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ONDOUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CGPTUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ASTRUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "1000FLOKIUSDT",
      "allowed": false,
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    }
  ],
  "last_20_rejects": [
    {
      "symbol": "GMTUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SQDUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAHARAUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ZILUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "BANUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "NAORISUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELOUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "JTOUSDT",
      "reason": "JTOUSDT: 2 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "RUNEUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "MANAUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAGAUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "APRUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "HANAUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ARPAUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "OPUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELRUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ONDOUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "CGPTUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "ASTRUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    },
    {
      "symbol": "1000FLOKIUSDT",
      "reason": "spike_await_confirmation",
      "execution_path": "paper"
    }
  ]
}
```

### chop_master

```json
{
  "signal_received_count": 371,
  "candidate_count": 371,
  "decision_count": 371,
  "paper_open_count": 0,
  "paper_closed_count": 0,
  "live_open_count": 0,
  "live_closed_count": 0,
  "reject_count": 371,
  "top_10_reject_reasons": [
    {
      "reason": "chop_score_low",
      "count": 314
    },
    {
      "reason": "PLAYUSDT: 4 SL-EMERGENCY / 72sa",
      "count": 15
    },
    {
      "reason": "PHBUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 14
    },
    {
      "reason": "GUAUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 9
    },
    {
      "reason": "BANANAS31USDT: 1 SL-EMERGENCY / 72sa",
      "count": 7
    },
    {
      "reason": "HYPEUSDT: 1 SL-EMERGENCY / 72sa",
      "count": 3
    },
    {
      "reason": "TRUUSDT: 3 SL-EMERGENCY / 72sa",
      "count": 2
    },
    {
      "reason": "VVVUSDT: 2 SL-EMERGENCY / 72sa",
      "count": 1
    },
    {
      "reason": "WIFUSDT: 2 SL-EMERGENCY / 72sa",
      "count": 1
    },
    {
      "reason": "FIDAUSDT: 2 SL-EMERGENCY / 72sa",
      "count": 1
    }
  ],
  "avg_score": null,
  "avg_expected_net_pnl": null,
  "avg_spread": 0.0,
  "avg_fee_gross": null,
  "last_20_decisions": [
    {
      "symbol": "GMTUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "NIGHTUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "GUAUSDT",
      "allowed": false,
      "reason": "GUAUSDT: 1 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "QUICKUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "BULLAUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "BULLAUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "OBOLUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "DODOXUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "PLAYUSDT",
      "allowed": false,
      "reason": "PLAYUSDT: 4 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "BANANAS31USDT",
      "allowed": false,
      "reason": "BANANAS31USDT: 1 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "INXUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "INXUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "allowed": false,
      "reason": "chop_score_low",
      "execution_path": "paper"
    }
  ],
  "last_20_rejects": [
    {
      "symbol": "GMTUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "NIGHTUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "GUAUSDT",
      "reason": "GUAUSDT: 1 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "QUICKUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "BULLAUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "BULLAUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "OBOLUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "DODOXUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "PLAYUSDT",
      "reason": "PLAYUSDT: 4 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "BANANAS31USDT",
      "reason": "BANANAS31USDT: 1 SL-EMERGENCY / 72sa",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "INXUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "CATIUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "INXUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    },
    {
      "symbol": "COSUSDT",
      "reason": "chop_score_low",
      "execution_path": "paper"
    }
  ]
}
```

### sentinel

```json
{
  "signal_received_count": 3913,
  "candidate_count": 3536,
  "decision_count": 3536,
  "paper_open_count": 0,
  "paper_closed_count": 0,
  "live_open_count": 0,
  "live_closed_count": 0,
  "reject_count": 3913,
  "top_10_reject_reasons": [
    {
      "reason": "sentinel_weak_observation",
      "count": 3376
    },
    {
      "reason": "execution_quality_low",
      "count": 512
    },
    {
      "reason": "PHBUSDT: SL-EMERGENCY geçmişi — mod temkinli girişi kapalı",
      "count": 14
    },
    {
      "reason": "GUAUSDT: SL-EMERGENCY geçmişi — mod temkinli girişi kapalı",
      "count": 3
    },
    {
      "reason": "BANANAS31USDT: SL-EMERGENCY geçmişi — mod temkinli girişi kapalı",
      "count": 3
    },
    {
      "reason": "PLAYUSDT: 4 SL-EMERGENCY / 72sa",
      "count": 2
    },
    {
      "reason": "TRUUSDT: 3 SL-EMERGENCY / 72sa",
      "count": 2
    },
    {
      "reason": "RDNTUSDT: SL-EMERGENCY geçmişi — mod temkinli girişi kapalı",
      "count": 1
    }
  ],
  "avg_score": null,
  "avg_expected_net_pnl": null,
  "avg_spread": 0.06,
  "avg_fee_gross": null,
  "last_20_decisions": [
    {
      "symbol": "SQDUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAHARAUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ZILUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "BANUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "NAORISUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELOUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "JTOUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "RUNEUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "MANAUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAGAUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "APRUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "HANAUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ARPAUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "OPUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELRUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ONDOUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CGPTUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ASTRUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "1000FLOKIUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "RONINUSDT",
      "allowed": false,
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    }
  ],
  "last_20_rejects": [
    {
      "symbol": "SQDUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAHARAUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ZILUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "BANUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "NAORISUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELOUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "JTOUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "RUNEUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "MANAUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "SAGAUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "APRUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "HANAUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ARPAUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "OPUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CELRUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ONDOUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "CGPTUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "ASTRUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "1000FLOKIUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    },
    {
      "symbol": "RONINUSDT",
      "reason": "sentinel_weak_observation",
      "execution_path": "paper"
    }
  ]
}
```

