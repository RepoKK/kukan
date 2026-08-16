import collections
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from django.db.models import Max, Min, Q

import kukan.jautils as jau

from .models import KoukiBushu, Reading


class FFilter(ABC):
    kind = ''
    label = ''
    value = ''

    def __init__(self, label, kind):
        self.kind = kind
        self.label = label
        self.value = ''

    def filter(self, request, qry):
        """An empty value is no filter at all, not a filter matching nothing.

        The Vue bar assembled the query itself and simply left an empty filter
        out, so `add_to_query` never saw one and `if flt is not None` was
        enough. The htmx bar is a real <form>: every chip that is up submits
        its input, empty or not. Under the old guard `種別=` built an empty
        `IN ()` and returned zero rows, so adding a second filter and leaving
        it blank -- or clearing one you had used -- emptied the whole list,
        and `読み=` raised ValueError unpacking four parts out of one.

        Filters that are up but unset are the normal state of the bar, so the
        empty case has to mean "no constraint" here rather than in each of the
        nine `add_to_query` implementations.
        """
        flt = request.GET.get(self.label, None)
        if flt:
            qry = self.add_to_query(flt, qry)
        return qry

    @abstractmethod
    def add_to_query(self, flt, qry):
        pass


class FGenericCheckbox(FFilter):
    def __init__(self, title, field, model, is_two_column=False, order='', none_label='未設定', none_position='end'):
        self.model = model
        self.field = field
        self.nb_col = 2 if is_two_column else 1
        self.order = order if order else field
        self.none_label = none_label
        self.none_position = none_position
        super().__init__(title, 'checkbox')

    def add_to_query(self, flt, qry):
        flt = flt.split(', ')
        kwargs = {self.field + '__in': flt}
        q = Q(**kwargs)
        if self.none_label in flt:
            kwargs = {self.field + '__isnull': True}
            q = q | Q(**kwargs)
        qry = qry.filter(q)
        return qry

    def get_choices(self):
        """The choice list rendered by kukan/templates/ui/filters/checkbox.html."""
        sys_list = [x[self.field] for x in self.model.objects.order_by(self.order).distinct().values(self.field)]
        try:
            sys_list.pop(sys_list.index(None))
            sys_list = [self.none_label, *sys_list] if self.none_position == 'start' else [*sys_list, self.none_label]
        except ValueError:
            pass
        ret = [{'native': idx, 'label': x, 'col': idx % self.nb_col} for idx, x in enumerate(sys_list)]
        return {'comptype': 'b-checkbox', 'elements': ret}



class FGenericMinMax(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'min-max')

    def add_to_query(self, flt, qry):
        flt_fct = qry.filter
        if flt[0:2] == "≠ ":
            flt_fct = qry.exclude
            flt = flt[2:]
        if '~' in flt:
            flt = flt.split('~')
            kwargs = {}
            if flt[0] != '':
                kwargs.update({self.field + '__gte': flt[0]})
            if flt[1] != '':
                kwargs.update({self.field + '__lte': flt[1]})
        else:
            kwargs = {self.field: flt}
        qry = flt_fct(**kwargs)
        return qry


class FGenericDateRange(FFilter):
    def __init__(self, title, field):
        self.field = field
        super().__init__(title, 'daterange')

    def add_to_query(self, flt, qry):
        flt_fct = qry.filter
        if flt[0:2] == "≠ ":
            flt_fct = qry.exclude
            flt = flt[2:]
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
                    end = end + timedelta(days=1)
                kwargs.update({self.field + '__lt': end})
        else:
            date = datetime.strptime(flt + ' +0900', "%Y-%m-%d %z")
            kwargs = {self.field + '__gte': date, self.field + '__lt': date + timedelta(days=1)}
        qry = flt_fct(**kwargs)
        return qry


class FGenericString(FFilter):
    def __init__(self, title, field, lh_criteria='', rh_fct=''):
        self.field = field
        self.lh_criteria = lh_criteria if lh_criteria else self.field + '__contains'
        self.rh_fct = rh_fct if rh_fct else lambda x: x
        super().__init__(title, 'string')

    def add_to_query(self, flt, qry):
        kwargs = {self.lh_criteria: self.rh_fct(flt)}
        qry = qry.filter(**kwargs).distinct()
        return qry


class FGenericYesNo(FFilter):
    def __init__(self, title, field, criteria, label_yes='Yes', label_no='No', inverse=False):
        self.field = field
        self.criteria = criteria
        self.label_yes = label_yes
        self.label_no = label_no
        self.inverse = inverse
        super().__init__(title, 'checkbox')

    def add_to_query(self, flt, qry):
        kwargs = {self.field: self.criteria}
        if (flt == self.label_yes and not self.inverse) or \
                (flt == self.label_no and self.inverse):
            flt_fct = qry.filter
        else:
            flt_fct = qry.exclude
        qry = flt_fct(**kwargs)
        return qry

    def get_choices(self):
        return {'comptype': 'b-radio',
                'elements': [{'native': 0, 'label': self.label_yes, 'col': 0},
                            {'native': 1, 'label': self.label_no, 'col': 0}]}



class FYomiSimple(FFilter):
    def __init__(self, field):
        self.field = field
        super().__init__('読み', 'yomi-simple')

    def add_to_query(self, flt, qry):
        # A hand-shortened or truncated URL -- "?読み=ゆ" -- must not 500 the
        # list page. `parse_yomi` already falls back to the widget's defaults
        # for the same input on the way in; do the same on the way out.
        yomi, _, position = flt.partition('_')
        position = position or '位致'
        yomi = yomi.translate(jau.kat2hir)

        if position == '位始':
            kwargs = {self.field + '__startswith': yomi}
        elif position == '位含':
            kwargs = {self.field + '__contains': yomi}
        else:
            kwargs = {self.field: yomi}

        qry = qry.filter(**kwargs)
        return qry


class FYomi(FFilter):
    def __init__(self):
        super().__init__('読み', 'yomi')

    def add_to_query(self, flt, qry):
        # Padded rather than unpacked, so a hand-shortened or truncated URL --
        # "?読み=ゆ" -- falls back to the widget's own defaults instead of
        # raising ValueError and 500-ing the list page. Matches `parse_yomi`,
        # which does the same for the same input on the way in.
        parts = flt.split('_')
        parts += ['位致', '読両', '常全'][len(parts) - 1:]
        yomi, position, onkun, joyo = parts[:4]
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


class FBushu(FFilter):
    def __init__(self):
        super().__init__('部首', 'bushu')

    def get_choices(self):
        """The radical list rendered by kukan/templates/ui/filters/bushu.html."""
        dct = collections.defaultdict(list)
        for x in KoukiBushu.objects.values_list('bushu', 'kakusu'):
            dct[x[1]].append(x[0])
        return {'listBushu': [{'strokeNumber': k, 'bushu': dct[k]} for k in dct],
                'kakusu': KoukiBushu.objects.aggregate(min=Min('kakusu'), max=Max('kakusu'))}


    def add_to_query(self, flt, qry):
        qry = qry.filter(kouki_bushu__bushu__in=flt)
        return qry
