from django.test import TestCase
from tempmon.models import PlaySession, DataPoint, PsGame
from tempmon.views import PSN, PlaySessionDetailView


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


class TestPsn(TestCase):
    def setUp(self) -> None:
        self.psn = PSN()

    def test_get_current_game(self):
        self.assertTrue(self.psn.get_current_game())

    def test_get_game_pk(self):
        # Check when game is not present
        pk = self.psn.get_game_pk('PPSA01286_00')
        self.assertTrue(1, pk)
        self.assertEqual(PsGame.objects.first().name, 'Returnal')
        # Check when the game is already present
        pk = self.psn.get_game_pk('PPSA01286_00')
        self.assertTrue(1, pk)


class TestPlaySessionDetailView(TestCase):
    def test_background_color(self):
        data_dict = {
            1: (1, 1, 1, -1),
            2: (1, 1, 1, -1),
            3: (1, 1, 1, 2),
            4: (1, 1, 1, 3),
            5: (1, 1, 1, 2),
            6: (1, 1, 1, 2)
        }

        expected_result = [(1, 2, -1), (2, 3, 2), (3, 4, 3), (4, 6, 2)]

        g = PlaySessionDetailView.get_background_matrix(
            data_dict, sorted(data_dict.keys()))
        print(g)
        print(next(g))
        print(next(g))
        print(next(g))
        print(next(g))
