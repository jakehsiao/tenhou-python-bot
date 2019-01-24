# -*- coding: utf-8 -*-
import unittest

from mahjong.tests_mixin import TestMixin

from game.ai.first_version.helpers.defence import TileDanger
from game.table import Table


class DefenceTestCase(unittest.TestCase, TestMixin):

    def test_defence_and_impossible_wait(self):
        table = Table()
        player = table.player

        table.add_discarded_tile(0, self._string_to_136_tile(honors='1'), False)
        table.add_discarded_tile(0, self._string_to_136_tile(honors='1'), False)
        table.add_discarded_tile(0, self._string_to_136_tile(honors='1'), False)

        tiles = self._string_to_136_array(man='34678', pin='2356', honors='1555')
        tile = self._string_to_136_tile(sou='8')

        player.init_hand(tiles)
        player.draw_tile(tile)

        discard_options, _ = player.ai.hand_builder.find_discard_options(
            player.tiles,
            player.closed_hand,
            player.melds
        )

        enemy_seat = 1
        discard_option = self._find_discard_option(discard_options, honors='1')
        self.assertEqual(len(discard_option.danger.values[enemy_seat]), 1)
        self.assertEqual(
            discard_option.danger.get_total_danger(enemy_seat),
            TileDanger.IMPOSSIBLE_WAIT['value']
        )

    def test_defence_and_third_honor(self):
        table = Table()
        player = table.player

        table.add_discarded_tile(0, self._string_to_136_tile(honors='1'), False)
        table.add_discarded_tile(0, self._string_to_136_tile(honors='1'), False)

        tiles = self._string_to_136_array(man='34678', pin='2356', honors='1555')
        tile = self._string_to_136_tile(sou='8')

        player.init_hand(tiles)
        player.draw_tile(tile)

        discard_options, _ = player.ai.hand_builder.find_discard_options(
            player.tiles,
            player.closed_hand,
            player.melds
        )

        enemy_seat = 1
        discard_option = self._find_discard_option(discard_options, honors='1')
        self.assertEqual(len(discard_option.danger.values[enemy_seat]), 1)
        self.assertEqual(
            discard_option.danger.get_total_danger(enemy_seat),
            TileDanger.HONOR_THIRD['value']
        )

    def _find_discard_option(self, discard_options, sou='', pin='', man='', honors=''):
        tile = self._string_to_136_tile(sou=sou, pin=pin, man=man, honors=honors)
        discard_option = [x for x in discard_options if x.tile_to_discard == tile // 4][0]
        return discard_option