import asyncio
import os
import stat
import tempfile
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST")
os.environ["LLM_PROVIDER"] = "codex"

import maxim_bot  # noqa: E402


class DirectAddressTests(unittest.TestCase):
    def test_username_mention_ignores_case(self):
        self.assertTrue(maxim_bot.is_bot_mentioned("эй @Dementiy_Bot, глянь", "dementiy_bot"))
        self.assertFalse(maxim_bot.is_bot_mentioned("@dementiy_bot2 глянь", "dementiy_bot"))
        self.assertFalse(maxim_bot.is_bot_mentioned("@dementiy_bot", None))

    def test_dementiy_all_cases(self):
        for text in ("Дементий, ты где?", "спроси дементия", "@дементию", "с Дементием", "о дементии"):
            self.assertTrue(maxim_bot.DEMENTIY_RE.search(text), text)

    def test_maxim_is_not_direct_address(self):
        self.assertIsNone(maxim_bot.DEMENTIY_RE.search("Максим, Макс, глянь"))

    def test_direct_response_skips_cooldown(self):
        limiter = maxim_bot.RateLimiter()
        limiter.record_response(1, cooldown=False)
        self.assertEqual(limiter.can_respond(1), (True, "ok"))
        self.assertEqual(limiter.daily_count, 1)
        limiter.record_response(1)
        self.assertFalse(limiter.can_respond(1)[0])


class CodexProviderTests(unittest.TestCase):
    def test_codex_exec_answer_is_read_from_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "codex")
            with open(fake, "w") as f:
                f.write(
                    "#!/bin/sh\n"
                    'while [ "$1" ]; do [ "$1" = -o ] && out="$2"; shift; done\n'
                    'grep -q "Последняя реплика" && echo "  Т.е. работает.  " > "$out"\n'
                )
            os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
            maxim_bot.CODEX_BIN = fake
            engine = maxim_bot.MaximResponseEngine()
            answer = asyncio.run(engine._generate_codex("как дела?", [], "system"))
        self.assertEqual(answer, "Т.е. работает.")


if __name__ == "__main__":
    unittest.main()
