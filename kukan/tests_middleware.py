"""Tests for `kukan.middleware.HtmxLoginRedirectMiddleware`.

The regression this guards: an unauthenticated htmx request hits
`LoginRequiredMiddleware`, gets a 302 to `/login`, and htmx follows it as an
ajax call — swapping the login page's markup into whatever element issued the
request instead of navigating the browser there. `HX-Redirect` is htmx's way
of saying "no, do a real redirect".

Exercised as a unit against the middleware directly, with a stub
`get_response`, rather than through a real view: what matters is "a redirect
to LOGIN_URL becomes HX-Redirect for htmx requests, and nothing else does",
which does not depend on which view produced the redirect.
"""
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, TestCase
from django_htmx.middleware import HtmxMiddleware

from kukan.middleware import HtmxLoginRedirectMiddleware


class HtmxLoginRedirectMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def middleware_returning(self, response):
        """Wraps `HtmxMiddleware` around it, in production's order, so
        `request.htmx` — which the middleware under test relies on — is set
        the same way a real request sets it."""
        inner = HtmxLoginRedirectMiddleware(lambda request: response)
        return HtmxMiddleware(inner)

    def test_a_plain_request_is_untouched(self):
        request = self.factory.get('/kanji/')
        middleware = self.middleware_returning(
            HttpResponseRedirect('/login?next=/kanji/'))
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('HX-Redirect', response)

    def test_an_htmx_request_to_login_gets_hx_redirect_instead(self):
        request = self.factory.get('/kanji/', HTTP_HX_REQUEST='true')
        middleware = self.middleware_returning(
            HttpResponseRedirect('/login?next=/kanji/'))
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['HX-Redirect'], '/login?next=/kanji/')

    def test_an_htmx_redirect_elsewhere_is_left_alone(self):
        """Only a redirect to LOGIN_URL is rewritten. A view that 302s
        somewhere else for its own reasons must reach htmx as a plain 302,
        which htmx already follows correctly on its own."""
        request = self.factory.get('/', HTTP_HX_REQUEST='true')
        middleware = self.middleware_returning(HttpResponseRedirect('/'))
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('HX-Redirect', response)

    def test_a_non_redirect_htmx_response_is_left_alone(self):
        request = self.factory.get('/', HTTP_HX_REQUEST='true')
        middleware = self.middleware_returning(HttpResponse('ok'))
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('HX-Redirect', response)
