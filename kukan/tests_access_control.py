"""Access-control tests: what an anonymous caller is allowed to reach.

These exist because of a real bypass found while backfilling tests before the
dependency upgrades.

`AjaxList.dispatch` routes `?ajax=1` straight to `self.get_list` instead of to
`super().dispatch()`. `LoginRequiredMixin` does its work *in* `dispatch`, so
the ajax branch skipped the login check entirely. The HTML page redirected to
/login exactly as intended, which is why it went unnoticed: the only way to see
it was to request the JSON directly.

The effect was that every list view — kanji, 四字熟語, 例文, 諺, test results,
and both tempmon lists — served its full contents to anonymous callers, with
working pagination, sorting and filtering. It was reproduced against the live
site before being fixed.

The tests below are deliberately blunt and assert on status codes rather than
on internals, so they keep working through the Vue-to-HTMX rewrite in Stage 10
and through the Django upgrade in Stage 6. Anything that is public is listed
explicitly, so making a view public becomes a visible edit to this file.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

# Views that are intentionally reachable without logging in. `bustime` is a
# personal bus timetable with no user data; the login and cert paths have to be
# reachable for anyone to log in at all.
PUBLIC_URL_NAMES = {
    'login',
    'logout',
    'bustime:bustime_main',
    'bustime:get_time_to_next_hana',
    # The sensor endpoint authenticates with a shared key in the body, not a
    # session. Covered in detail by tempmon.tests_api_contract.
    'add_temp_point',
}

# Every list view built on AjaxList, by URL name.
AJAX_LIST_URLS = [
    'kukan:kanji_list',
    'kukan:yoji_list',
    'kukan:example_list',
    'kukan:kotowaza_list',
    'kukan:test_result_list',
    'session_list',
    'game_list',
]


class TestAjaxListRequiresLogin(TestCase):
    """The regression test for the bypass. One case per list view."""

    def setUp(self):
        self.client = Client()

    def assertRedirectsToLogin(self, response, url):
        self.assertEqual(
            response.status_code, 302,
            f'{url} served content to an anonymous caller')
        self.assertIn('/login', response['Location'])

    def test_html_page_requires_login(self):
        for name in AJAX_LIST_URLS:
            with self.subTest(view=name):
                url = reverse(name)
                self.assertRedirectsToLogin(self.client.get(url), url)

    def test_ajax_endpoint_requires_login(self):
        """The bypass. This is the assertion that was failing."""
        for name in AJAX_LIST_URLS:
            with self.subTest(view=name):
                url = reverse(name)
                response = self.client.get(url, {'ajax': '1'})
                self.assertRedirectsToLogin(response, url)

    def test_ajax_endpoint_returns_no_data_to_anonymous_caller(self):
        """Belt and braces: whatever the status, it must not be a JSON body."""
        for name in AJAX_LIST_URLS:
            with self.subTest(view=name):
                response = self.client.get(reverse(name), {'ajax': '1'})
                self.assertNotEqual(response.get('Content-Type', ''),
                                    'application/json')

    def test_ajax_with_paging_and_sorting_requires_login(self):
        """The bypass was fully featured; make sure no parameter combination
        finds a way back in."""
        for name in AJAX_LIST_URLS:
            with self.subTest(view=name):
                url = reverse(name)
                response = self.client.get(
                    url, {'ajax': '1', 'page': '2', 'sort_by': 'pk'})
                self.assertRedirectsToLogin(response, url)


class LogoutTest(TestCase):
    """Logout is POST-only from Django 5.0.

    A GET used to work and was what the navbar link did. Django deprecated it
    because a prefetching browser, a crawler, or an <img src> on another site
    could log the user out without them asking. The navbar is now a POST form
    with a CSRF token.
    """

    def setUp(self):
        User.objects.create_user('test_user', password='pwd')
        self.client = Client()
        self.client.login(username='test_user', password='pwd')

    def test_post_logs_out_and_redirects_to_login(self):
        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_get_is_rejected(self):
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 405)

    def test_get_does_not_log_the_user_out(self):
        """The point of the change: a stray GET must leave the session alone."""
        self.client.get(reverse('logout'))
        self.assertIn('_auth_user_id', self.client.session)

    def test_next_page_is_the_login_view(self):
        """next_page now reaches LogoutView. It used to be passed as a URLconf
        extra-kwargs dict, which the view never read."""
        response = self.client.post(reverse('logout'))
        self.assertEqual(response['Location'], reverse('login'))

    def test_navbar_renders_a_post_form_with_a_csrf_token(self):
        response = self.client.get(reverse('kukan:index'))
        self.assertContains(response, f'action="{reverse("logout")}"')
        self.assertContains(response, 'csrfmiddlewaretoken')


class TestEveryNamedViewIsClassified(TestCase):
    """A view is either in PUBLIC_URL_NAMES or it redirects anonymous callers.

    This is the breadth-first net: a new view added during Stages 3-10 is
    caught here automatically, instead of relying on somebody remembering to
    write an access-control test for it.
    """

    def get_checkable_urls(self):
        """Named, no-argument, non-admin URLs, with their reversed path."""
        from django.urls import NoReverseMatch, get_resolver

        from kukan.management.commands.smoke_urls import iter_url_names

        for name in sorted(set(iter_url_names(get_resolver()))):
            if name.startswith('admin:'):
                continue
            try:
                yield name, reverse(name)
            except NoReverseMatch:
                # Needs arguments; not reachable by a bare probe.
                continue

    def test_non_public_views_redirect_anonymous_callers(self):
        client = Client(raise_request_exception=False)
        for name, url in self.get_checkable_urls():
            if name in PUBLIC_URL_NAMES:
                continue
            with self.subTest(view=name):
                response = client.get(url)
                self.assertEqual(
                    response.status_code, 302,
                    f'{name} ({url}) did not redirect an anonymous caller. '
                    f'If it is meant to be public, add it to '
                    f'PUBLIC_URL_NAMES with a reason.')
                self.assertIn('/login', response['Location'])

    def test_public_list_is_accurate(self):
        """Guards against the allow-list rotting: every name in it must still
        resolve, so a renamed or deleted view cannot silently stay exempt."""
        reachable = {name for name, _ in self.get_checkable_urls()}
        stale = PUBLIC_URL_NAMES - reachable
        self.assertEqual(
            stale, set(),
            'PUBLIC_URL_NAMES lists URL names that no longer exist')
