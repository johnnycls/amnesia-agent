import re
import unittest
from pathlib import Path

GAME = Path(__file__).parents[1] / "game"


class MultilingualSetupTests(unittest.TestCase):
    def test_cjk_font_is_bundled(self) -> None:
        font = GAME / "fonts" / "NotoSansCJKsc-Regular.otf"
        self.assertGreater(font.stat().st_size, 1_000_000)
        styles = (GAME / "screens" / "styles.rpy").read_text(encoding="utf-8")
        self.assertIn('font "fonts/NotoSansCJKsc-Regular.otf"', styles)

    def test_each_supported_language_has_the_same_ui_translation_keys(self) -> None:
        translations = (GAME / "translations.rpy").read_text(encoding="utf-8")
        blocks = re.split(
            r"^translate (\w+) strings:\n", translations, flags=re.MULTILINE
        )
        language_blocks = dict(zip(blocks[1::2], blocks[2::2]))
        expected_languages = {"schinese", "tchinese", "japanese", "korean"}
        self.assertEqual(set(language_blocks), expected_languages)

        keys = []
        for block in language_blocks.values():
            block_keys = re.findall(r'^    old "(.*)"$', block, flags=re.MULTILINE)
            self.assertTrue(block_keys)
            if not keys:
                keys = block_keys
            self.assertEqual(block_keys, keys)

    def test_screen_literals_are_translation_keys(self) -> None:
        screens_text = ""
        for path in (GAME / "screens").rglob("*.rpy"):
            screens_text += path.read_text(encoding="utf-8")
        screens_text += (GAME / "script.rpy").read_text(encoding="utf-8")
        translations = (GAME / "translations.rpy").read_text(encoding="utf-8")
        keys = set(re.findall(r'_\("([^"\n]+)"\)', screens_text))
        translated_keys = set(
            re.findall(r'^    old "(.*)"$', translations, flags=re.MULTILINE)
        )
        self.assertTrue(keys)
        self.assertTrue(keys <= translated_keys)

    def test_status_literals_are_translation_keys(self) -> None:
        app_py = (GAME / "state" / "app.py").read_text(encoding="utf-8")
        script = (GAME / "script.rpy").read_text(encoding="utf-8")
        translations = (GAME / "translations.rpy").read_text(encoding="utf-8")
        keys = set(re.findall(r'localize\("([^"\n]+)"', app_py + script))
        translated_keys = set(
            re.findall(r'^    old "(.*)"$', translations, flags=re.MULTILINE)
        )
        self.assertTrue(keys)
        self.assertTrue(keys <= translated_keys)


if __name__ == "__main__":
    unittest.main()
