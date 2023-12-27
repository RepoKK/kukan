import json
import logging

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, DetailView

from kukan.filters import FGenericDateRange, FGenericMinMax
from kukan.views import AjaxList, TableData
from tempmon.models import PlaySession, DataPoint

logger = logging.getLogger(__name__)


@csrf_exempt
def add_temp_point(request):
    try:
        logger.info(f'New add_temp_point request, body: {request.body}')
        body = json.loads(request.body)

        if body.pop('API_KEY', None) != settings.TEMPMON_API_KEY:
            return JsonResponse({'result': f'Failure - wrong API_KEY'})

        pt = DataPoint(**body)
        print(pt)
        sess = PlaySession.add_point(pt)
        print(sess.data_dict)

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = context['object']
        context['duration'] = session.end_time - session.start_time
        context['temp_data'] = [
            {'x': (k - session.start_time.timestamp())/60, 'y': pt[0]}
            for k, pt in session.data_dict.items()
        ]
        return context
