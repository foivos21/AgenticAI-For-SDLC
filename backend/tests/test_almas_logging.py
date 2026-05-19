from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import Settings
from app.services.almas.logging import log_stage_payload


class ALMASLoggingTests(unittest.TestCase):
    @patch("app.services.almas.logging.logger")
    def test_log_stage_payload_redacts_and_truncates(self, mock_logger) -> None:
        settings = Settings(
            almas_enable_color_logs=False,
            almas_log_payload_max_chars=120,
            almas_redact_sensitive_logs=True,
        )

        log_stage_payload(
            settings,
            run_id="run-1",
            issue_key="SDLC-1",
            agent="analyzer",
            stage="input",
            model="test-model",
            payload={
                "api_token": "super-secret",
                "text": "x" * 500,
            },
        )

        self.assertTrue(mock_logger.info.called)
        args = mock_logger.info.call_args.args
        self.assertEqual(args[0], "%s\n%s")
        self.assertIn("[ALMAS][ANALYZER][INPUT]", args[1])
        self.assertIn("***REDACTED***", args[2])
        self.assertIn("...<truncated", args[2])


if __name__ == "__main__":
    unittest.main()
