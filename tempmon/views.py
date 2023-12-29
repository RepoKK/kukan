import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFound

from kukan.filters import FGenericDateRange, FGenericMinMax
from kukan.views import AjaxList, TableData
from tempmon.models import PlaySession, DataPoint, PsGame

logger = logging.getLogger(__name__)


class PSN:
    def __init__(self, token):
        self.psnawp = PSNAWP(token)

        self.client = self.psnawp.me()
        self.me = self.psnawp.user(account_id=self.client.account_id)

    def get_game_pk(self, title_id):
        try:
            ps_game = PsGame.objects.get(title_id=title_id)
        except PsGame.DoesNotExist:
            try:
                game = self.psnawp.game_title(title_id=title_id,
                                              account_id=self.client.account_id)
                ps_game = PsGame.objects.create(
                    title_id=title_id, name=game.get_details()[0]['name'])
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
if settings.PSN_TOKEN != '__dummy__':
    psn = PSN(settings.PSN_TOKEN)
else:
    psn = None


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


class PlaySessionListView(AjaxList):
    model = PlaySession
    template_name = 'kukan/default_list.html'
    default_sort = '-start_time'
    list_title = 'Play sessions'
    filters = [FGenericDateRange('Start time', 'start_time'),
               FGenericDateRange('End time', 'end_time'),
               FGenericMinMax('Start temperature', 'start_temp')]
    table_data = TableData(model, [
        {'name': 'start_time',
         'link': TableData.FieldProps.link_pk('tempmon/session'),
         'format': TableData.FieldProps.format_datetime_min},
        {'name': 'end_time',
         'format': TableData.FieldProps.format_datetime_min},
        'start_temp', 'max_temp'
    ])


class PlaySessionDetailView(LoginRequiredMixin, DetailView):
    model = PlaySession

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

        game_pk_list = set(v[3] for v in d.values())
        print(game_pk_list)
        game_color = {pk: ('#FFFFFF' if pk == -1 else
                           self.bg_colors[idx % len(self.bg_colors)])
                      for idx, pk in enumerate(game_pk_list)}
        print(game_color)

        context['graph_background'] = [[
            (t1 - session.start_time.timestamp()) / 60,
            (t2 - session.start_time.timestamp()) / 60,
            game_color[game_pk]
        ] for t1, t2, game_pk in self.get_background_matrix(d, list_time)]

        context['games_legend'] = [
            set('N/A' if v[3] == -1 else str(PsGame.objects.get(pk=v[3]))
                for v in d.values())
        ]
        return context

# PSN current game
# Token https://andshrew.github.io/PlayStation-Trophies/#/APIv2?id=obtaining-an-authentication-token
# https://note.com/kijitora_neco/n/nf0efa130ae00
# https://github.com/mgp25/psn-api/blob/master/README.md
# https://github.com/isFakeAccount/psnawp
