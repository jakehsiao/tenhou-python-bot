import logging
import os
import re
from optparse import OptionParser

import requests
from mahjong.meld import Meld
from mahjong.tile import TilesConverter

from game.table import Table
from tenhou.client import TenhouClient
from tenhou.decoder import TenhouDecoder
from utils.logger import set_up_logging

from collections import defaultdict
import time

logger = logging.getLogger('tenhou')


class TenhouLogReproducer(object):
    """
    The way to debug bot decisions that it made in real tenhou.net games
    """

    def __init__(self, log_url, stop_tag=None, params={}):
        log_id, player_position, needed_round = self._parse_url(log_url)
        log_content = self._download_log_content(log_id)
        rounds = self._parse_rounds(log_content)

        self.player_position = player_position
        self.rounds = rounds
        self.round_content = rounds[needed_round]
        self.stop_tag = stop_tag
        self.decoder = TenhouDecoder()
        self.params = params

    def reproduce(self, dry_run=True, verbose=False):
        draw_tags = ['T', 'U', 'V', 'W']
        discard_tags = ['D', 'E', 'F', 'G']

        player_draw = draw_tags[self.player_position]

        player_draw_regex = re.compile('^<[{}]+\d*'.format(''.join(player_draw)))
        discard_regex = re.compile('^<[{}]+\d*'.format(''.join(discard_tags)))

        table = Table(self.params)

        total = defaultdict(int)
        results = defaultdict(int)

        for i,r in enumerate(self.rounds):
            print("Round:", i)
            print()
            for tag in r:
                if dry_run:
                    #print(tag)
                    pass

                if not dry_run and tag == self.stop_tag:
                    break

                if 'INIT' in tag:
                    values = self.decoder.parse_initial_values(tag)

                    shifted_scores = []
                    for x in range(0, 4):
                        shifted_scores.append(values['scores'][self._normalize_position(x, self.player_position)])

                    table.init_round(
                        values['round_number'],
                        values['count_of_honba_sticks'],
                        values['count_of_riichi_sticks'],
                        values['dora_indicator'],
                        self._normalize_position(self.player_position, values['dealer']),
                        shifted_scores,
                    )

                    hands = [
                        [int(x) for x in self.decoder.get_attribute_content(tag, 'hai0').split(',')],
                        [int(x) for x in self.decoder.get_attribute_content(tag, 'hai1').split(',')],
                        [int(x) for x in self.decoder.get_attribute_content(tag, 'hai2').split(',')],
                        [int(x) for x in self.decoder.get_attribute_content(tag, 'hai3').split(',')],
                    ]

                    table.player.init_hand(hands[self.player_position])

                if player_draw_regex.match(tag) and 'UN' not in tag:
                    tile = self.decoder.parse_tile(tag)
                    table.player.draw_tile(tile)

                if discard_regex.match(tag) and 'DORA' not in tag:
                    tile = self.decoder.parse_tile(tag)
                    player_sign = tag.upper()[1]
                    player_seat = self._normalize_position(self.player_position, discard_tags.index(player_sign))

                    if player_seat == 0:
                        # TODO: add player's state, river, melds, and reach timepoint
                        current_hand = TilesConverter.to_one_line_string(table.player.tiles)
                        choice = table.player.ai.discard_tile(None)
                        table.player.discard_tile(tile)
                        match = int(tile == choice)
                        total["TOTAL"] += 1
                        results["TOTAL"] += match
                        total[table.player.play_state] += 1
                        results[table.player.play_state] += match
                        if verbose:
                            print("Hand:", current_hand)
                            print("AI's Choice:", TilesConverter.to_one_line_string([choice]))
                            print("MP's Choice:", TilesConverter.to_one_line_string(([tile])))
                            print("AI's State:", table.player.play_state)
                            print("Same:", tile == choice)
                            print()
                    else:
                        table.add_discarded_tile(player_seat, tile, False)

                if '<N who=' in tag:
                    meld = self.decoder.parse_meld(tag)
                    player_seat = self._normalize_position(self.player_position, meld.who)
                    table.add_called_meld(player_seat, meld)

                    if player_seat == 0:
                        # we had to delete called tile from hand
                        # to have correct tiles count in the hand
                        if meld.type != Meld.KAN and meld.type != Meld.CHANKAN:
                            table.player.draw_tile(meld.called_tile)

                if '<REACH' in tag and 'step="1"' in tag:
                    who_called_riichi = self._normalize_position(self.player_position,
                                                                 self.decoder.parse_who_called_riichi(tag))
                    table.add_called_riichi(who_called_riichi)
                    # TODO: add reach time point

        if dry_run:
            print(total, results)
            return total, results

        if not dry_run:
            tile = self.decoder.parse_tile(self.stop_tag)
            print('Hand: {}'.format(table.player.format_hand_for_print(tile)))

            # to rebuild all caches
            table.player.draw_tile(tile)
            tile = table.player.discard_tile()

            # real run, you can stop debugger here
            table.player.draw_tile(tile)
            tile = table.player.discard_tile()

            print('Discard: {}'.format(TilesConverter.to_one_line_string([tile])))

    def _normalize_position(self, who, from_who):
        positions = [0, 1, 2, 3]
        return positions[who - from_who]

    def _parse_url(self, log_url):
        temp = log_url.split('?')[1].split('&')
        log_id, player, round_number = '', 0, 0
        for item in temp:
            item = item.split('=')
            if 'log' == item[0]:
                log_id = item[1]
            if 'tw' == item[0]:
                player = int(item[1])
            if 'ts' == item[0]:
                round_number = int(item[1])
        return log_id, player, round_number

    def _download_log_content(self, log_id):
        """
        Check the log file, and if it is not there download it from tenhou.net
        :param log_id:
        :return:
        """
        temp_folder = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'logs')
        if not os.path.exists(temp_folder):
            os.mkdir(temp_folder)

        log_file = os.path.join(temp_folder, log_id)
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                return f.read()
        else:
            url = 'http://e.mjv.jp/0/log/?{0}'.format(log_id)
            response = requests.get(url)

            with open(log_file, 'w') as f:
                f.write(response.text)

            return response.text

    def _parse_rounds(self, log_content):
        """
        Build list of round tags
        :param log_content:
        :return:
        """
        rounds = []

        game_round = []
        tag_start = 0
        tag = None
        for x in range(0, len(log_content)):
            if log_content[x] == '>':
                tag = log_content[tag_start:x + 1]
                tag_start = x + 1

            # not useful tags
            if tag and ('mjloggm' in tag or 'TAIKYOKU' in tag):
                tag = None

            # new round was started
            if tag and 'INIT' in tag:
                rounds.append(game_round)
                game_round = []

            # the end of the game
            if tag and 'owari' in tag:
                rounds.append(game_round)

            if tag:
                # to save some memory we can remove not needed information from logs
                if 'INIT' in tag:
                    # we dont need seed information
                    find = re.compile(r'shuffle="[^"]*"')
                    tag = find.sub('', tag)

                # add processed tag to the round
                game_round.append(tag)
                tag = None

        return rounds[1:]


class SocketMock(object):
    """
    Reproduce tenhou <-> bot communication
    """

    def __init__(self, log_path, log_content=''):
        self.log_path = log_path
        self.commands = []
        if not log_content:
            self.text = self._load_text()
        else:
            self.text = log_content
        self._parse_text()

    def connect(self, _):
        pass

    def shutdown(self, _):
        pass

    def close(self):
        pass

    def sendall(self, message):
        pass

    def recv(self, _):
        if not self.commands:
            raise KeyboardInterrupt('End of commands')

        return self.commands.pop(0).encode('utf-8')

    def _load_text(self):
        log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), self.log_path)
        with open(log_file, 'r') as f:
            return f.read()

    def _parse_text(self):
        """
        Load list of get commands that tenhou.net sent to us
        """
        results = self.text.split('\n')
        for item in results:
            if 'Get: ' not in item:
                continue

            item = item.split('Get: ')[1]
            item = item.replace('> <', '>\x00<')
            item += '\x00'

            self.commands.append(item)


def parse_args_and_start_reproducer():
    parser = OptionParser()

    parser.add_option('-o', '--online_log',
                      type='string',
                      help='Tenhou log with specified player and round number. '
                           'Example: http://tenhou.net/0/?log=2017041516gm-0089-0000-23b4752d&tw=3&ts=2')

    parser.add_option('-l', '--local_log',
                      type='string',
                      help='Path to local log file')

    parser.add_option('-d', '--dry_run',
                      action='store_true',
                      default=False,
                      help='Special option for tenhou log reproducer. '
                           'If true, it will print all available tags in the round')

    parser.add_option('-t', '--tag',
                      type='string',
                      help='Special option for tenhou log reproducer. It indicates where to stop parse round tags')

    opts, _ = parser.parse_args()

    if not opts.online_log and not opts.local_log:
        print('Please, set -o or -l option')
        return

    if opts.online_log and not opts.dry_run and not opts.tag:
        print('Please, set -t for real run of the online log')
        return

    if opts.online_log:
        if '?' not in opts.online_log and '&' not in opts.online_log:
            print('Wrong tenhou log format, please provide log link with player position and round number')
            return

        reproducer = TenhouLogReproducer(opts.online_log, opts.tag)
        reproducer.reproduce(opts.dry_run)
    else:
        set_up_logging()

        client = TenhouClient(SocketMock(opts.local_log))
        try:
            client.connect()
            client.authenticate()
            client.start_game()
        except (Exception, KeyboardInterrupt) as e:
            logger.exception('', exc_info=e)
            client.end_game()


def main():
    #parse_args_and_start_reproducer()

    params_set = [
        {},
        {"force_honitsu":True},
        {"big_diff":True},
    ]

    t0 = time.time()

    for params in params_set:
        total_all = defaultdict(int)
        results_all = defaultdict(int)
        for log_id in os.listdir("full_logs")[:1000]: # total 2800
            #print(l[:-6])
            log_url = "https://tenhou.net/0/?log={}".format(log_id[:-6])
            try:
                total, results = TenhouLogReproducer(log_url, params=params).reproduce(True, False)
                for k in total:
                    total_all[k] += total[k]
                    results_all[k] += results[k]
            except Exception as e:
                print("There is a bug:", e)
                #raise e

        print("\nPARAMS:", params)
        print("\nRESULTS:")
        for k in total_all:
            print(k, ":", results_all[k]/total_all[k])

    print("Running time:", time.time()-t0)



if __name__ == '__main__':
    main()
