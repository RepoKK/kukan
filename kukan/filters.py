from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
import kukan.jautils as jau
import json
from django.utils import timezone
from datetime import datetime, timedelta


class FFilter():
    type = ''
    label = ''
    value = ''

    @staticmethod
    def get_filter_context_strings():
        return {
            'FFilter': {
                'transl': {
                    'addfilter': 'ﾌｨﾙﾀｰ追加',
                    'apply': '適用',
                    'value': '値',
                    'selectall': '全選択',
                    'range': '範囲',
                    'exclude': '除く',
                    'time': '時間',
                    'date': '日付',
                    'daterange': '日時範囲',
                    'datestart': '開始',
                    'dateend': '終了',
                },
                'template': {
                    'std': '@apply="handleApply" @rm_fil="rm_fil" :title="title" '
                           ':current_filter="filterDisp" :keep_title="keep_title"'
                }
            }
        }

    def __init__(self, label, type):
        self.type = type
        self.label = label
        self.value = ''

    def toJSON(self):
        return "{'name':'" + self.type + "', "\
               "'label':'" + self.label + "', "\
               "'extra':" + self.get_extra_json() + ", " \
               "'value':'" + self.value + "'}"

    def get_extra_json(self):
        return "{}"

    def filter(self, request, qry):
        flt = request.GET.get(self.label, None)
        if flt is not None:
            qry = self.add_to_query(flt, qry)
        return qry


class FGenericCheckbox(FFilter):
    def __init__(self, title, field, model, is_two_column = False, order='', none_label='未設定', none_position='end'):
        self.model = model
        self.field = field
        self.nb_col = 2 if is_two_column else 1
        self.order = order if order else field
        self.none_label = none_label
        self.none_position = none_position
        super().__init__(title, 'v-filter-checkbox')

    def add_to_query(self, flt, qry):
        flt = flt.split(', ')
        kwargs = {self.field + '__in': flt}
        qry = qry.filter(**kwargs)
        return qry

    def get_extra_json(self):
        sys_list = [x[self.field] for x in self.model.objects.order_by(self.order).distinct().values(self.field)]
        try:
            idx = sys_list.index(None)
            sys_list.pop(sys_list.index(None))
            sys_list = [self.none_label] + sys_list if self.none_position=='start' else sys_list + [self.none_label]
        except ValueError:
            pass
        ret = [{'native': idx, 'label': x, 'col': idx % self.nb_col} for idx, x in enumerate(sys_list)]
        ret = {'comptype': "b-checkbox", 'elements': ret}
        return json.dumps(ret)


class FGenericMinMax(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'v-filter-min-max')

    def add_to_query(self, flt, qry):
        flt_fct = qry.filter
        if flt[0:2] == "≠ ":
            flt_fct = qry.exclude
            flt=flt[2:]
        if '~' in flt:
            flt = flt.split('~')
            kwargs = {}
            if flt[0] != '':
                kwargs.update({self.field + '__gte': flt[0]})
            if flt[1] != '':
                kwargs.update({self.field + '__lte': flt[1]})
        else:
            kwargs = {self.field : flt}
        qry = flt_fct(**kwargs)
        return qry


class FGenericDateRange(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'v-filter-daterange')

    def add_to_query(self, flt, qry):
        flt_fct = qry.filter
        if flt[0:2] == "≠ ":
            flt_fct = qry.exclude
            flt=flt[2:]
        if '~' in flt:
            flt = flt.split('~')
            kwargs = {}
            if flt[0] != '':
                try:
                    start = datetime.strptime(flt[0] + ' +0900', "%Y-%m-%d %H:%M %z")
                except ValueError:
                    start = datetime.strptime(flt[0] + ' +0900', "%Y-%m-%d %z")
                kwargs.update({self.field + '__gte': start})
            if flt[1] != '':
                try:
                    end = datetime.strptime(flt[1] + ' +0900', "%Y-%m-%d %H:%M %z")
                except ValueError:
                    end = datetime.strptime(flt[1] + ' +0900', "%Y-%m-%d %z")
                    end = end+timedelta(days=1)
                kwargs.update({self.field + '__lt': end})
        else:
            date=datetime.strptime(flt + ' +0900', "%Y-%m-%d %z")
            kwargs = {self.field + '__gte': date, self.field + '__lt': date+timedelta(days=1)}
        qry = flt_fct(**kwargs)
        return qry


class FGenericString(FFilter):
    def __init__(self, title, field, lh_criteria='', rh_fct=''):
        self.field = field
        self.lh_criteria = lh_criteria if lh_criteria else self.field + '__contains'
        self.rh_fct = rh_fct if rh_fct else lambda x :x
        super().__init__(title, 'v-filter-string')

    def add_to_query(self, flt, qry):
        kwargs = {self.lh_criteria:self.rh_fct(flt)}
        qry = qry.filter(**kwargs).distinct()
        return qry


class FGenericYesNo(FFilter):
    def __init__(self, title, field, criteria, label_yes='Yes', label_no='No', inverse=False):
        self.field = field
        self.criteria = criteria
        self.label_yes = label_yes
        self.label_no = label_no
        self.inverse = inverse
        super().__init__(title, 'v-filter-checkbox')

    def add_to_query(self, flt, qry):
        kwargs = {self.field: self.criteria}
        flt_fct = qry.exclude if self.inverse else qry.filter
        if (flt == self.label_yes and not self.inverse) or \
                (flt == self.label_no and self.inverse):
            flt_fct = qry.filter
        else:
            flt_fct = qry.exclude
        qry = flt_fct(**kwargs)
        return qry

    def get_extra_json(self):
        ret = {'comptype': "b-radio",
               'elements': [{'native': 0, 'label': self.label_yes, 'col': 0},
                            {'native': 1, 'label': self.label_no,  'col': 0}]}
        return json.dumps(ret)


class FYomi(FFilter):
    def __init__(self):
        super().__init__('読み', 'v-filter-yomi')

    def add_to_query(self, flt, qry):
        yomi, position, onkun, joyo = flt.split('_')
        yomi = yomi.translate(jau.kat2hir)
        readings = Reading.objects.all()

        # Filter position yomi
        if position == '位始':
            readings = readings.filter(reading_simple__startswith=yomi)
        elif position == '位含':
            readings = readings.filter(reading_simple__contains=yomi)
        else:
            readings = readings.filter(reading_simple=yomi)

        # Filter on/kun yomi
        if onkun == '読音':
            readings = readings.filter(yomi_type__yomi_type='音')
        if onkun == '読訓':
            readings = readings.filter(yomi_type__yomi_type='訓')

        # Filter yojo
        if joyo == '常用':
            readings = readings.exclude(joyo__yomi_joyo='表外')
        if joyo == '常外':
            readings = readings.filter(joyo__yomi_joyo='表外')

        qry = qry.filter(reading__in=readings)
        return qry
