import json
import tempfile
import unittest
from pathlib import Path

from lakituai import config, daemon, detect


class DaemonConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.rules = self.dir / "settings.json"
        self.bots = self.dir / "bots.json"
        self.players = self.dir / "players.json"
        self.tags = self.dir / "team_tags.json"

    def _load(self, rules_data):
        self.rules.write_text(json.dumps(rules_data))
        return config.load_config(self.bots, self.players, self.tags, self.rules)

    def test_defaults_when_settings_missing(self):
        cfg = config.load_config(self.bots, self.players, self.tags, self.rules)
        self.assertEqual(cfg.daemon.monitor, 1)
        self.assertEqual(cfg.daemon.poll_interval_s, 0.5)
        self.assertEqual(cfg.daemon.gate_fraction, detect.DEFAULT_GATE_FRACTION)
        self.assertEqual(cfg.daemon.complete_min_band, detect.DEFAULT_COMPLETE_MIN_BAND)
        self.assertEqual(cfg.daemon.cooldown_s, 90.0)

    def test_backward_compat_only_races_per_war(self):
        cfg = self._load({"races_per_war": 12})
        self.assertEqual(cfg.races_per_war, 12)
        self.assertEqual(cfg.daemon.gate_fraction, detect.DEFAULT_GATE_FRACTION)

    def test_loads_daemon_section(self):
        cfg = self._load(
            {
                "races_per_war": 12,
                "daemon": {
                    "monitor": 2,
                    "poll_interval_s": 1.0,
                    "gate_fraction": 0.7,
                    "complete_min_band": 0.6,
                    "cooldown_s": 120.0,
                },
            }
        )
        self.assertEqual(cfg.daemon.monitor, 2)
        self.assertEqual(cfg.daemon.poll_interval_s, 1.0)
        self.assertEqual(cfg.daemon.gate_fraction, 0.7)
        self.assertEqual(cfg.daemon.complete_min_band, 0.6)
        self.assertEqual(cfg.daemon.cooldown_s, 120.0)

    def test_partial_daemon_section_falls_back_per_key(self):
        cfg = self._load({"daemon": {"monitor": 3}})
        self.assertEqual(cfg.daemon.monitor, 3)
        self.assertEqual(cfg.daemon.gate_fraction, detect.DEFAULT_GATE_FRACTION)

    def test_corrupt_settings_file_falls_back(self):
        self.rules.write_text("{not json")
        cfg = config.load_config(self.bots, self.players, self.tags, self.rules)
        self.assertEqual(cfg.daemon.monitor, 1)
        self.assertEqual(cfg.races_per_war, 12)

    def test_save_persists_daemon_section(self):
        cfg = config.GameConfig(daemon=config.DaemonConfig(cooldown_s=45.0))
        config.save_config(cfg, self.bots, self.players, self.tags, self.rules)
        with open(self.rules, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["daemon"]["cooldown_s"], 45.0)
        self.assertEqual(data["races_per_war"], 12)

    def test_save_preserves_unknown_keys(self):
        self.rules.write_text(json.dumps({"races_per_war": 12, "custom": "keep"}))
        cfg = config.GameConfig()
        config.save_config(cfg, self.bots, self.players, self.tags, self.rules)
        with open(self.rules, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["custom"], "keep")

    def test_settings_from_config(self):
        cfg = config.GameConfig(daemon=config.DaemonConfig(monitor=2, cooldown_s=30.0))
        settings = daemon.settings_from_config(cfg)
        self.assertEqual(settings.monitor, 2)
        self.assertEqual(settings.cooldown_s, 30.0)
        self.assertEqual(settings.gate_fraction, detect.DEFAULT_GATE_FRACTION)


if __name__ == "__main__":
    unittest.main()
