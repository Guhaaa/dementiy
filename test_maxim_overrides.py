import os
import tempfile
import unittest

from maxim_overrides import MAX_RULES, Overrides, parse_correction
from maxim_style import build_system_prompt


class OverridesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sub", "overrides.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rules_and_examples_survive_restart(self):
        o = Overrides(self.path)
        self.assertEqual(o.prompt_section(), "")
        self.assertEqual(o.add_rule("  не шути про Марсель "), 1)
        o.add_example("Отличный вопрос!", "Т.е. ты про context window?")
        again = Overrides(self.path)
        self.assertEqual(again.rules, ["не шути про Марсель"])
        self.assertEqual(again.examples[0]["better"], "Т.е. ты про context window?")
        self.assertIn("- не шути про Марсель", again.prompt_section())
        self.assertIn("Надо: «Т.е. ты про context window?»", again.prompt_section())

    def test_parse_correction(self):
        self.assertEqual(parse_correction('{"kind": "none"}'), None)
        self.assertEqual(parse_correction("не JSON"), None)
        self.assertEqual(parse_correction('{"kind": "rule", "text": ""}'), None)
        self.assertEqual(
            parse_correction('Вот: {"kind": "rule", "text": "Не шути про Марсель"}'),
            ("rule", "Не шути про Марсель"),
        )
        self.assertEqual(
            parse_correction('{"kind": "example", "text": "Т.е. ты про context?"}'),
            ("example", "Т.е. ты про context?"),
        )

    def test_rules_are_capped(self):
        o = Overrides(self.path)
        for i in range(MAX_RULES + 5):
            o.add_rule(str(i))
        self.assertEqual(len(o.rules), MAX_RULES)
        self.assertEqual(o.rules[0], "5")

    def test_section_goes_before_final_instruction(self):
        prompt = build_system_prompt(overrides_section="\n\n## Поправки от самого Максима\n- x")
        self.assertLess(prompt.index("## Поправки"), prompt.index("Не объясняй наличие подсказок"))


if __name__ == "__main__":
    unittest.main()
