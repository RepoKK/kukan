import pickle
from collections import defaultdict
from dataclasses import dataclass

from django.db import models
import datetime as dt
from datetime import UTC

from django.db.models import Sum, Max
from django.utils.timezone import now


@dataclass
class DataPoint:
    session_time: int
    current_time: int
    temperature: float
    humidity: float
    pressure: float

    @property
    def session_time_dt(self):
        return dt.datetime.fromtimestamp(self.session_time).astimezone(UTC)

    @property
    def current_time_dt(self):
        return dt.datetime.fromtimestamp(self.current_time).astimezone(UTC)

    @property
    def values(self):
        return self.temperature, self.humidity, self.pressure

    def __post_init__(self):
        if self.current_time < self.session_time:
            raise ValueError('Current time before Session time')


class PlaySession(models.Model):
    start_time = models.DateTimeField(verbose_name='Start time')
    end_time = models.DateTimeField(verbose_name='End time')
    start_temp = models.FloatField(verbose_name='Starting temperature')
    max_temp = models.FloatField(verbose_name='Max temperature')
    data_points = models.BinaryField(verbose_name='Data points')
    duration = models.DurationField(verbose_name='Duration')

    def __str__(self):
        return f'{self.start_time}'

    @property
    def data_dict(self):
        return pickle.loads(self.data_points)

    @property
    def current_temp(self):
        return self.data_dict[max(self.data_dict.keys())][0]

    @classmethod
    def add_point(cls, pt: DataPoint, game_pk=-1):
        data = (*pt.values, game_pk)
        try:
            session = cls.objects.get(start_time=pt.session_time_dt)
            current_data = session.data_dict
            current_data[pt.current_time] = data

            last_ts = max(current_data.keys())
            last_dt = dt.datetime.fromtimestamp(last_ts).astimezone(UTC)
            session.end_time = last_dt
            session.duration = last_dt - pt.session_time_dt

            session.max_temp = max(session.max_temp, pt.temperature)
            session.data_points = pickle.dumps(current_data)
            session.save()

            session.update_game_per_session_info()

        except PlaySession.DoesNotExist:
            session = cls.objects.create(
                start_time=pt.session_time_dt,
                end_time=pt.current_time_dt,
                duration=pt.current_time_dt - pt.session_time_dt,
                start_temp=pt.temperature,
                max_temp=pt.temperature,
                data_points=pickle.dumps({pt.current_time: data})
            )
        return session

    def get_time_per_game(self):
        """Return a dict with each game pk as key, and the number
         of seconds as value"""
        d = self.data_dict
        list_of_times = sorted(d.keys())
        res = defaultdict(lambda: 0)
        for t1, t2 in zip(list_of_times, list_of_times[1:]):
            res[d[t1][3]] += (t2 - t1)
        return res

    def update_game_per_session_info(self):
        for game_pk, duration in self.get_time_per_game().items():
            if game_pk == -1:
                continue
            info = GamePerSessionInfo.objects.get_or_create(
                session=self, game=PsGame.objects.get(pk=game_pk))[0]
            info.duration = dt.timedelta(seconds=duration)
            info.save()


class PsGame(models.Model):
    title_id = models.TextField(max_length=12, verbose_name='Title ID')
    name = models.TextField(max_length=2000, verbose_name='Name')
    play_time = models.DurationField(verbose_name='Play time', null=True)
    last_played = models.DateTimeField(verbose_name='Last played',
                                       default=now)

    def __str__(self):
        return f'{self.name}'


class PsnApiKey(models.Model):
    code = models.CharField('npsso code', max_length=100,
                           default='__dummy__')

    def __str__(self):
        return 'PSN npsso code'


class GamePerSessionInfo(models.Model):
    session = models.ForeignKey(PlaySession, on_delete=models.CASCADE)
    game = models.ForeignKey(PsGame, on_delete=models.PROTECT)
    duration = models.DurationField(verbose_name='Duration', null=True)

    def __str__(self):
        return f' "{self.game}" played on "{self.session}"'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        agg = self.game.gamepersessioninfo_set.aggregate(
            Max('session__end_time'), Sum('duration'))
        self.game.play_time = agg['duration__sum']
        self.game.last_played = agg['session__end_time__max']
        self.game.save()

# Reimporting from info log
# import json
# from tempmon.models import *
# with open('../dp', 'r') as f: s=f.read()
# l = s.replace("\'", "").split('\n')
#
# ld = [json.loads(x) for x in l if x]
# for x in ld: del x['API_KEY']
# ldp = [DataPoint(**x) for x in ld]
# for pt in ldp: PlaySession.add_point(pt, PsGame.objec <to check> ts.last().pk)