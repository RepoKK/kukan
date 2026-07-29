"""Characterisation tests for the `add_temp_point` sensor endpoint.

This endpoint is a hardware contract. The firmware that calls it is not in this
repository, cannot be updated in step with the server, and has no retry buffer:
anything it fails to deliver is lost silently. Every assertion here pins a
detail the firmware depends on, so that a refactor that changes one fails
loudly instead of quietly dropping readings.

The contract, restated:

* URL is ``/tempmon/add_temp_point/`` and the method is POST.
* The body is JSON and carries the shared secret under the key ``API_KEY``.
* The remaining keys map field-for-field onto ``DataPoint``.
* A success returns exactly ``{'result': 'OK'}``.
* The view is CSRF-exempt.
* The status is **always** 200, including on error. The firmware does not read
  the body, so a non-200 is the only thing it could notice, and it would have
  no way to recover.

The final point is the counter-intuitive one, and the reason these tests assert
200 on paths that are plainly failures. That is deliberate, not an oversight.
"""
import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from tempmon.models import PlaySession, PsGame

# A session that starts and reports at the same instant: the first point of a
# new session, which is what the sensor sends after a power cycle.
FIRST_POINT = {
    'session_time': 1703643862,  # 2023-12-27T11:24:22+09:00
    'current_time': 1703643862,
    'temperature': 21.9,
    'humidity': 30.1,
    'pressure': 10000.3,
}

API_KEY = 'test-api-key'


@override_settings(TEMPMON_API_KEY=API_KEY)
class TestAddTempPointContract(TestCase):
    """The wire format, exactly as the sensor firmware sends it."""

    url = '/tempmon/add_temp_point/'

    def setUp(self):
        # enforce_csrf_checks proves @csrf_exempt is doing the work: the sensor
        # has no way to obtain a token, so losing the exemption bricks it.
        self.client = Client(enforce_csrf_checks=True)

    def post(self, body):
        return self.client.post(
            self.url, data=json.dumps(body), content_type='application/json')

    def test_url_is_stable(self):
        """The firmware has this path compiled in; reverse() must not move it."""
        from django.urls import reverse
        self.assertEqual(reverse('tempmon:add_temp_point'), self.url)

    @patch('tempmon.views.get_psn')
    def test_accepts_point_and_returns_ok(self, get_psn):
        get_psn.return_value.get_current_game.return_value = -1

        response = self.post({'API_KEY': API_KEY, **FIRST_POINT})

        self.assertEqual(response.status_code, 200)
        # Exact body, not a subset: the firmware compares the whole payload.
        self.assertEqual(json.loads(response.content), {'result': 'OK'})

        session = PlaySession.objects.get()
        self.assertEqual(session.start_temp, 21.9)
        self.assertEqual(session.data_dict,
                         {1703643862: (21.9, 30.1, 10000.3, -1)})

    @patch('tempmon.views.get_psn')
    def test_api_key_is_stripped_before_building_the_point(self, get_psn):
        """API_KEY is popped, not passed on to DataPoint(**body)."""
        get_psn.return_value.get_current_game.return_value = -1

        response = self.post({'API_KEY': API_KEY, **FIRST_POINT})

        self.assertEqual(json.loads(response.content), {'result': 'OK'})
        self.assertEqual(PlaySession.objects.count(), 1)

    @patch('tempmon.views.get_psn')
    def test_current_game_is_recorded_against_the_point(self, get_psn):
        game = PsGame.objects.create(title_id='PPSA02269_00', name='AC VI')
        get_psn.return_value.get_current_game.return_value = game.pk

        self.post({'API_KEY': API_KEY, **FIRST_POINT})

        session = PlaySession.objects.get()
        self.assertEqual(session.data_dict[1703643862][3], game.pk)

    def test_wrong_api_key_is_rejected_but_still_returns_200(self):
        response = self.post({'API_KEY': 'wrong', **FIRST_POINT})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content),
                         {'result': 'Failure - wrong API_KEY'})
        self.assertEqual(PlaySession.objects.count(), 0)

    def test_missing_api_key_is_rejected_but_still_returns_200(self):
        response = self.post(FIRST_POINT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content),
                         {'result': 'Failure - wrong API_KEY'})
        self.assertEqual(PlaySession.objects.count(), 0)

    def test_malformed_json_returns_200(self):
        response = self.client.post(
            self.url, data='not json at all',
            content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            json.loads(response.content)['result'].startswith('Failure:'))

    def test_unknown_field_returns_200(self):
        """A firmware that grows a field must not take the server down."""
        response = self.post(
            {'API_KEY': API_KEY, **FIRST_POINT, 'altitude': 42})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            json.loads(response.content)['result'].startswith('Failure:'))

    def test_invalid_point_returns_200(self):
        """current_time before session_time: DataPoint raises, we still 200."""
        bad = {**FIRST_POINT, 'current_time': FIRST_POINT['session_time'] - 60}

        response = self.post({'API_KEY': API_KEY, **bad})

        self.assertEqual(response.status_code, 200)
        self.assertIn('Current time before Session time',
                      json.loads(response.content)['result'])

    def test_psn_unavailable_still_records_the_reading(self):
        """FIXED IN STAGE 8. This test used to assert the opposite.

        There was a module-level `psn` that was an object when the PlayStation
        login had worked and None when it had not — after an expired npsso
        token, a network blip, or simply on a box with no token configured.
        `add_temp_point` then called `psn.get_current_game()` unconditionally,
        the AttributeError was caught by the handler at the bottom of the view,
        and the temperature reading was discarded with it.

        The firmware has no retry buffer, so those readings were gone. The
        cause was PlayStation; the casualty was the thermometer.

        `get_psn()` now always returns a client, and `get_current_game()` never
        raises, so an unusable PSN costs the game attribution and nothing else.
        """
        from tempmon.psn import NullPsnClient, reset_psn

        reset_psn(NullPsnClient('no token'))
        self.addCleanup(reset_psn)

        response = self.post({'API_KEY': API_KEY, **FIRST_POINT})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'result': 'OK'})

        session = PlaySession.objects.get()
        self.assertEqual(
            next(iter(session.data_dict.values()))[3], -1,
            'the point should be stored, attributed to no game')

    @patch('tempmon.views.get_psn')
    def test_get_is_not_accepted(self, get_psn):
        """Only POST carries a body; a GET must not create anything."""
        get_psn.return_value.get_current_game.return_value = -1

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(PlaySession.objects.count(), 0)

    @patch('tempmon.views.get_psn')
    def test_no_authentication_required(self, get_psn):
        """The sensor cannot log in. This must never sit behind @login_required."""
        get_psn.return_value.get_current_game.return_value = -1

        response = self.post({'API_KEY': API_KEY, **FIRST_POINT})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('login', response.get('Location', ''))
