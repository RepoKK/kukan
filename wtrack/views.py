import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from wtrack.comm_withings import CommWithings

logger = logging.getLogger(__name__)


class WtrackMain(LoginRequiredMixin, TemplateView):
    template_name = "wtrack/wtrack_main.html"


def withings_auth_cb(request):
    auth_code = request.GET.get('code')
    api = CommWithings()

    logger.info(f'Getting credentials with auth code {auth_code}')
    api.save_credentials(auth_code)

    return redirect(reverse('wtrack:wtrack_main'))


def withings_auth_request(_):
    return redirect(CommWithings().get_authorize_url())
