import datetime as dt
import logging
import math
import re
import urllib.request
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

logger = logging.getLogger(__name__)

# Every time in this module is a Tokyo wall-clock time: the timetable, the
# realtime feed and the "is it hot" window are all published in JST. The host's
# own clock is never the right reference — see the comments at each use.
JST = ZoneInfo('Asia/Tokyo')


def get_bus_time(url, station, line, direction):
    page = urllib.request.urlopen(url).read().decode()
    df_all = pd.read_html(StringIO(page))
    today_type = re.search('(..)ダイヤ</a>で運行しております。',
                           page)[1]

    list_times = []

    for df in df_all:
        header = {re.sub('\\.[0-9]+', '', str(c))
                  for c in df.columns if c != '時'}
        if header == {f'【{station}】 {line} {direction}行（{today_type}）'}:

            # now(tz), not now().replace(tzinfo=tz): the latter takes the
            # system-local wall clock and merely relabels it as JST. On a
            # UTC-clocked host that is nine hours early, so the page lists
            # buses that departed hours ago. Production happens to run on a
            # JST clock, which is why this was invisible there.
            now = dt.datetime.now(JST)

            df = (df.set_index('時')
                  .dropna(axis='index', how='all')
                  .dropna(axis='columns', how='all')
                  .replace('[^0-9]', '', regex=True)
                  .astype(float))

            for r in df.iterrows():
                hour = r[0]
                for minute in r[1]:
                    if math.isnan(minute):
                        continue
                    # The timetable is a JST wall clock, so the date it is
                    # combined with must be today *in Tokyo*, not the host's
                    # local date.
                    bus_time = dt.datetime.combine(
                        now.date(), dt.time(hour, int(minute)), tzinfo=JST)
                    if bus_time > now:
                        list_times.append(bus_time)
    return list_times


NO_REALTIME_INFO = (-1, '-')


def get_realtime_status():
    """(stops away, minutes to wait) for the next 新宿駅西口-bound bus.

    `(-1, '-')` means the feed had nothing approaching. `(0, 0)` means
    まもなく -- the page says a bus is imminent and gives no minute count.
    """
    url = 'https://tobus.jp/blsys/navi?LCD=&VCD=cresultrsi&ECD=aprslt&slst=1235'
    page = requests.get(
        url,
        headers={'Cache-Control': 'max-age=0'}
    ).content.decode('UTF-8')

    status = pd.read_html(StringIO(page))[2]
    is_soon = status.iloc[0, 1] == '新宿駅西口行まもなく'
    time_list = status.iloc[0].str.extract(r'新宿駅西口行([0-9]+)分待').dropna()

    if is_soon:
        return 0, 0
    try:
        return int(time_list.iloc[0].name / 2), f'{int(time_list.iloc[0][0])}'
    except IndexError:
        return NO_REALTIME_INFO


# bustime is a personal bus timetable with no user data, and is deliberately
# reachable without logging in. LoginRequiredMiddleware denies by default, so
# that has to be stated rather than assumed.
@login_not_required
def get_time_to_next_hana(request):
    """The realtime panel, as an HTML fragment htmx polls every 10 seconds.

    It used to return JSON for the Vue page to render, with the failure case
    handled by an `axios.catch` that set the "no info" sentinel. htmx has no
    equivalent -- a 500 just leaves the previous fragment on screen -- and a
    tobus.jp outage would otherwise log a traceback every ten seconds for
    every open tab. So the scrape failing is the same "no info" state the
    feed itself reports when nothing is approaching.
    """
    try:
        bus_stop, bus_wait = get_realtime_status()
    except Exception as e:
        logger.warning(f'Realtime bus lookup failed, showing no info: {e}')
        bus_stop, bus_wait = NO_REALTIME_INFO

    return render(request, 'bustime/_realtime.html', {
        'real_next_bus_stop': bus_stop,
        'real_next_bus_wait': bus_wait,
    })


@method_decorator(login_not_required, name='dispatch')
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
        # Epoch milliseconds for the Alpine countdown, which needs to compare
        # departures against the *browser's* clock -- a JST-formatted string
        # would be a wall-clock time in an unstated zone.
        context['departure_times_ms'] = [
            int(t.timestamp() * 1000) for t in context['list_times']]
        context['busStopMain'] = {'name': stationMain,
                                  'class': class_main}
        context['busStopOther'] = {'name': stationOther,
                                   'class': class_other}
        # Only 花園町 has a realtime feed; the Vue page expressed this by
        # simply never starting the poller on the other stop.
        context['has_realtime'] = stationMain == '花園町'
        # Tokyo's month, not the host's: on a UTC clock the last nine hours of
        # 30 September are still September locally but already October in JST.
        context['hot_day'] = 6 < dt.datetime.now(JST).month < 10
        return context

