import itertools
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, TemplateView, UpdateView

from kukan.filters import FFilter, FGenericDateRange, FGenericMinMax, FGenericString
from kukan.listview import FilteredListView
from kukan.views import TableData
from tempmon.models import (
    DataPoint,
    GamePerSessionInfo,
    PlaySession,
    PsGame,
    PsnApiKey,
)
from tempmon.psn import NO_GAME, PsnClient, get_psn, reset_psn

logger = logging.getLogger(__name__)


class PsnApiKeyForm(forms.ModelForm):
    """A plain ModelForm — `BForm` bought this page nothing.

    `BForm` exists to swap in Buefy widget templates and to stamp `v-model`
    on every field, and this form got neither: the override table keys on the
    exact widget type, and `PasswordInput` is not `TextInput`. The `v-model`
    attribute was rendered onto an input no Vue instance ever mounted over.
    """

    class Meta:
        model = PsnApiKey
        fields = ['code']
        widgets = {
            'code': forms.PasswordInput(attrs={'size': '64', 'class': 'input'}),
        }

    def clean_code(self):
        """Reject a token PSN will not accept, before it is saved.

        Built directly rather than through `tempmon.psn.build_client_from_token`
        on purpose: that helper turns a bad token into a NullPsnClient, which
        is right for start-up and wrong here — the user is typing a token and
        needs to be told it does not work.
        """
        new_token = self.cleaned_data['code']
        try:
            new_psn = PsnClient(new_token)
        except Exception as e:
            raise ValidationError(f'Failed to authenticate: {e}') from e

        self.cleaned_data['new_psn'] = new_psn

        return new_token


@login_not_required
@csrf_exempt
def add_temp_point(request):
    try:
        logger.info(f'New add_temp_point request, body: {request.body}')
        body = json.loads(request.body)

        if body.pop('API_KEY', None) != settings.TEMPMON_API_KEY:
            logger.error('Received tempmon data with wrong API_KEY')
            return JsonResponse({'result': 'Failure - wrong API_KEY'})

        pt = DataPoint(**body)
        # `get_psn()` always returns a client and `get_current_game()` never
        # raises, so a PSN problem costs the game attribution and nothing
        # else. It used to cost the reading: the exception propagated to the
        # handler below, and the device has no retry buffer.
        PlaySession.add_point(pt, get_psn().get_current_game())

        return JsonResponse({'result': 'OK'})
    except Exception as e:
        logger.error(f'Failure to handle add_temp_point, error: {e}')
        return JsonResponse({'result': f'Failure: {e}'})


class FGenericMinMaxDurationMin(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'min-max')

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
        context['psn_ok'] = get_psn().is_available
        return context


class PsnApiKeyUpdateView(TempMonViewMixin, UpdateView):
    model = PsnApiKey
    form_class = PsnApiKeyForm
    success_url = reverse_lazy('tempmon:session_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        days = get_psn().refresh_token_days
        context['remaining_days'] = 'N/A' if days is None else days
        return context

    def form_valid(self, form):
        # Save to DB first, then swap in the client built from the new token.
        res = super().form_valid(form)
        reset_psn(form.cleaned_data['new_psn'])
        return res


class PlaySessionListView(TempMonViewMixin, FilteredListView):
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
            for t1, t2 in itertools.pairwise(list_time)
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
            if pk != NO_GAME
        }

        context['graph_background'] = [[
            (t1 - session.start_time.timestamp()) / 60,
            (t2 - session.start_time.timestamp()) / 60,
            context['games_legend'][game_pk][1]
        ] for t1, t2, game_pk in self.get_background_matrix(d, list_time)
            if game_pk != NO_GAME
        ]

        context['switch_link'] = {'path_name': 'tempmon:session_details',
                                  'label': 'Details'}
        return context


class PlaySessionDetailsView(LoginRequiredMixin, TempMonViewMixin, DetailView):
    model = PlaySession
    template_name = 'tempmon/playsession_detail.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.game_dict = {}

    def get_game_from_id(self, pk):
        if pk == NO_GAME:
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

        context['switch_link'] = {'path_name': 'tempmon:session',
                                  'label': 'Graph'}
        return context


def format_duration(duration):
    total_sec = int(duration.total_seconds()) if duration else 0
    hours, remainder = divmod(total_sec, 3600)
    minutes, _ = divmod(remainder, 60)

    return f'{hours}:{minutes:02}'


class PlaytimeChartView(TempMonViewMixin, LoginRequiredMixin, TemplateView):
    """Hours per game, bucketed by month or by year.

    One view and one template for both pages: they differed only in the
    `strftime` bucket, whether a time window was applied, and the name of the
    JSON key holding the labels. `bucket_format` and `window_days` carry the
    first two; the key is `categories` on both, so the template does not have
    to know which page it is rendering.
    """

    template_name = 'tempmon/playtime.html'
    bucket_format = None
    window_days = None
    list_title = ''

    def get_bucketed_hours(self):
        """{bucket: {game name: hours}} over the configured window.

        One query with the joins spelled out, where this used to walk
        `PsGame` and then `game.gamepersessioninfo_set` per game -- an N+1
        over every game ever played. `game__play_time__isnull=False` is kept
        from the original: `GamePerSessionInfo.save()` recomputes `play_time`
        as a Sum, so a game whose every session has a null duration ends up
        null there and was excluded.
        """
        plays = GamePerSessionInfo.objects.filter(
            game__play_time__isnull=False).select_related('session', 'game')
        if self.window_days is not None:
            plays = plays.filter(
                session__start_time__gte=(timezone.now()
                                          - timedelta(days=self.window_days)))

        buckets = defaultdict(lambda: defaultdict(timedelta))
        for play in plays.only('duration', 'session__start_time', 'game__name'):
            bucket = play.session.start_time.strftime(self.bucket_format)
            buckets[bucket][play.game.name] += play.duration or timedelta(0)
        return buckets

    def get_chart_data(self):
        buckets = self.get_bucketed_hours()
        categories = sorted(buckets)
        games = sorted({name for b in buckets.values() for name in b})
        return {
            'categories': categories,
            'games': games,
            'series': [
                {'name': game,
                 'data': [round(buckets[c].get(game, timedelta(0))
                                .total_seconds() / 3600, 2)
                          for c in categories]}
                for game in games
            ],
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['chart_data'] = self.get_chart_data()
        context['list_title'] = self.list_title
        return context


class PlaytimeMonthlyView(PlaytimeChartView):
    # ~24 months. The original comment called it "approximately 24 months",
    # and nothing downstream depends on the boundary landing on the 1st.
    window_days = 24 * 30
    bucket_format = '%Y-%m'
    list_title = 'Playtime per Month'


class PlaytimeYearlyView(PlaytimeChartView):
    bucket_format = '%Y'
    list_title = 'Playtime per Year'


class GamesListView(TempMonViewMixin, FilteredListView):
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
