# -*- coding: utf-8 -*-
from mahjong.constants import TERMINAL_INDICES, HONOR_INDICES
from mahjong.tile import TilesConverter

from game.ai.first_version.strategies.main import BaseStrategy
from mahjong.utils import plus_dora, is_honor, is_aka_dora
import logging


logger = logging.getLogger("ai")

class TanyaoStrategy(BaseStrategy):
    min_shanten = 3
    not_suitable_tiles = TERMINAL_INDICES + HONOR_INDICES

    def should_activate_strategy(self):
        """
        Tanyao hand is a hand without terminal and honor tiles, to achieve this
        we will use different approaches
        :return: boolean
        """

        result = super(TanyaoStrategy, self).should_activate_strategy()
        if not result:
            return False

        # Get count of dora
        dora_count = sum([plus_dora(x, self.player.table.dora_indicators) for x in self.player.tiles])
        # aka dora
        dora_count += sum([1 for x in self.player.tiles if is_aka_dora(x, self.player.table.has_open_tanyao)])
        # Get shanten
        shanten = self.player.ai.previous_shanten
        # Get hand index
        hand_index = len(self.player.discards)

        #if not ((dora_count >= 1) or (shanten <= 1 and hand_index >= 8) or self.player.is_dealer):
        #    return False

        if len(self.player.discards) <= 4:
           #Do not activate it too early
            return False

        tiles = TilesConverter.to_34_array(self.player.tiles)
        count_of_terminal_pon_sets = 0
        count_of_terminal_pairs = 0
        count_of_valued_pairs = 0
        for x in range(0, 34):
            tile = tiles[x]
            if not tile:
                continue

            if x in self.not_suitable_tiles and tile == 3:
                count_of_terminal_pon_sets += 1

            if x in self.not_suitable_tiles and tile == 2:
                count_of_terminal_pairs += 1

                if x in self.player.valued_honors:
                    count_of_valued_pairs += 1

        # if we already have pon of honor\terminal tiles
        # we don't need to open hand for tanyao
        if count_of_terminal_pon_sets > 0:
            return False

        # with valued pair (yakuhai wind or dragon)
        # we don't need to go for tanyao
        if count_of_valued_pairs > 0:
            return False

        # no pair is ok in tanyao pair
        # but 1+ pairs can't be suitable
        #if count_of_terminal_pairs >= 1:
        #    return False

        # 1234 and 9876 indices
        indices = [
            [0, 1, 2, 3], [8, 7, 6, 5],
            [9, 10, 11, 12], [17, 16, 15, 14],
            [18, 19, 20, 21], [26, 25, 24, 23],
        ]

        num_terminal_lugs = 0
        for index_set in indices:
            first = int(tiles[index_set[0]] >= 1)
            second = int(tiles[index_set[1]] >= 1)
            third = int(tiles[index_set[2]] >= 1)
            fourth = int(tiles[index_set[3]] >= 1)
            if ((first + second >= 2) or (first + third >= 2) or (second + third >= 2)) and fourth == 0:
                num_terminal_lugs += 1
            if first + second + third >= 3:
                num_terminal_lugs += 2
        num_terminal_lugs += count_of_terminal_pairs

        if num_terminal_lugs > 1:
            return False

        return True

    def determine_what_to_discard(self, closed_hand, outs_results, shanten, for_open_hand, tile_for_open_hand,
                                  hand_was_open=False):
        if tile_for_open_hand:
            tile_for_open_hand //= 4

        is_open_hand = self.player.is_open_hand or hand_was_open

        if shanten == 0 and is_open_hand:
            results = []
            # there is no sense to wait 1-4 if we have open hand
            for item in outs_results:
                all_waiting_are_fine = all([self.is_tile_suitable(x * 4) for x in item.waiting])
                if all_waiting_are_fine:
                    results.append(item)

            # we don't have a choice
            # we had to have on bad wait
            if not results:
                return outs_results

            return results
        else:
            return super(TanyaoStrategy, self).determine_what_to_discard(closed_hand,
                                                                         outs_results,
                                                                         shanten,
                                                                         for_open_hand,
                                                                         tile_for_open_hand,
                                                                         hand_was_open)

    def is_tile_suitable(self, tile):
        """
        We can use only simples tiles (2-8) in any suit
        :param tile: 136 tiles format
        :return: True
        """
        tile //= 4
        return tile not in self.not_suitable_tiles

    def try_to_call_meld(self, tile, is_kamicha_discard):
        # Don't call meld too much
        meld, selected_tile = super().try_to_call_meld(tile, is_kamicha_discard)

        if not meld:
            print("This is a bad meld, don't call it.")
            return None, None

        logger.info("Detect a possible tanyao meld: {}".format(meld))
        num_melds = len(self.player.melds)
        if num_melds == 1:
            logger.info("Player has 1 meld, should continue?")
            logger.info("Shanten after call: {}".format(selected_tile.shanten))
            if selected_tile.shanten <= 1:
                logger.info("Should go!")
                return meld, selected_tile
            else:
                logger.info("Too far away from drawing hand, should not call this.")
                return None, None

        else:
            print("Keep attacking!")
            return meld, selected_tile
