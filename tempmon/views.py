import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView
from psnawp_api import PSNAWP

from kukan.filters import FGenericDateRange, FGenericMinMax
from kukan.views import AjaxList, TableData
from tempmon.models import PlaySession, DataPoint, PsGame

logger = logging.getLogger(__name__)


class PSN:
    def __init__(self):
        self.psnawp = PSNAWP(settings.PSN_TOKEN)

        self.client = self.psnawp.me()
        self.me = self.psnawp.user(account_id=self.client.account_id)

    def get_game_pk(self, title_id):
        try:
            ps_game = PsGame.objects.get(title_id=title_id)
        except PsGame.DoesNotExist:
            game = self.psnawp.game_title(title_id=title_id)
            ps_game = PsGame.objects.create(title_id=title_id,
                                            name=game.get_details()[0]['name'])
        return ps_game.pk

    def get_current_game(self):
        status = self.me.get_presence()['basicPresence']
        if status['availability'] == 'unavailable':
            return -1
        else:
            if status['primaryPlatformInfo']['onlineStatus'] == 'online':
                title_id = status["gameTitleInfoList"][0]["npTitleId"]
                return self.get_game_pk(title_id)
            else:
                return -1


# Global instance to avoid the overhead everytime this is called
psn = PSN()


@csrf_exempt
def add_temp_point(request):
    try:
        logger.info(f'New add_temp_point request, body: {request.body}')
        body = json.loads(request.body)

        if body.pop('API_KEY', None) != settings.TEMPMON_API_KEY:
            return JsonResponse({'result': f'Failure - wrong API_KEY'})

        print(psn.get_current_game())
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

    background_colors = ['#F1EAFF', '#EBF3E8', '#CDF5FD',
                         '#FFF0F5', '#FDF7E4', '#EEEEEE']

    @classmethod
    def get_background_matrix(cls, data_dict, list_time):
        game_id = None
        prev_time = None
        start_time = data_dict[list_time[0]][0]
        print(list_time)
        try:
            for t in list_time:
                d = data_dict[t]
                print('LOOP', t, d, game_id)
                if d[3] != game_id:
                    if not game_id:
                        pass
                    else:
                        yield start_time, prev_time, game_id, t
                        start_time = prev_time
                game_id = d[3]
                prev_time = t
        except StopIteration:
            print('HERE')
            yield start_time, prev_time, game_id
            raise

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
        context['graph_background'] = {(0, 10, 0xFF0000), (10, 50, 0x00FF00)}
        context['games_legend'] = [
            set('N/A' if v[3] == -1 else PsGame.objects.get(pk=v[3])
                for v in d.values())
        ]
        return context

# PSN current game
# Token https://andshrew.github.io/PlayStation-Trophies/#/APIv2?id=obtaining-an-authentication-token
# https://note.com/kijitora_neco/n/nf0efa130ae00
# https://github.com/mgp25/psn-api/blob/master/README.md
# https://github.com/isFakeAccount/psnawp