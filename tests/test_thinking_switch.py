"""思考模式开关的离线检查，不运行 main 流程或调用模型。"""

import os
import unittest
from unittest.mock import patch

import main
from research_agent.config import load_settings


class ThinkingSwitchTests(unittest.TestCase):
    def test_config_defaults_off_and_can_enable(self):
        with patch("research_agent.config.load_dotenv"), patch.dict(
                os.environ, {"DEEPSEEK_API_KEY": "offline-placeholder"}, clear=True):
            self.assertEqual(load_settings().model_params["extra_body"]["thinking"]["type"], "disabled")
            self.assertEqual(load_settings(thinking=True).model_params["extra_body"]["thinking"]["type"], "enabled")

    def test_cli_defaults_off(self):
        with patch("sys.argv", ["main.py"]), patch("main.run_extraction") as run:
            main.main()
        run.assert_called_once_with(thinking=False)

    def test_cli_passes_enabled_mode(self):
        with patch("sys.argv", ["main.py", "--thinking"]), patch("main.run_extraction") as run:
            main.main()
        run.assert_called_once_with(thinking=True)


if __name__ == "__main__":
    unittest.main()
