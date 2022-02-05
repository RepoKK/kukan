import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView, ListView

from wtrack.comm_withings import CommWithings
from wtrack.models import Measurement

logger = logging.getLogger(__name__)


class WtrackMain(LoginRequiredMixin, ListView):
    template_name = "wtrack/wtrack_main.html"
    model = Measurement

    def get_queryset(self):
        return (super().get_queryset()
                .filter(measure_date__gte='2022-01-01')
                .order_by('measure_date')
                )



def withings_auth_cb(request):
    auth_code = request.GET.get('code')
    api = CommWithings()

    logger.info(f'Getting credentials with auth code {auth_code}')
    api.save_credentials(auth_code)

    return redirect(reverse('wtrack:wtrack_main'))


def withings_auth_request(_):
    return redirect(CommWithings().get_authorize_url())
