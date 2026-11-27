import asyncio
import os
import tempfile
import unittest

from maxim_wiki import HISTORY, MAX_BATCH_CHARS, Wiki, broken_links, format_batch, message_lines


def rec(i, date, who="Женя", text="привет", **kw):
    return {"id": i, "date": date, "from": who, "text": text, **kw}


class FakeAgent:
    def __init__(self, wiki):
        self.wiki, self.calls = wiki, []

    async def __call__(self, prompt, workdir):
        inbox = sorted(os.listdir(os.path.join(workdir, "_inbox")))
        self.calls.append((prompt, inbox, [open(os.path.join(workdir, "_inbox", n)).read() for n in inbox]))
        with open(os.path.join(workdir, "index.md"), "w") as f:
            f.write("- [[people/1]] Женя\n- [[people/2]] нет страницы\n")
        os.makedirs(os.path.join(workdir, "people"), exist_ok=True)
        open(os.path.join(workdir, "people", "1.md"), "w").write("# Женя")
        return "изменил people/1"


class WikiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wiki = Wiki(self.tmp.name, "2026-11-04")
        self.wiki.prepare()
        self.wiki.set_title(-100, "ИИ")

    def test_old_history_is_one_batch_then_days_without_today(self):
        records = {-100: [
            rec(1, "2025-02-25T19:26:58"), rec(2, "2026-10-01T10:00:00"),
            rec(3, "2026-11-09T10:00:00+00:00"), rec(4, "2026-11-10T10:00:00+00:00"),
            rec(5, "2026-11-11T10:00:00+00:00"),
        ], -200: [rec(9, "2026-11-09T12:00:00+00:00")]}
        batches = [(k, c, [m["id"] for m in ms]) for k, c, ms in self.wiki.pending(records, "2026-11-11")]
        self.assertEqual(batches, [(HISTORY, -100, [1, 2]), ("2026-11-09", -200, [9]),
                                   ("2026-11-09", -100, [3]), ("2026-11-10", -100, [4])])

    def test_history_is_split_into_ordered_parts_and_inbox_cleaned(self):
        records = [rec(i, "2025-03-01T10:00:00", uid=7) for i in range(1, 902)]
        agent = FakeAgent(self.wiki)
        asyncio.run(self.wiki.ingest(-100, HISTORY, records, agent))
        prompt, inbox, texts = agent.calls[0]
        self.assertEqual(len(inbox), 3)  # 400 + 400 + 101
        self.assertIn("по порядку", prompt)
        self.assertIn("строго по порядку", prompt)
        self.assertIn("[2025-03-01 10:00 #1 Женя (id 7)]: привет", texts[0])
        self.assertEqual(os.listdir(os.path.join(self.wiki.root, "_inbox")), [])
        again = Wiki(self.tmp.name, "2026-11-04")  # состояние переживает перезапуск
        self.assertEqual(again.pending({-100: records}, "2026-11-11"), [])

    def test_lint_gets_broken_links_and_runs_weekly(self):
        asyncio.run(self.wiki.ingest(-100, "2026-11-09", [rec(1, "2026-11-09T10:00:00")], FakeAgent(self.wiki)))
        self.assertEqual(broken_links(self.wiki.root), ["index.md → [[people/2]]"])
        agent = FakeAgent(self.wiki)
        asyncio.run(self.wiki.lint_if_due("2026-11-10", agent))
        self.assertIn("index.md → [[people/2]]", agent.calls[0][0])
        self.assertIsNone(asyncio.run(self.wiki.lint_if_due("2026-11-12", agent)))
        self.assertIsNotNone(asyncio.run(self.wiki.lint_if_due("2026-11-17", agent)))

    def test_hint_points_to_wiki_and_other_archives(self):
        self.assertEqual(self.wiki.hint(-100, str), "")
        open(self.wiki.index_path, "w").write("x")
        self.wiki.set_title(-200, "Баня")
        hint = self.wiki.hint(-100, lambda c: self.wiki.index_path if c == -200 else "/none")
        self.assertIn("Пользуйся по своему усмотрению", hint)
        self.assertIn("«Баня»", hint)
        self.assertNotIn("«ИИ»", hint)

    def test_long_day_is_shrunk(self):
        many = [rec(i, "2026-11-09T10:00:00", text="x" * 2000) for i in range(200)]
        self.assertLessEqual(len(format_batch(many)), MAX_BATCH_CHARS)
        self.assertEqual(message_lines([rec(1, "2026-11-09T10:00:00", text="a\nb", reply_to=5, media="фото")]),
                         ["[2026-11-09 10:00 #1 Женя ↩5]: [фото] a b"])


if __name__ == "__main__":
    unittest.main()
