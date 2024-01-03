import json
import logging
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, UpdateView
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFound

from kukan.filters import FGenericDateRange, FGenericMinMax, FFilter
from kukan.forms import BForm
from kukan.views import AjaxList, TableData
from tempmon.models import PlaySession, DataPoint, PsGame, PsnApiKey
from psnawp_api.utils.endpoints import BASE_PATH, API_PATH

logger = logging.getLogger(__name__)


class PSN:
    def __init__(self, token):
        self.psnawp = PSNAWP(token, accept_language='ja', country='JP')

        self.client = self.psnawp.me()
        self.me = self.psnawp.user(account_id=self.client.account_id)

    def get_game_name_in_jp(self, title_id):
        """The GameTitle.get_details hard code to US"""
        game = self.psnawp.game_title(title_id=title_id,
                                      account_id=self.client.account_id)
        return self.psnawp._request_builder.get(
            url=f"{BASE_PATH['game_titles']}"
                f"{API_PATH['title_concept'].format(title_id=game.title_id)}",
            params={"age": 99, "country": "JP", "language": "ja-JP"},
        ).json()[0]['name']

    def get_game_pk(self, title_id):
        try:
            ps_game = PsGame.objects.get(title_id=title_id)
        except PsGame.DoesNotExist:
            try:
                ps_game = PsGame.objects.create(
                    title_id=title_id, name=self.get_game_name_in_jp(title_id))
            except PSNAWPNotFound:
                ps_game = PsGame.objects.create(
                    title_id=title_id, name='__UNKNOWN__')

        return ps_game.pk

    def get_current_game(self):
        status = self.me.get_presence()['basicPresence']
        if status['availability'] == 'unavailable':
            return -1
        else:
            if status['primaryPlatformInfo']['onlineStatus'] == 'online':
                try:
                    title_id = status["gameTitleInfoList"][0]["npTitleId"]
                    return self.get_game_pk(title_id)
                except KeyError:
                    return -1
            else:
                return -1


# Global instance to avoid the overhead everytime this is called
if (token := PsnApiKey.objects.first().code) != '__dummy__':
    psn = PSN(token)
else:
    psn = None


class PsnApiKeyForm(BForm):
    class Meta:
        model = PsnApiKey
        fields = ['code']
        widgets = {
            'code': forms.PasswordInput(attrs={"size": "64"}),
        }


class PsnApiKeyUpdateView(UpdateView):
    model = PsnApiKey
    form_class = PsnApiKeyForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['remaining_days'] = (
                psn.psnawp._request_builder.authenticator
                ._auth_properties['refresh_token_expires_in'] / 60 / 60 / 24)
        except AttributeError:
            context['remaining_days'] = 'N/A'
        return context

    success_url = reverse_lazy('session_list')


@csrf_exempt
def add_temp_point(request):
    try:
        logger.info(f'New add_temp_point request, body: {request.body}')
        body = json.loads(request.body)

        if body.pop('API_KEY', None) != settings.TEMPMON_API_KEY:
            return JsonResponse({'result': f'Failure - wrong API_KEY'})

        pt = DataPoint(**body)
        PlaySession.add_point(pt, psn.get_current_game())

        return JsonResponse({'result': 'OK'})
    except Exception as e:
        logger.error(f'Failure to handle add_temp_point, error: {e}')
        return JsonResponse({'result': f'Failure: {e}'})


class FGenericMinMaxDurationMin(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'v-filter-min-max')

    @staticmethod
    def to_timedelta(val):
        return timedelta(minutes=int(val))

    def add_to_query(self, flt, qry):
        flt_fct = qry.filter
        if flt[0:2] == "≠ ":
            flt_fct = qry.exclude
            flt = self.to_timedelta(flt[2:])
        if '~' in flt:
            flt = flt.split('~')
            kwargs = {}
            if flt[0] != '':
                kwargs.update({self.field + '__gte': self.to_timedelta(flt[0])})
            if flt[1] != '':
                kwargs.update({self.field + '__lte': self.to_timedelta(flt[1])})
        else:
            kwargs = {self.field: flt}
        qry = flt_fct(**kwargs)
        return qry


class PlaySessionListView(AjaxList):
    model = PlaySession
    template_name = 'tempmon/playsession_list.html'
    default_sort = '-start_time'
    list_title = 'Play sessions'
    filters = [FGenericDateRange('Start time', 'start_time'),
               FGenericDateRange('End time', 'end_time'),
               FGenericMinMaxDurationMin('Duration (min)', 'duration'),
               FGenericMinMax('Start temperature', 'start_temp')
               ]
    table_data = TableData(model, [
        {'name': 'start_time',
         'link': TableData.FieldProps.link_pk('tempmon/session'),
         'format': TableData.FieldProps.format_datetime_min},
        {'name': 'end_time',
         'format': TableData.FieldProps.format_datetime_min},
        {'name': 'duration'},
        'start_temp', 'max_temp'
    ])


class PlaySessionGraphView(LoginRequiredMixin, DetailView):
    model = PlaySession
    template_name = 'tempmon/playsession_graph.html'

    bg_colors = ['#F1EAFF', '#EBF3E8', '#CDF5FD',
                 '#FFF0F5', '#FDF7E4', '#EEEEEE']

    @classmethod
    def get_background_matrix(cls, data_dict, list_time):
        game_id = None
        prev_time = None
        start_time = list_time[0]

        for idx, t in enumerate(list_time):
            d = data_dict[t]

            if d[3] != game_id and game_id:
                yield start_time, prev_time, game_id
                start_time = prev_time

            game_id = d[3]
            prev_time = t

            if idx == len(list_time) - 1:
                yield start_time, prev_time, game_id

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = context['object']
        context['duration'] = session.end_time - session.start_time
        d = session.data_dict
        list_time = sorted(d.keys())
        context['temp_data'] = [
            {'x': (t - session.start_time.timestamp())/60,
             'y': d[t][0]}
            for t in list_time
        ]
        context['temp_delta'] = [
            {'x': (t2 - session.start_time.timestamp())/60,
             'y': d[t2][0] - d[t1][0]}
            for t1, t2 in zip(list_time, list_time[1:])
        ]

        unique_game_ordered = []
        for t in list_time:
            if d[t][3] not in unique_game_ordered:
                unique_game_ordered.append(d[t][3])

        context['games_legend'] = {
            pk: (PsGame.objects.get(pk=pk).name,
                 self.bg_colors[idx % len(self.bg_colors)])
            for idx, pk in enumerate(unique_game_ordered)
            if pk != -1
        }

        context['graph_background'] = [[
            (t1 - session.start_time.timestamp()) / 60,
            (t2 - session.start_time.timestamp()) / 60,
            context['games_legend'][game_pk][1]
        ] for t1, t2, game_pk in self.get_background_matrix(d, list_time)
            if game_pk != -1
        ]

        context['switch_link'] = {'path_name': 'session_details',
                                  'label': 'Details'}
        return context


class PlaySessionDetailsView(LoginRequiredMixin, DetailView):
    model = PlaySession
    template_name = 'tempmon/playsession_detail.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.game_dict = {}

    def get_game_from_id(self, pk):
        if pk == -1:
            return 'N/A'
        try:
            return self.game_dict[pk]
        except KeyError:
            try:
                game_name = PsGame.objects.get(pk=pk)
            except PsGame.DoesNotExist:
                return 'N/A'
            self.game_dict[pk] = game_name
            return game_name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = context['object']
        context['duration'] = session.end_time - session.start_time
        d = session.data_dict
        list_time = sorted(d.keys())
        jst = ZoneInfo('Asia/Tokyo')
        context['data'] = {
            'headers': ['Time', 'Duration', 'Game',
                        'Temperature', 'Humidity', 'Pressure'],
            'rows': [[
                datetime.fromtimestamp(t).astimezone(jst).strftime("%H:%M:%S"),
                timedelta(seconds=(t - session.start_time.timestamp())),
                self.get_game_from_id(d[t][3]),
                f'{d[t][0]:.2f}',
                f'{d[t][1]:.2f}',
                f'{d[t][2]:.1f}'
            ] for t in list_time]
        }

        context['switch_link'] = {'path_name': 'session',
                                  'label': 'Graph'}
        return context
