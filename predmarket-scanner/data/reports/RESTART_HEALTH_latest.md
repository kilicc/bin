# RESTART_HEALTH

- Generated: `2026-05-23T13:31:37.399532+00:00`
- Base URL: `http://127.0.0.1:9005`

## HTTP

- **panel_mode**: status=200 ok=True
- **motor_gate**: status=200 ok=True
- **connection_live**: status=200 ok=True

## Imports / runtime

```json
{
  "training_snapshot_loaded": true,
  "training_snapshot_created_at": "2026-05-23T13:29:16.751859+00:00",
  "learning_active": false,
  "learning_blocks_trading": false,
  "trading_continues_during_learning": true,
  "active_config_version": "evrim_cfg_active_20260523_131349_42029",
  "candidate_config_version": "evrim_cfg_candidate_20260523_133019_43019",
  "active_futures_mode": "evrim",
  "modes": {
    "evrim": {
      "open_paper": 0,
      "closed": 0,
      "live_motor": false
    },
    "berserk": {
      "open_paper": 8,
      "closed": 800,
      "live_motor": false
    },
    "hunter": {
      "open_paper": 0,
      "closed": 0,
      "live_motor": false
    },
    "chop_master": {
      "open_paper": 0,
      "closed": 800,
      "live_motor": false
    },
    "sentinel": {
      "open_paper": 0,
      "closed": 2,
      "live_motor": false
    }
  },
  "data_lake": {
    "path": "data/data_lake.db",
    "ok": true,
    "paper_trades": 3407,
    "live_trades": 12
  }
}
```

## Motor gate smoke

```json
{
  "test1_berserk_paper_under_evrim": true,
  "test2_hunter_live_candidate": true,
  "test3_evrim_live_when_active": true
}
```
