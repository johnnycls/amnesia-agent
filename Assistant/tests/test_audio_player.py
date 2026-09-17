"""Global music service tests without Ren'Py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

GAME = Path(__file__).parents[1] / "game"
sys.path.insert(0, str(GAME))

from audio.player import MUSIC_CHANNEL, MusicPlayer  # noqa: E402


class MusicPlayerTests(unittest.TestCase):
    def test_same_path_is_not_restarted(self) -> None:
        backend = Mock()
        player = MusicPlayer(backend)

        self.assertTrue(player.play_looped("aurora/default.ogg"))
        self.assertFalse(player.play_looped("aurora/default.ogg"))

        backend.play.assert_called_once_with(
            "aurora/default.ogg", channel=MUSIC_CHANNEL, loop=True
        )

    def test_different_path_replaces_track(self) -> None:
        backend = Mock()
        player = MusicPlayer(backend)

        player.play_looped("aurora/default.ogg")
        self.assertTrue(player.play_looped("kai/default.ogg"))

        self.assertEqual(backend.play.call_count, 2)
        backend.play.assert_called_with(
            "kai/default.ogg", channel=MUSIC_CHANNEL, loop=True
        )

    def test_stop_allows_same_track_to_start_again(self) -> None:
        backend = Mock()
        player = MusicPlayer(backend)

        player.play_looped("default.ogg")
        self.assertTrue(player.stop())
        self.assertTrue(player.play_looped("default.ogg"))

        self.assertEqual(backend.stop.call_count, 1)
        self.assertEqual(backend.play.call_count, 2)


if __name__ == "__main__":
    unittest.main()
