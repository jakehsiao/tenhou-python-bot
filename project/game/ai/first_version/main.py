# -*- coding: utf-8 -*-
import logging

from mahjong.agari import Agari
from mahjong.constants import AKA_DORA_LIST, CHUN, HAKU, HATSU
from mahjong.hand_calculating.divider import HandDivider
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.hand_config import HandConfig
from mahjong.meld import Meld
from mahjong.shanten import Shanten
from mahjong.tile import TilesConverter
from mahjong.utils import is_pair, is_pon
from mahjong.utils import plus_dora, is_honor, is_aka_dora

from game.ai.base.main import InterfaceAI
from game.ai.discard import DiscardOption
from game.ai.first_version.defence.main import DefenceHandler
from game.ai.first_version.defence.main import COUNTER_RATIO
from game.ai.first_version.strategies.honitsu import HonitsuStrategy
from game.ai.first_version.strategies.main import BaseStrategy
from game.ai.first_version.strategies.tanyao import TanyaoStrategy
from game.ai.first_version.strategies.yakuhai import YakuhaiStrategy

logger = logging.getLogger('ai')

'''
Note: for state changes, 
proactive states are in "should_call_riichi",
reactive states are in "should_go_defence",
defence state is in "discard_tile"
'''


class ImplementationAI(InterfaceAI):
    version = '0.3.2'

    agari = None
    shanten = None
    defence = None
    hand_divider = None
    finished_hand = None
    last_discard_option = None

    previous_shanten = 7
    in_defence = False
    waiting = None

    current_strategy = None

    def __init__(self, player):
        super(ImplementationAI, self).__init__(player)

        self.agari = Agari()
        self.shanten = Shanten()
        self.defence = DefenceHandler(player)
        self.hand_divider = HandDivider()
        self.finished_hand = HandCalculator()
        self.previous_shanten = 7
        self.current_strategy = None
        self.waiting = []
        self.in_defence = False
        self.last_discard_option = None

        # Added for cowboy
        self.wanted_tiles_count = 0
        self.pushing = False

    def init_hand(self):
        """
        Let's decide what we will do with our hand (like open for tanyao and etc.)
        """
        self.determine_strategy()

    def erase_state(self):
        self.current_strategy = None
        self.in_defence = False
        self.last_discard_option = None

        # Added for cowboy
        self.previous_shanten = 7
        self.pushing = False

    def draw_tile(self, tile):
        """
        :param tile: 136 tile format
        :return:
        """
        self.determine_strategy()

    def discard_tile(self, discard_tile):
        # we called meld and we had discard tile that we wanted to discard
        if discard_tile is not None:
            if not self.last_discard_option:
                return discard_tile

            return self.process_discard_option(self.last_discard_option, self.player.closed_hand, True)

        results, shanten = self.calculate_outs(self.player.tiles,
                                               self.player.closed_hand,
                                               self.player.open_hand_34_tiles)

        if shanten < self.previous_shanten:
            logger.info("Shanten: {}".format(shanten))
            self.previous_shanten = shanten

        selected_tile = self.process_discard_options_and_select_tile_to_discard(results, shanten)

        # bot think that there is a threat on the table
        # and better to fold
        # if we can't find safe tiles, let's continue to build our hand
        if self.defence.should_go_to_defence_mode(selected_tile):
            if not self.in_defence:
                logger.info('We decided to fold against other players')
                self.in_defence = True
                self.player.set_state("DEFENCE")
            else:
                #logger.info("Player is alreay in defence")
                pass

            defence_results, shanten = self.calculate_outs(self.player.tiles,
                                                   self.player.closed_hand,
                                                   self.player.open_hand_34_tiles)

            defence_tile = self.defence.try_to_find_safe_tile_to_discard(defence_results)
            if defence_tile:
                return self.process_discard_option(defence_tile, self.player.closed_hand)
        else:
            self.in_defence = False

        # Process the discard option before changing the state
        card2discard = self.process_discard_option(selected_tile, self.player.closed_hand)

        # After adjusting the defence, time to update the state
        if shanten == 0 and self.player.play_state == "PREPARING" and results:  # and results for debugging
            if self.wanted_tiles_count > 4:
                self.player.set_state("PROACTIVE_GOODSHAPE")
            else:
                self.player.set_state("PROACTIVE_BADSHAPE")

        return card2discard

    def process_discard_options_and_select_tile_to_discard(self, results, shanten, had_was_open=False):
        tiles_34 = TilesConverter.to_34_array(self.player.tiles)

        # we had to update tiles value there
        # because it is related with shanten number
        for result in results:
            result.tiles_count = self.count_tiles(result.waiting, tiles_34)
            result.calculate_value(shanten)

        # current strategy can affect on our discard options
        # so, don't use strategy specific choices for calling riichi
        if self.current_strategy:
            results = self.current_strategy.determine_what_to_discard(self.player.closed_hand,
                                                                      results,
                                                                      shanten,
                                                                      False,
                                                                      None,
                                                                      had_was_open)

        return self.chose_tile_to_discard(results)

    def calculate_outs(self, tiles, closed_hand, open_sets_34=None):
        """
        :param tiles: array of tiles in 136 format
        :param closed_hand: array of tiles in 136 format
        :param open_sets_34: array of array with tiles in 34 format
        :return:
        """
        tiles_34 = TilesConverter.to_34_array(tiles)
        closed_tiles_34 = TilesConverter.to_34_array(closed_hand)
        is_agari = self.agari.is_agari(tiles_34, self.player.open_hand_34_tiles)

        results = []
        for hand_tile in range(0, 34):
            if not closed_tiles_34[hand_tile]:
                continue

            tiles_34[hand_tile] -= 1

            shanten = self.shanten.calculate_shanten(tiles_34, open_sets_34)

            waiting = []
            for j in range(0, 34):
                if hand_tile == j or tiles_34[j] == 4:
                    continue

                tiles_34[j] += 1
                if self.shanten.calculate_shanten(tiles_34, open_sets_34) == shanten - 1:
                    waiting.append(j)
                tiles_34[j] -= 1

            tiles_34[hand_tile] += 1

            if waiting:
                results.append(DiscardOption(player=self.player,
                                             shanten=shanten,
                                             tile_to_discard=hand_tile,
                                             waiting=waiting,
                                             tiles_count=self.count_tiles(waiting, tiles_34)))

        if is_agari:
            shanten = Shanten.AGARI_STATE
        else:
            shanten = self.shanten.calculate_shanten(tiles_34, open_sets_34)

        return results, shanten

    def count_tiles(self, waiting, tiles_34):
        n = 0
        for item in waiting:
            n += 4 - self.player.total_tiles(item, tiles_34)
        return n

    def try_to_call_meld(self, tile, is_kamicha_discard):
        if not self.current_strategy:
            return None, None

        meld, discard_option = self.current_strategy.try_to_call_meld(tile, is_kamicha_discard)
        tile_to_discard = None
        if discard_option:
            self.last_discard_option = discard_option
            tile_to_discard = discard_option.tile_to_discard

        return meld, tile_to_discard

    def determine_strategy(self):
        # for already opened hand we don't need to give up on selected strategy
        if self.player.is_open_hand and self.current_strategy:
            return False

        old_strategy = self.current_strategy
        self.current_strategy = None

        # order is important
        strategies = [
            YakuhaiStrategy(BaseStrategy.YAKUHAI, self.player),
            HonitsuStrategy(BaseStrategy.HONITSU, self.player),
        ]

        if self.player.table.has_open_tanyao:
            strategies.append(TanyaoStrategy(BaseStrategy.TANYAO, self.player))

        for strategy in strategies:
            if strategy.should_activate_strategy():
                self.current_strategy = strategy

        if self.current_strategy:
            if not old_strategy or self.current_strategy.type != old_strategy.type:
                message = '{} switched to {} strategy'.format(self.player.name, self.current_strategy)
                if old_strategy:
                    message += ' from {}'.format(old_strategy)
                logger.info(message)
                logger.info('With such a hand: {}'.format(TilesConverter.to_one_line_string(self.player.tiles)))

        if not self.current_strategy and old_strategy:
            logger.debug('{} gave up on {}'.format(self.player.name, old_strategy))

        return self.current_strategy and True or False

    def chose_tile_to_discard(self, results: [DiscardOption]) -> DiscardOption:
        """
        Try to find best tile to discard, based on different valuations
        """

        def sorting(x):
            # - is important for x.tiles_count
            # in that case we will discard tile that will give for us more tiles
            # to complete a hand
            return x.shanten, -x.tiles_count, x.valuation

        # util for drawing
        def get_order(t):
            # if it is honor
            if t // 9 >= 3:
                return 0
            else:
                return min((t % 9), (8 - (t % 9))) + 1

        def display_waiting(w):
            return TilesConverter.to_one_line_string([t * 4 for t in w])

        had_to_be_discarded_tiles = [x for x in results if x.had_to_be_discarded]
        if had_to_be_discarded_tiles:
            had_to_be_discarded_tiles = sorted(had_to_be_discarded_tiles, key=sorting)
            selected_tile = had_to_be_discarded_tiles[0]
        else:
            results = sorted(results, key=sorting)
            #print("Len: ", len(results))

            # init the temp_tile
            temp_tile = results[0]

            # remove needed tiles from discard options
            results = [x for x in results if not x.had_to_be_saved]

            # let's chose most valuable tile first
            if results:
                temp_tile = results[0]
            else:
                return temp_tile

            # and let's find all tiles with same shanten
            results_with_same_shanten = [x for x in results if x.shanten == temp_tile.shanten]

            # if there are 7 pairs
            tiles_34 = TilesConverter.to_34_array(self.player.tiles)
            paired_tiles = [x for x in range(0, 34) if tiles_34[x] == 2]
            num_pairs = len(paired_tiles)

            if num_pairs == 4 and temp_tile.shanten > 1 and not self.player.in_seven_pairs and not self.player.params.get("fool_in_pairs"):
                logger.info("There are 4 pairs!")

                if len(self.player.discards) > 6:
                    logger.info("However it's too late for seven pairs.")
                    for r in results:
                        if r.tile_to_discard in paired_tiles:
                            logger.info("With hand: {}".format(TilesConverter.to_one_line_string(self.player.tiles)))
                            logger.info("Discard {}".format(display_waiting([r.tile_to_discard])))
                            return r
                else:
                    logger.info("It's early, okay to go with seven pairs.")
                    self.player.in_seven_pairs = True


            # TODO: a smart seven pairs strategy should be carried
            if self.player.in_seven_pairs and not self.player.params.get("fool_in_pairs"):
                single_tiles = [x for x in range(0,34) if tiles_34[x] in [1,3,4]]
                single_tiles.sort(key=lambda x: (self.count_tiles([x], tiles_34) >= 2, -get_order(x)))
                for s in single_tiles: # actually only #1 would be used most of the time
                    for r in results:
                        if r.tile_to_discard == s:
                            logger.info("SevenPairsStrategy:")
                            logger.info("Hand: {}".format(TilesConverter.to_one_line_string(self.player.tiles)))
                            logger.info("Discard: {}".format(display_waiting([s])))
                            return r


            # if in drawing
            if temp_tile.shanten == 0:
                print("It's a drawing hand!")
                print("Hand: {}".format(TilesConverter.to_one_line_string(self.player.tiles)))
                # assume that temp tile got the biggest waiting
                if temp_tile.tiles_count > 4:
                    print("It's a good shape, go for it.")
                else:
                    logger.info("It's a bad shape drawing hand, need some calculation.")
                    logger.info("Possible choices: {}".format(TilesConverter.to_one_line_string([x.tile_to_discard*4 for x in results_with_same_shanten])))
                    possible_choices = [(temp_tile, 99)]
                    for r in results_with_same_shanten:
                        print("\nCut:", display_waiting([r.tile_to_discard]))
                        print("Waiting:", display_waiting(r.waiting))
                        print("Order:", [get_order(t) for t in r.waiting])
                        print("Outs:", r.tiles_count)
                        if r.tiles_count == 0:
                            print("It's an impossible drawing.")
                            continue
                        if len(r.waiting) == 1:
                            print("It's an 1 out drawing.")
                            possible_choices.append((r, get_order(r.waiting[0])))
                        else:
                            print("It's a multiple out drawing.")
                            r.waiting.sort(key=get_order)
                            possible_choices.append((r, get_order(r.waiting[0])))
                    possible_choices.sort(key=lambda x: (x[1], -x[0].tiles_count))
                    final_choice = possible_choices[0][0]
                    logger.info("Choice: {} {} {}".format(display_waiting([final_choice.tile_to_discard]), "with waiting", display_waiting(final_choice.waiting)))

                    return final_choice

            # if not in drawing or in drawing with good shape
            possible_options = [temp_tile]
            for discard_option in results_with_same_shanten:
                # there is no sense to check already chosen tile
                if discard_option.tile_to_discard == temp_tile.tile_to_discard:
                    continue

                # we don't need to select tiles almost dead waits
                if discard_option.tiles_count <= 2:
                    continue

                # let's check all other tiles with same shanten
                # maybe we can find tiles that have almost same tiles count number
                # Cowboy: +-2 is a big difference, but +-1 is not
                diff = 1
                if self.player.params.get("big_diff"):
                    diff = 2
                if temp_tile.tiles_count - diff < discard_option.tiles_count < temp_tile.tiles_count + diff:
                    possible_options.append(discard_option)

            # let's sort got tiles by value and let's chose less valuable tile to discard
            possible_options = sorted(possible_options, key=lambda x: x.valuation)
            selected_tile = possible_options[0]

            if selected_tile.shanten == 0:
                print("\nChoice:", display_waiting([selected_tile.tile_to_discard]), "with waiting",
                      display_waiting(selected_tile.waiting))

        return selected_tile

    def process_discard_option(self, discard_option, closed_hand, force_discard=False):
        self.waiting = discard_option.waiting
        self.wanted_tiles_count = discard_option.tiles_count
        self.player.ai.previous_shanten = discard_option.shanten
        self.player.in_tempai = self.player.ai.previous_shanten == 0

        # when we called meld we don't need "smart" discard
        if force_discard:
            return discard_option.find_tile_in_hand(closed_hand)

        last_draw_34 = self.player.last_draw  and self.player.last_draw // 4 or None
        if self.player.last_draw not in AKA_DORA_LIST and last_draw_34 == discard_option.tile_to_discard:
            return self.player.last_draw
        else:
            return discard_option.find_tile_in_hand(closed_hand)

    def estimate_hand_value(self, win_tile, tiles=None, call_riichi=False):
        """
        :param win_tile: 34 tile format
        :param tiles:
        :param call_riichi:
        :return:
        """
        win_tile *= 4

        # we don't need to think, that our waiting is aka dora
        if win_tile in AKA_DORA_LIST:
            win_tile += 1

        if not tiles:
            tiles = self.player.tiles

        tiles += [win_tile]

        config = HandConfig(
            is_riichi=call_riichi,
            player_wind=self.player.player_wind,
            round_wind=self.player.table.round_wind,
            has_aka_dora=self.player.table.has_aka_dora,
            has_open_tanyao=self.player.table.has_open_tanyao
        )

        result = self.finished_hand.estimate_hand_value(tiles,
                                                        win_tile,
                                                        self.player.melds,
                                                        self.player.table.dora_indicators,
                                                        config)
        return result

    def should_call_riichi(self):
        logger.info("Can call a reach!")

        # empty waiting can be found in some cases
        if not self.waiting:
            logger.info("However it is impossible to win.")
            return False

        # In pushing state, it's better to call it
        if self.pushing:
            logger.info("Go for it! The player is in pushing state.")
            return True

        # Get the rank EV after round 3
        if self.table.round_number >= 5:  # DEBUG: set this to 0
            try:
                possible_hand_values = [self.estimate_hand_value(tile, call_riichi=True).cost["main"] for tile in self.waiting]
            except Exception as e:
                print(e)
                possible_hand_values = [2000]
            hand_value = sum(possible_hand_values) / len(possible_hand_values)
            hand_value += self.table.count_of_riichi_sticks * 1000
            if self.player.is_dealer:
                hand_value += 700  # EV for dealer combo

            lose_estimation = 6000 if self.player.is_dealer else 7000

            hand_shape = "pro_bad_shape" if self.wanted_tiles_count <= 4 else "pro_good_shape"

            rank_ev = self.defence.get_rank_ev(hand_value, lose_estimation, COUNTER_RATIO[hand_shape][len(self.player.discards)])

            logger.info('''Cowboy: Proactive reach:
            Hand value: {}    Hand shape: {}
            Is dealer: {}    Current ranking: {}
            '''.format(hand_value, hand_shape, self.player.is_dealer, self.table.get_players_sorted_by_scores()))

            logger.info("Rank EV for proactive reach: {}".format(rank_ev))

            if rank_ev < 0:
                logger.info("It's better to fold.")
                return False
            else:
                logger.info("Go for it!")
                return True

        should_attack = not self.defence.should_go_to_defence_mode()

        # For bad shape, at least 1 dora is required
        # Get count of dora
        dora_count = sum([plus_dora(x, self.player.table.dora_indicators) for x in self.player.tiles])
        # aka dora
        dora_count += sum([1 for x in self.player.tiles if is_aka_dora(x, self.player.table.has_open_tanyao)])
        if self.wanted_tiles_count <= 4 and dora_count == 0 and not self.player.is_dealer:
            should_attack = False
            logger.info("A bad shape with no dora, don't call it.")

        # # If player is on the top, no need to call reach
        # if self.player == self.player.table.get_players_sorted_by_scores()[0] and self.player.scores > 30000:
        #     should_attack = False
        #     logger.info("Player is in 1st position, no need to call reach.")

        if should_attack:
            # If we are proactive, let's set the state!
            logger.info("Go for it!")
            if self.player.play_state == "PREPARING": # If not changed in defense actions
                if self.wanted_tiles_count > 4:
                    self.player.set_state("PROACTIVE_GOODSHAPE")
                else:
                    self.player.set_state("PROACTIVE_BADSHAPE")
            return True

        else:
            logger.info("However it's better to fold.")
            return False


        # These codes are unreachable, it is fine.
        waiting = self.waiting[0]
        tiles = self.player.closed_hand + [waiting * 4]
        closed_melds = [x for x in self.player.melds if not x.opened]
        for meld in closed_melds:
            tiles.extend(meld.tiles[:3])

        tiles_34 = TilesConverter.to_34_array(tiles)

        results = self.hand_divider.divide_hand(tiles_34)
        result = results[0]

        count_of_pairs = len([x for x in result if is_pair(x)])
        # with chitoitsu we can call a riichi with pair wait
        if count_of_pairs == 7:
            return True

        for hand_set in result:
            # better to not call a riichi for a pair wait
            # it can be easily improved
            if is_pair(hand_set) and waiting in hand_set:
                return False

        return True

    def should_call_kan(self, tile, open_kan):
        """
        Method will decide should we call a kan,
        or upgrade pon to kan
        :param tile: 136 tile format
        :param open_kan: boolean
        :return: kan type
        """
        # we don't need to add dora for other players
        if self.player.ai.in_defence:
            return None

        if open_kan:
            # we don't want to start open our hand from called kan
            if not self.player.is_open_hand:
                return None

            # there is no sense to call open kan when we are not in tempai
            if not self.player.in_tempai:
                return None

            # we have a bad wait, rinshan chance is low
            if len(self.waiting) < 2:
                return None

        tile_34 = tile // 4
        tiles_34 = TilesConverter.to_34_array(self.player.tiles)
        closed_hand_34 = TilesConverter.to_34_array(self.player.closed_hand)
        pon_melds = [x for x in self.player.open_hand_34_tiles if is_pon(x)]

        # let's check can we upgrade opened pon to the kan
        if pon_melds:
            for meld in pon_melds:
                # tile is equal to our already opened pon,
                # so let's call chankan!
                if tile_34 in meld:
                    return Meld.CHANKAN

        count_of_needed_tiles = 4
        # for open kan 3 tiles is enough to call a kan
        if open_kan:
            count_of_needed_tiles = 3

        # we have 3 tiles in our hand,
        # so we can try to call closed meld
        if closed_hand_34[tile_34] == count_of_needed_tiles:
            if not open_kan:
                # to correctly count shanten in the hand
                # we had do subtract drown tile
                tiles_34[tile_34] -= 1

            melds = self.player.open_hand_34_tiles
            previous_shanten = self.shanten.calculate_shanten(tiles_34, melds)

            melds += [[tile_34, tile_34, tile_34]]
            new_shanten = self.shanten.calculate_shanten(tiles_34, melds)

            # called kan will not ruin our hand
            if new_shanten <= previous_shanten:
                return Meld.KAN

        return None

    def should_call_win(self, tile, enemy_seat):
        return True

    def enemy_called_riichi(self, enemy_seat):
        """
        After enemy riichi we had to check will we fold or not
        it is affect open hand decisions
        :return:
        """
        #if self.defence.should_go_to_defence_mode():
        #    self.in_defence = True

        # No need to check it here

        pass

    @property
    def enemy_players(self):
        """
        Return list of players except our bot
        """
        return self.player.table.players[1:]
