import datetime
import datetime as dt
import re
import urllib.request
from io import StringIO

import numpy as np
import pandas as pd
import pytz
import requests
from django.http import JsonResponse
from django.views.generic import TemplateView


def get_bus_time(url, station, line, direction):
    page = urllib.request.urlopen(url).read().decode()
    df_all = pd.read_html(StringIO(page))
    today_type = re.search('(..)ダイヤ</a>で運行しております。',
                           page)[1]

    tz = pytz.timezone('Asia/Tokyo')
    list_times = []

    for df in df_all:
        header = {re.sub('\\.[0-9]+', '', str(c))
                  for c in df.columns if c != '時'}
        if header == {f'【{station}】 {line} {direction}行（{today_type}）'}:

            now = tz.localize(dt.datetime.now())

            df = (df.set_index('時')
                  .dropna(axis='index', how='all')
                  .dropna(axis='columns', how='all')
                  .replace('[^0-9]', '', regex=True)
                  .astype(float))

            for r in df.iterrows():
                hour = r[0]
                for minute in r[1]:
                    if np.isnan(minute):
                        continue
                    bus_time = tz.localize(
                        dt.datetime.combine(dt.date.today(),
                                            dt.time(hour, int(minute)))
                    )
                    if bus_time > now:
                        list_times.append(bus_time)
    return list_times


def get_time_to_next_hana(_):
    url = 'https://tobus.jp/blsys/navi?LCD=&VCD=cresultrsi&ECD=aprslt&slst=1235'
    page = requests.get(
        url,
        headers={'Cache-Control': 'max-age=0'}
    ).content.decode('UTF-8')

    status = pd.read_html(StringIO(page))[2]
    is_soon = status.iloc[0, 1] == '新宿駅西口行まもなく'
    time_list = status.iloc[0].str.extract(r'新宿駅西口行([0-9]+)分待').dropna()

    if is_soon:
        bus_stop = 0
        bus_wait = 0
    else:
        try:
            bus_stop = int(time_list.iloc[0].name / 2)
            bus_wait = f'{int(time_list.iloc[0][0])}'
        except IndexError:
            bus_stop = -1
            bus_wait = '-'

    return JsonResponse({
        'real_next_bus_stop': bus_stop,
        'real_next_bus_wait': bus_wait,
    })


class BusTimeMain(TemplateView):
    template_name = "bustime/bustime_main.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stationMain = self.request.GET.get('station', '新宿駅西口')
        from_shinjuku = stationMain == '新宿駅西口'
        stationOther = '花園町' if from_shinjuku else '新宿駅西口'

        if from_shinjuku:
            url = 'https://tobus.jp/blsys/navi?LCD=&VCD=cresultttbl&ECD=show' \
                  '&slst=702&pl=8&RTMCD=122&lrid=2&tgo=1'
            class_main = 'is-info'
            class_other = 'is-success'
        else:
            url = 'https://tobus.jp/blsys/navi?LCD=&VCD=cresultttbl&ECD=show' \
                  '&slst=1235&pl=1&RTMCD=122&lrid=1&tgo=1'
            class_main = 'is-success'
            class_other = 'is-info'

        line = '白６１'
        direction = '練馬駅・練馬車庫前' if from_shinjuku else '新宿駅西口'
        context['list_times'] = get_bus_time(url, stationMain, line, direction)
        context['busStopMain'] = {'name': stationMain,
                                  'class': class_main}
        context['busStopOther'] = {'name': stationOther,
                                   'class': class_other}
        context['hot_day'] = 6 < datetime.datetime.now().month < 10
        return context

