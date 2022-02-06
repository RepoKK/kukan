from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

import urllib.request

import numpy as np
import pandas as pd
import datetime as dt
import re

import pytz


def get_bus_time(url, station, line, direction):
    page = urllib.request.urlopen(url)
    df_all = pd.read_html(url)
    today_type = re.search('(..)ダイヤ</a>で運行しております。',
                           page.read().decode())[1]

    tz = pytz.timezone('Asia/Tokyo')
    list_times = []

    for df in df_all:
        print(df)
        header = {re.sub('\.[0-9]+', '', str(c))
                  for c in df.columns if c != '時'}
        print(header)
        print(f'【{station}】 {line} {direction}行（{today_type}）')
        if header == {f'【{station}】 {line} {direction}行（{today_type}）'}:
            print('IN RIGHT DF')

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


class BusTimeMain(LoginRequiredMixin, TemplateView):
    template_name = "bustime/bustime_main.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        url = 'https://tobus.jp/blsys/navi?LCD=&VCD=SelectDest&ECD=SelectDest' \
              '&slst=702&pl=8&RTMCD=122'
        station = '新宿駅西口'
        line = '白６１'
        direction = '練馬駅・練馬車庫前'
        context['list_times'] = get_bus_time(url, station, line, direction)
        context['list_times']
        return context

