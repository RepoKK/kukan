import pickle
from dataclasses import dataclass

from django.db import models
import datetime as dt
from datetime import UTC


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
            session.end_time = pt.current_time_dt
            session.duration = pt.current_time_dt - pt.session_time_dt
            session.max_temp = max(session.max_temp, pt.temperature)
            session.data_points = pickle.dumps(current_data)
            session.save()

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


class PsGame(models.Model):
    title_id = models.TextField(max_length=12, verbose_name='Title ID')
    name = models.TextField(max_length=2000, verbose_name='Name')

    def __str__(self):
        return f'{self.name}'


class PsnApiKey(models.Model):
    code = models.CharField('npsso code', max_length=100,
                           default='__dummy__')

    def __str__(self):
        return 'PSN npsso code'
