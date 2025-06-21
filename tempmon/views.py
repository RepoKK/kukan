import json
import logging
from datetime import timedelta
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django import forms
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, UpdateView
from psnawp_api import PSNAWP
from psnawp_api.core.psnawp_exceptions import PSNAWPNotFound, \
    PSNAWPAuthenticationError

from kukan.filters import FGenericDateRange, FGenericMinMax, FFilter, \
    FGenericString
from kukan.forms import BForm
from kukan.views import AjaxList, TableData
from tempmon.models import PlaySession, DataPoint, PsGame, PsnApiKey
from psnawp_api.utils.endpoints import BASE_PATH, API_PATH

logger = logging.getLogger(__name__)


class PSN:
    def __init__(self, token):
        self.psnawp = PSNAWP(token, accept_language='ja', country='JP')
        logger.info('Logged into PSN')

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
try:
    if (token := PsnApiKey.objects.first().code) != '__dummy__':
        psn = PSN(token)
    else:
        psn = None
except PSNAWPAuthenticationError as e:
    logger.error(f'Failed to login to PSN: {e}')
    psn = None
except OperationalError as e:
    # This is just a bootstrap catch-up, should not happen
    logger.error(f'OperationalError: {e}')
    psn = None
except Exception as e:
    logger.error(f'Exception: {e}')
    psn = None


class PsnApiKeyForm(BForm):
    class Meta:
        model = PsnApiKey
        fields = ['code']
        widgets = {
            'code': forms.PasswordInput(attrs={"size": "64"}),
        }

    def clean_code(self):
        new_token = self.cleaned_data['code']
        try:
            new_psn = PSN(new_token)
        except PSNAWPAuthenticationError as e:
            raise ValidationError(f'Failed to authenticate: {e}')

        self.cleaned_data['new_psn'] = new_psn

        return new_token


@csrf_exempt
def add_temp_point(request):
    try:
        logger.info(f'New add_temp_point request, body: {request.body}')
        body = json.loads(request.body)

        if body.pop('API_KEY', None) != settings.TEMPMON_API_KEY:
            logger.error('Received tempmon data with wrong API_KEY')
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


class TempMonViewMixin:
    """Mixin used to display the Tempmon header in red if not logged"""
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['psn_ok'] = (psn != None)
        return context


class PsnApiKeyUpdateView(TempMonViewMixin, UpdateView):
    model = PsnApiKey
    form_class = PsnApiKeyForm
    success_url = reverse_lazy('session_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['remaining_days'] = (
                psn.psnawp._request_builder.authenticator
                ._auth_properties['refresh_token_expires_in'] / 60 / 60 / 24)
        except AttributeError:
            context['remaining_days'] = 'N/A'
        return context

    def form_valid(self, form):
        global psn
        # Save to DB first, then update the global
        res = super().form_valid(form)
        psn = form.cleaned_data['new_psn']
        return res


class PlaySessionListView(TempMonViewMixin, AjaxList):
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


class PlaySessionGraphView(LoginRequiredMixin, TempMonViewMixin, DetailView):
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
        game_time = session.get_time_per_game()
        context['games_legend'] = {
            pk: (PsGame.objects.get(pk=pk).name,
                 self.bg_colors[idx % len(self.bg_colors)],
                 timedelta(seconds=game_time[pk]))
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


class PlaySessionDetailsView(LoginRequiredMixin, TempMonViewMixin, DetailView):
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


def format_duration(duration):
    total_sec = int(duration.total_seconds()) if duration else 0
    hours, remainder = divmod(total_sec, 3600)
    minutes, _ = divmod(remainder, 60)

    return f'{hours}:{minutes:02}'


class PlaytimeMonthlyView(TempMonViewMixin, LoginRequiredMixin, DetailView):
    template_name = 'tempmon/playtime_monthly.html'
    list_title = 'Playtime per Month'

    def get_object(self, queryset=None):
        # This view doesn't need a specific object, but DetailView requires one
        # Return a dummy object
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Calculate the date 24 months ago from the current date
        current_date = datetime.now()
        two_years_ago = current_date - timedelta(days=24*30)  # Approximately 24 months

        # Get all games with play_time
        games = PsGame.objects.filter(play_time__isnull=False)

        # Aggregate play time by month and game
        monthly_data = {}
        game_names = {}  # Store game names for later use

        for game in games:
            game_names[game.pk] = game.name
            # Get all GamePerSessionInfo for this game
            game_sessions = game.gamepersessioninfo_set.filter(
                session__start_time__gte=two_years_ago)
            for gs in game_sessions:
                # Get the month and year of the session
                month_year = gs.session.start_time.strftime('%Y-%m')

                # Initialize the month if it doesn't exist
                if month_year not in monthly_data:
                    monthly_data[month_year] = {}

                # Initialize the game in this month if it doesn't exist
                if game.pk not in monthly_data[month_year]:
                    monthly_data[month_year][game.pk] = timedelta(0)

                # Add the duration to the game's monthly total
                if gs.duration:
                    monthly_data[month_year][game.pk] += gs.duration

        # Convert to hours for the chart
        chart_data = {
            'months': [],
            'games': [],
            'series': []
        }

        # Get unique list of games across all months
        all_game_pks = set()
        for month_data in monthly_data.values():
            all_game_pks.update(month_data.keys())

        # Sort games by name for consistent ordering
        sorted_game_pks = sorted(all_game_pks, key=lambda pk: game_names.get(pk, ''))

        # Prepare game names for the chart
        for game_pk in sorted_game_pks:
            chart_data['games'].append(game_names.get(game_pk, 'Unknown'))

        # Prepare series data for each game
        for game_idx, game_pk in enumerate(sorted_game_pks):
            series_data = []

            # For each month, get the hours for this game
            for month in sorted(monthly_data.keys()):
                if game_idx == 0:  # Only add month once
                    chart_data['months'].append(month)

                # Get hours for this game in this month
                hours = 0
                if game_pk in monthly_data[month]:
                    hours = monthly_data[month][game_pk].total_seconds() / 3600

                series_data.append(round(hours, 2))

            # Add series for this game
            chart_data['series'].append({
                'name': game_names.get(game_pk, 'Unknown'),
                'data': series_data
            })

        context['chart_data'] = json.dumps(chart_data)
        context['list_title'] = self.list_title
        return context


class PlaytimeYearlyView(TempMonViewMixin, LoginRequiredMixin, DetailView):
    template_name = 'tempmon/playtime_yearly.html'
    list_title = 'Playtime per Year'

    def get_object(self, queryset=None):
        # This view doesn't need a specific object, but DetailView requires one
        # Return a dummy object
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get all games with play_time
        games = PsGame.objects.filter(play_time__isnull=False)

        # Aggregate play time by year and game
        yearly_data = {}
        game_names = {}  # Store game names for later use

        for game in games:
            game_names[game.pk] = game.name
            # Get all GamePerSessionInfo for this game
            game_sessions = game.gamepersessioninfo_set.all()
            for gs in game_sessions:
                # Get the year of the session
                year = gs.session.start_time.strftime('%Y')

                # Initialize the year if it doesn't exist
                if year not in yearly_data:
                    yearly_data[year] = {}

                # Initialize the game in this year if it doesn't exist
                if game.pk not in yearly_data[year]:
                    yearly_data[year][game.pk] = timedelta(0)

                # Add the duration to the game's yearly total
                if gs.duration:
                    yearly_data[year][game.pk] += gs.duration

        # Convert to hours for the chart
        chart_data = {
            'years': [],
            'games': [],
            'series': []
        }

        # Get unique list of games across all years
        all_game_pks = set()
        for year_data in yearly_data.values():
            all_game_pks.update(year_data.keys())

        # Sort games by name for consistent ordering
        sorted_game_pks = sorted(all_game_pks, key=lambda pk: game_names.get(pk, ''))

        # Prepare game names for the chart
        for game_pk in sorted_game_pks:
            chart_data['games'].append(game_names.get(game_pk, 'Unknown'))

        # Prepare series data for each game
        for game_idx, game_pk in enumerate(sorted_game_pks):
            series_data = []

            # For each year, get the hours for this game
            for year in sorted(yearly_data.keys()):
                if game_idx == 0:  # Only add year once
                    chart_data['years'].append(year)

                # Get hours for this game in this year
                hours = 0
                if game_pk in yearly_data[year]:
                    hours = yearly_data[year][game_pk].total_seconds() / 3600

                series_data.append(round(hours, 2))

            # Add series for this game
            chart_data['series'].append({
                'name': game_names.get(game_pk, 'Unknown'),
                'data': series_data
            })

        context['chart_data'] = json.dumps(chart_data)
        context['list_title'] = self.list_title
        return context


class GamesListView(TempMonViewMixin, AjaxList):
    model = PsGame
    template_name = 'tempmon/game_list.html'
    default_sort = '-last_played'
    list_title = 'Game play time'
    filters = [FGenericString('Title', 'name'),
               FGenericMinMaxDurationMin('Duration (min)',
                                         'play_time'),
               ]
    table_data = TableData(model, [
        'name',
        {'name': 'last_played',
         'format': TableData.FieldProps.format_datetime_min},
        {'name': 'play_time',
         'format': format_duration},
    ])
