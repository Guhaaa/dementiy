import asyncio
import os
import tempfile
import unittest

from maxim_memory import MAX_DAY_CHARS, Memory, format_day


def rec(i, date, who="Женя", text="привет", **kw):
    return {"id": i, "date": date, "from": who, "text": text, **kw}


RECORDS = [
    rec(1, "2026-11-03T10:00:00", text="до запуска"),
    rec(2, "2026-11-09T10:00:00+00:00", text="про баню"),
    rec(3, "2026-11-09T11:00:00+00:00", who="Бот (ты)", text="схожу", reply_to=2, uid=9),
    rec(4, "2026-11-10T09:00:00+00:00", text="пусто"),
    rec(5, "2026-11-11T09:00:00+00:00", text="сегодня"),
]


class FakeAsk:
    def __init__(self):
        self.prompts = []

    async def __call__(self, prompt):
        self.prompts.append(prompt)
        if "Сообщения:" in prompt:
            return "SKIP" if "пусто" in prompt else "- обещал сходить в баню"
        if "Перепиши память о чате" in prompt:
            return "Женя: любит баню."
        return "Общая память."


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memory = Memory(self.tmp.name, "2026-11-04")
        self.memory.set_title(-100, "Баня")

    def test_days_since_launch_without_today_and_resumable(self):
        ask = FakeAsk()
        days = asyncio.run(self.memory.update_chat(-100, RECORDS, "2026-11-11", ask))
        self.assertEqual(days, 2)  # 09 и 10; 03 — до запуска, 11 — сегодня
        self.assertTrue(os.path.exists(os.path.join(self.memory.days_dir(-100), "2026-11-09.md")))
        self.assertFalse(os.path.exists(os.path.join(self.memory.days_dir(-100), "2026-11-10.md")))
        with open(self.memory.profile_path(-100), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "Женя: любит баню.")
        self.assertIn("#3 Бот (ты) (id 9) ↩2]: схожу", ask.prompts[0])
        again = Memory(self.tmp.name, "2026-11-04")  # состояние переживает перезапуск
        self.assertEqual(again.pending_days(-100, RECORDS, "2026-11-12").keys(), {"2026-11-11"})

    def test_self_layer_and_hint_lists_paths_not_text(self):
        asyncio.run(self.memory.update_chat(-100, RECORDS, "2026-11-11", FakeAsk()))
        self.memory.set_title(-200, "ИИ")
        os.makedirs(os.path.dirname(self.memory.profile_path(-200)))
        with open(self.memory.profile_path(-200), "w") as f:
            f.write("ИИ-чат")
        ask = FakeAsk()
        asyncio.run(self.memory.update_self(ask))
        self.assertIn("## Чат «Баня»", ask.prompts[0])
        self.assertIn("## Чат «ИИ»", ask.prompts[0])
        hint = self.memory.hint(-100, lambda c: f"/arch/{c}.jsonl" if c == -200 else "/none")
        self.assertIn(self.memory.self_path, hint)
        self.assertIn("«Баня» (этот чат)", hint)
        self.assertIn(self.memory.profile_path(-200), hint)
        self.assertNotIn("любит баню", hint)
        self.assertEqual(Memory(tempfile.mkdtemp(), "2026-11-04").hint(-1, str), "")

    def test_long_day_is_shrunk(self):
        many = [rec(i, "2026-11-09T10:00:00+00:00", text="x" * 1000) for i in range(200)]
        self.assertLessEqual(len(format_day(many)), MAX_DAY_CHARS)


if __name__ == "__main__":
    unittest.main()
