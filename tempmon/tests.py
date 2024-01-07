import datetime as dt
import os

from django.test import TestCase
from tempmon.models import PlaySession, DataPoint, PsGame, GamePerSessionInfo, \
    PsnApiKey
from tempmon.views import PSN, PlaySessionGraphView


class TestPlaySessionModel(TestCase):
    def test_store_point(self):
        pt = DataPoint(1703643862,  # 2023-12-27T11:24:22+09:00,
                       1703643862, 21.9, 30.1, 10000.3)
        ps = PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3, -1)})

        # Add second point
        pt = DataPoint(1703643862, 1703643892, 21.8, 30.0, 10000.2)
        ps = PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3, -1),
                          1703643892: (21.8, 30.0, 10000.2, -1)})

        # Add third point, with high temp
        pt = DataPoint(1703643862, 1703643952, 22.5, 30.0, 10000.2)
        ps = PlaySession.add_point(pt, 2)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertTrue(ps.start_time, pt.session_time_dt)
        self.assertTrue(ps.end_time, pt.current_time_dt)
        self.assertEqual(ps.max_temp, 22.5)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3, -1),
                          1703643892: (21.8, 30.0, 10000.2, -1),
                          1703643952: (22.5, 30.0, 10000.2, 2)})

        # Add new session
        pt = DataPoint(1703644000, 1703644001, 22.5, 30.0, 10000.2)
        PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 2)

    def test_store_override(self):
        pt1 = DataPoint(1703644000, 1703644001, 22.5, 30.0, 10000.2)
        pt2 = DataPoint(1703644000, 1703644001, 20.7, 30.0, 10000.2)
        PlaySession.add_point(pt1)
        ps = PlaySession.add_point(pt2)
        self.assertEqual(ps.data_dict, {1703644001: (20.7, 30.0, 10000.2, -1)})

    def test_validate_point(self):
        with self.assertRaisesMessage(ValueError,
                                      'Current time before Session time'):
            _ = DataPoint(1703644000, 1703643000, 22.5, 30.0, 10000.2)

    def test_duration(self):
        pt1 = DataPoint(1703644000, 1703644001, 22.5, 30.0, 10000.2)
        pt2 = DataPoint(1703644000, 1703644030, 20.7, 30.0, 10000.2)
        pt3 = DataPoint(1703644000, 1703644020, 20.7, 30.0, 10000.2)
        ps = PlaySession.add_point(pt1)
        self.assertEqual(ps.duration, dt.timedelta(seconds=1))
        self.assertEqual(ps.end_time.timestamp(), 1703644001)
        ps = PlaySession.add_point(pt2)
        self.assertEqual(ps.duration, dt.timedelta(seconds=30))
        self.assertEqual(ps.end_time.timestamp(), 1703644030)
        ps = PlaySession.add_point(pt3)
        self.assertEqual(ps.duration, dt.timedelta(seconds=30))
        self.assertEqual(ps.end_time.timestamp(), 1703644030)

    def test_get_time_per_game(self):
        PsGame.objects.create(name='Game1', title_id='X1')
        PsGame.objects.create(name='Game2', title_id='X2')
        list_val = [  # list of tuple of (time, game pk)
            (1704115053, -1),
            (1704115117, 1), (1704117200, 1), (1704117100, 1), (1704117000, 1),
            (1704117328, -1), (1704117331, -1),
            (1704117359, 2), (1704118000, 2),
            (1704118025, 1), (1704120993, 1)
        ]
        for val in list_val:
            ps = PlaySession.add_point(
                DataPoint(1704115053, val[0], 7, 8, 9), val[1])

        self.assertEqual(ps.duration, dt.timedelta(seconds=5940))

        ps.update_game_per_session_info()
        game1 = GamePerSessionInfo.objects.first()
        self.assertEqual(game1.game.name, 'Game1')
        self.assertEqual(game1.duration, dt.timedelta(seconds=5179))
        self.assertEqual(game1.game.play_time, dt.timedelta(seconds=5179))

        game2 = GamePerSessionInfo.objects.last()
        self.assertEqual(game2.game.name, 'Game2')
        self.assertEqual(game2.duration, dt.timedelta(seconds=666))
        self.assertEqual(game2.game.play_time, dt.timedelta(seconds=666))

        PlaySession.add_point(
            DataPoint(1704122000, 1704122010, 7, 8, 9), -1)
        PlaySession.add_point(
            DataPoint(1704122000, 1704122020, 7, 8, 9), 2)
        PlaySession.add_point(
            DataPoint(1704122000, 1704122054, 7, 8, 9), 2)

        game2 = GamePerSessionInfo.objects.last()
        self.assertEqual(game2.game.play_time, dt.timedelta(seconds=700))


class TestPsn(TestCase):
    def setUp(self) -> None:
        try:
            self.psn = PSN(os.environ['psn_token'])
        except KeyError:
            # Need to set the token in env.var, like: $env:psn_token = 'XXX'
            self.psn = None

    def test_get_current_game(self):
        self.assertTrue(self.psn.get_current_game())

    def test_get_game_pk(self):
        # Check when game is not present
        pk = self.psn.get_game_pk('PPSA02269_00')
        self.assertTrue(1, pk)
        self.assertEqual(PsGame.objects.first().name,
                         'ARMORED CORE VI FIRES OF RUBICON')
        # Check when the game is already present
        pk = self.psn.get_game_pk('PPSA01286_00')
        self.assertTrue(1, pk)


class TestPlaySessionDetailView(TestCase):
    def test_background_color1(self):
        data_dict = {
            1: (10, 1, 1, -1),
            2: (10, 1, 1, -1),
            3: (10, 1, 1, 2),
            4: (10, 1, 1, 3),
            5: (10, 1, 1, 2),
            6: (10, 1, 1, 2)
        }

        expected_result = [(1, 2, -1), (2, 3, 2), (3, 4, 3), (4, 6, 2)]

        g = PlaySessionGraphView.get_background_matrix(
            data_dict, sorted(data_dict.keys()))
        self.assertEqual(expected_result, list(g))

    def test_background_color2(self):
        data_dict = {
            1: (10, 1, 1, -1),
            2: (10, 1, 1, -1),
            3: (10, 1, 1, 2),
            4: (10, 1, 1, 3),
            5: (10, 1, 1, 2)
        }

        expected_result = [(1, 2, -1), (2, 3, 2), (3, 4, 3), (4, 5, 2)]

        g = PlaySessionGraphView.get_background_matrix(
            data_dict, sorted(data_dict.keys()))
        self.assertEqual(expected_result, list(g))

    def test_background_color3(self):
        data_dict = {
            1: (10, 1, 1, -1),
        }

        expected_result = [(1, 1, -1)]

        g = PlaySessionGraphView.get_background_matrix(
            data_dict, sorted(data_dict.keys()))
        self.assertEqual(expected_result, list(g))
