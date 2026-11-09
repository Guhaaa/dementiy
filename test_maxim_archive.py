import json
import os
import tempfile
import unittest

from maxim_archive import ChatArchive, flatten_export_text, message_link_base, record

EXPORT = {
    "id": 2497337650,
    "type": "public_supergroup",
    "messages": [
        {"id": 2, "type": "message", "date": "2026-10-28T11:18:43", "from": "Guha",
         "text": ["Агентам нужен ", {"type": "text_link", "text": "сон", "href": "https://arxiv.org/abs/1"}],
         "reply_to_message_id": 1},
        {"id": 1, "type": "message", "date": "2026-10-28T11:00:00", "from": "Max", "text": "привет",
         "photo": "(File not included.)"},
        {"id": 3, "type": "service", "date": "2026-10-28T12:00:00", "text": ""},
        {"id": 4, "type": "message", "date": "2026-10-28T12:00:00", "from": "Dima", "text": ""},
    ],
}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive = ChatArchive(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self, chat_id):
        with open(self.archive.path(chat_id), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_flatten_keeps_hidden_links(self):
        self.assertEqual(flatten_export_text(EXPORT["messages"][0]["text"]),
                         ("Агентам нужен сон", ["https://arxiv.org/abs/1"]))

    def test_import_is_sorted_skips_empty_and_is_idempotent(self):
        chat_id, added = self.archive.import_export(EXPORT)
        self.assertEqual((chat_id, added), (-1002497337650, 2))
        self.assertEqual([m["id"] for m in self.lines(chat_id)], [1, 2])
        self.assertEqual(self.lines(chat_id)[1]["links"], ["https://arxiv.org/abs/1"])
        self.assertEqual(self.lines(chat_id)[1]["reply_to"], 1)
        self.assertEqual(self.lines(chat_id)[0]["media"], "фото")
        self.assertNotIn("media", self.lines(chat_id)[1])
        self.assertEqual(self.archive.import_export(EXPORT)[1], 0)

    def test_live_messages_append_and_links(self):
        self.archive.append(-1001, record(7, "2026-11-09T10:00:00", "Guha", "текст"))
        self.assertEqual(self.archive.ids(-1001), {7})
        self.assertEqual(self.archive.link_base(-1001591588448), "https://t.me/c/1591588448")
        self.archive.remember_username(-1002497337650, "share_your_prompt")
        fresh = ChatArchive(self.tmp.name)  # username переживает перезапуск
        self.assertEqual(fresh.link_base(-1002497337650), "https://t.me/share_your_prompt")
        self.assertEqual(message_link_base(-100555, None), "https://t.me/c/555")

    def test_remove_and_recent_ids(self):
        for i, date in [(1, "2026-11-08T10:00:00+00:00"), (2, "2026-11-09T10:00:00+00:00"),
                        (3, "2026-11-09T11:00:00+00:00")]:
            self.archive.append(-1001, record(i, date, "G", "t"))
        self.assertEqual(self.archive.recent_ids(-1001, "2026-11-09T00:00:00+00:00"), [2, 3])
        self.assertEqual(self.archive.remove(-1001, {2, 99}), 1)
        self.assertEqual(self.archive.ids(-1001), {1, 3})
        self.assertEqual(self.archive.remove(-1001, {99}), 0)


if __name__ == "__main__":
    unittest.main()
