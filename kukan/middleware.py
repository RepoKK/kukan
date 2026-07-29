"""Project-wide middleware for the HTMX frontend."""
from django.conf import settings
from django_htmx.http import HttpResponseClientRedirect


class HtmxLoginRedirectMiddleware:
    """Turn a login redirect into an `HX-Redirect` for htmx requests.

    `LoginRequiredMiddleware` answers an unauthenticated request with a plain
    302 to `LOGIN_URL`. htmx follows a 302 itself and swaps the response body
    — the login page — into whatever element issued the request, rather than
    sending the browser there. `HX-Redirect` tells htmx to navigate instead.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (getattr(request, 'htmx', False)
                and response.status_code == 302
                and response.url.startswith(settings.LOGIN_URL)):
            return HttpResponseClientRedirect(response.url)
        return response
