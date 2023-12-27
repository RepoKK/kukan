from django.test import TestCase
from tempmon.models import PlaySession, DataPoint


class TestPlaySessionModel(TestCase):
    def test_store_point(self):
        pt = DataPoint(1703643862,  # 2023-12-27T11:24:22+09:00,
                       1703643862, 21.9, 30.1, 10000.3)
        ps = PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3)})

        # Add second point
        pt = DataPoint(1703643862, 1703643892, 21.8, 30.0, 10000.2)
        ps = PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3),
                          1703643892: (21.8, 30.0, 10000.2)})

        # Add third point, with high temp
        pt = DataPoint(1703643862, 1703643952, 22.5, 30.0, 10000.2)
        ps = PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 1)
        self.assertTrue(ps.start_time, pt.session_time_dt)
        self.assertTrue(ps.end_time, pt.current_time_dt)
        self.assertEqual(ps.max_temp, 22.5)
        self.assertEqual(ps.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3),
                          1703643892: (21.8, 30.0, 10000.2),
                          1703643952: (22.5, 30.0, 10000.2)})

        # Add new session
        pt = DataPoint(1703644000, 1703644001, 22.5, 30.0, 10000.2)
        PlaySession.add_point(pt)
        self.assertTrue(PlaySession.objects.count(), 2)

    def test_store_override(self):
        pt1 = DataPoint(1703644000, 1703644001, 22.5, 30.0, 10000.2)
        pt2 = DataPoint(1703644000, 1703644001, 20.7, 30.0, 10000.2)
        PlaySession.add_point(pt1)
        ps = PlaySession.add_point(pt2)
        self.assertEqual(ps.data_dict, {1703644001: (20.7, 30.0, 10000.2)})

    def test_validate_point(self):
        with self.assertRaisesMessage(ValueError,
                                      'Current time before Session time'):
            _ = DataPoint(1703644000, 1703643000, 22.5, 30.0, 10000.2)