import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import betterstack_api as cli
import betterstack_sql as sql


class Behavior(unittest.TestCase):
    def test_area_credentials_do_not_fall_back(self):
        with patch.dict(
            os.environ, {"BETTERSTACK_UPTIME_TOKEN": "synthetic"}, clear=True
        ):
            with self.assertRaises(cli.SafeError):
                cli.read_token(area="telemetry")

    def test_uptime_v3_uses_uptime_token(self):
        with patch.dict(
            os.environ, {"BETTERSTACK_UPTIME_TOKEN": "synthetic"}, clear=True
        ):
            self.assertEqual(cli.read_token(area="uptime-v3")[0], "synthetic")

    def test_sql_rejects_foreign_host(self):
        with self.assertRaises(ValueError):
            sql.validate_config({"host": "evil.test", "username": "x", "password": "y"})

    def test_sql_rejects_write_and_multiple_statements(self):
        cfg = {
            "host": "sample-connect.betterstackdata.com",
            "username": "x",
            "password": "y",
        }
        for query in ["DELETE FROM logs", "SELECT 1; DROP TABLE logs"]:
            with self.assertRaises(ValueError):
                sql.execute(cfg, query)

    def test_validate_only_selected_area(self):
        with (
            patch.dict(
                os.environ, {"BETTERSTACK_UPTIME_TOKEN": "synthetic"}, clear=True
            ),
            patch("betterstack_api.request", return_value=(200, {"data": []})) as req,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["validate"]), 0)
            req.assert_called_once()
            self.assertIn("uptime.betterstack.com", req.call_args.args[0])

    def test_mutation_preview_no_network(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("betterstack_api.request_json") as req,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["delete", "uptime", "/monitors/synthetic"]), 0)
            req.assert_not_called()
