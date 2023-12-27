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
    objects = None
    DoesNotExist = None
    start_time = models.DateTimeField(verbose_name='Start time')
    end_time = models.DateTimeField(verbose_name='End time')
    start_temp = models.FloatField(verbose_name='Starting temperature')
    max_temp = models.FloatField(verbose_name='Max temperature')
    data_points = models.BinaryField(verbose_name='Data points')

    def __str__(self):
        return f'{self.start_time}'

    @property
    def data_dict(self):
        return pickle.loads(self.data_points)

    @classmethod
    def add_point(cls, pt: DataPoint):
        try:
            session = cls.objects.get(start_time=pt.session_time_dt)
            current_data = session.data_dict
            current_data[pt.current_time] = pt.values
            session.end_time = pt.current_time_dt
            session.max_temp = max(session.max_temp, pt.temperature)
            session.data_points = pickle.dumps(current_data)
            session.save()

        except PlaySession.DoesNotExist:
            session = cls.objects.create(
                start_time=pt.session_time_dt,
                end_time=pt.current_time_dt,
                start_temp=pt.temperature,
                max_temp=pt.temperature,
                data_points=pickle.dumps({pt.current_time: pt.values})
            )
        return session
