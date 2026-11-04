import unittest

from analyze_chat import analyze


def msg(i, text, author="Максим", **extra):
    return {"id": i, "type": "message", "date": "2026-01-0%dT10:00:00" % (i % 9 + 1),
            "from": author, "from_id": "user1" if author == "Максим" else "user2",
            "text": text, **extra}


class AnalyzeChatTests(unittest.TestCase):
    def test_report_separates_pastes_and_finds_quotes(self):
        data = {"name": "test", "messages": [
            msg(1, "Кстати, т.е. это работает?"),
            msg(2, "«Скрипач не нужен.»"),
            msg(3, "x" * 800),
            msg(4, [{"type": "pre", "text": "print(1)"}]),
            msg(5, "Чёрт!", reply_to_message_id=6),
            msg(6, "вопрос", author="Женя"),
        ]}
        report = analyze(data, "Максим", min_count=1)
        self.assertIn("Разговорных сообщений: 3.", report)
        self.assertIn("длинное (>700) — 1", report)
        self.assertIn("код — 1", report)
        self.assertIn("- `кстати` — 1", report)
        self.assertIn("«Скрипач не нужен.»", report)
        self.assertIn("- Женя — 1", report)


if __name__ == "__main__":
    unittest.main()
