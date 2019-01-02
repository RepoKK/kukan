import time
from collections import defaultdict, deque
from functools import reduce

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage
from django.db.models import Count
from django.http import JsonResponse
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import generic
from django.views.generic.base import TemplateView
from django.views.generic.edit import CreateView, UpdateView, DeleteView

from kukan.exporting import ExporterAsResp
from kukan.jautils import JpText, JpnText
from kukan.onlinepedia import DefinitionWordBase
from .filters import *
from .forms import SearchForm, ExampleForm, ExportForm, KotowazaForm
from .models import Kanji, Reading, Example, ExMap, Yoji, TestResult, Kotowaza


class Index(LoginRequiredMixin, generic.FormView):
    template_name = 'kukan/index.html'
    form_class = SearchForm

    def form_valid(self, form):
        search = form.cleaned_data['search']
        if 'yoji' in self.request.POST:
            self.success_url = reverse('kukan:yoji_list')
            if search != '':
                self.success_url += '?漢字=' + search + '&Anki=Anki'
        elif 'kotowaza' in self.request.POST:
            self.success_url = reverse('kukan:kotowaza_list')
            if search != '':
                self.success_url += '?諺=' + search
        elif 'example' in self.request.POST:
            self.success_url = reverse('kukan:example_list')
            if search != '':
                self.success_url += '?単語=' + search
        else:
            self.success_url = reverse('kukan:kanji_list')
            if search != '':
                if len(search) == 1 and Kanji.objects.filter(kanji=search).exists():
                    self.success_url = reverse('kukan:kanji_detail', args=search)
                elif search.translate(jau.kat2hir).translate(jau.hir2nul) == '':
                    self.success_url += '?読み=' + search + '_位始_読両_常全'
                else:
                    self.success_url += '?漢字=' + search
        return super().form_valid(form)

    def get_success_url(self):
        return self.success_url


class StatsPage(LoginRequiredMixin, TemplateView):
    template_name = "kukan/stats.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data_list = []
        data = {'cat': '漢字', 'total': Kanji.objects.all().count(),
                'joyo': Kanji.objects.filter(classification__classification='常用漢字').count(),
                'non_joyo': Kanji.objects.exclude(classification__classification='常用漢字').count()}
        data_list.append(data.copy())
        data = {'cat': '総合読み', 'total': Reading.objects.all().count(),
                'joyo': Reading.objects.exclude(joyo__yomi_joyo='表外').count(),
                'non_joyo': Reading.objects.filter(joyo__yomi_joyo='表外').count()}
        data_list.append(data.copy())
        data['cat'] = '音読み'
        yomi_filter = Reading.objects.filter(yomi_type__yomi_type='音')
        data['total'] = yomi_filter.count()
        data['joyo'] = yomi_filter.exclude(joyo__yomi_joyo='表外').count()
        data['non_joyo'] = yomi_filter.filter(joyo__yomi_joyo='表外').count()
        data_list.append(data.copy())
        yomi_filter = Reading.objects.filter(yomi_type__yomi_type='訓')
        data['cat'] = '訓読み'
        data['total'] = yomi_filter.count()
        data['joyo'] = yomi_filter.exclude(joyo__yomi_joyo='表外').count()
        data['non_joyo'] = yomi_filter.filter(joyo__yomi_joyo='表外').count()
        data_list.append(data.copy())
        data['cat'] = '例文'
        data['total'] = Example.objects.all().count()
        data['joyo'] = 0
        data['non_joyo'] = 0
        data_list.append(data.copy())
        context['stats_table_data'] = json.dumps(data_list)
        return context


class TableData:
    class FieldProps:
        def __init__(self, model, in_props):
            # Default properties
            self.props = {
                'field': in_props['name'],
                'label': in_props['name'],
                'link': None,
                'type': in_props.get('type', ''),
                'format': self.std_str,
                'visible': True
            }
            self.get_choice_display = None
            if in_props['name'] in [x.name for x in model._meta.get_fields()]:
                fld = model._meta.get_field(in_props['name'])
                if self.props['type'] == '':
                    var_type = ''
                    if fld.get_internal_type() == 'BooleanField':
                        var_type = 'bool'
                    elif fld.get_internal_type() in 'IntegerField FloatField':
                        var_type = 'numeric'
                    self.props.update({'type': var_type})

                choices_list = getattr(fld, 'choices', None)
                if choices_list is not None:
                    self.get_choice_display = {x: y for x, y in choices_list}

                self.props.update({
                    'label': fld.verbose_name if fld.verbose_name != '' else fld.name,
                    'format': self.format_identical if fld.get_internal_type() == 'BooleanField' else self.std_str,
                })
            # Override with input dict properties
            self.props.update(in_props)
            self.link_fn = self.props.pop('link')
            self.format_fld = self.props.pop('format')

        def get_props_dict(self):
            return self.props

        def format(self, obj):
            value = reduce(lambda x, y: getattr(x, y), self.props['field'].split('__'), obj)
            value = self.format_fld(value)
            if self.get_choice_display:
                value = self.get_choice_display[value]
            if self.link_fn is not None:
                value = '<a href="' + self.link_fn(obj) + '/">' + str(value) + '</a>'
            return self.props['field'], value

        def add_link(self, obj):
            return 'link', self.link_fn(obj) if self.link_fn is not None else ''

        @staticmethod
        def std_str(var):
            return '' if var is None else str(var)

        @staticmethod
        def format_identical(var):
            return var

        @staticmethod
        def format_datetime_min(datetime_var):
            class_date = timezone.localtime(datetime_var)
            return class_date.strftime("%Y.%m.%d %H:%M")

        @staticmethod
        def format_date(datetime_var):
            # class_date = timezone.localtime(datetime_var)
            return datetime_var.strftime("%Y.%m.%d")

        @staticmethod
        def link_pk(base):
            return lambda obj: '/' + base + '/' + str(obj.pk)

    def __init__(self, model, table_fields):
        self.model = model
        self._field_prop_list = []
        for fld in table_fields:
            if type(fld) is str:
                fld = {'name': fld}
            self._field_prop_list.append(self.FieldProps(model, fld))

    def get_col_template(self):
        return [x.get_props_dict() for x in self._field_prop_list]

    def get_table_row(self, obj):
        return {x[0]: x[1] for x in [y.format(obj) for y in self._field_prop_list]}

    def get_table_data(self, lst):
        return [self.get_table_row(obj) for obj in lst]

    def get_table_full(self, lst):
        return {'columns': self.get_col_template(), 'data': self.get_table_data(lst)}


class AjaxList(LoginRequiredMixin, generic.TemplateView):
    model = None
    table_data = None
    default_sort = None
    filters = None
    list_title = 'LIST_TITLE'
    is_mobile_card = True

    def __init__(self):
        super().__init__()
        self.object_counter = '件'

    def dispatch(self, request, *args, **kwargs):
        if request.method.lower() == 'get' and request.GET.get('ajax', None) == '1':
            handler = self.get_list
        else:
            handler = super().dispatch
        return handler(request, *args, **kwargs)

    def get_list(self, request):
        page = request.GET.get('page', 1)
        sort_by = request.GET.get('sort_by', self.default_sort)
        table_data = {'page': int(page), 'sort_by': sort_by, 'columns': '', 'data': []}
        start_time = time.time()
        qry = self.get_filtered_list(request)

        try:
            p = Paginator(qry.order_by(sort_by), 20, allow_empty_first_page=True)
            table_data.update(self.table_data.get_table_full(p.page(page).object_list))
            end_time = time.time()
            data = {'total_results': p.count, 'table_data': table_data,
                    'stats': self.get_stats(qry, p, start_time, end_time)}
            data.update(self.get_extra_json(p, page, qry))
        except EmptyPage:
            data = {'total_results': 0, 'table_data': table_data, 'stats': '0 ' + self.object_counter}

        return JsonResponse(data)

    # noinspection PyUnusedLocal,PyMethodMayBeStatic
    def get_extra_json(self, p, page, qry):
        return {}

    # noinspection PyUnusedLocal
    def get_stats(self, qry, p, start_time, end_time):
        return [str(p.count) + ' ' + self.object_counter,
                'Q:' + '{:d}'.format(int((end_time - start_time)*1000))]

    def get_filtered_list(self, request):
        qry = self.model.objects.all()
        for flt in self.filters:
            qry = flt.filter(request, qry)
        return qry

    def get_context_data(self, **kwargs):
        filter_list = ""
        for flt in self.filters:
            flt.value = self.request.GET.get(flt.label, '')
            filter_list += flt.to_json() + ",\n"
        filter_list = "[" + filter_list + "]"

        flt_order = []
        for flt in self.filters:
            flt_order.append(flt.label)

        active_filters = []
        for f_req in self.request.GET:
            try:
                idx = flt_order.index(f_req)
                if idx > -1:
                    active_filters.append(idx)
            except ValueError:
                pass

        context = super().get_context_data(**kwargs)
        context['filter_list'] = filter_list
        context.update(FFilter.get_filter_context_strings())
        context['active_filters'] = active_filters

        page = self.request.GET.get('page', 1)
        sort_by = self.request.GET.get('sort_by', self.default_sort)
        context['table_data'] = json.dumps({'page': int(page), 'sort_by': sort_by, 'columns': '', 'data': []})

        context['list_title'] = self.list_title
        context['is_mobile_card'] = self.is_mobile_card

        return context


class KanjiListFilter(AjaxList):
    model = Kanji
    template_name = 'kukan/default_list.html'
    default_sort = 'kanken'
    list_title = '漢字'
    is_mobile_card = False
    filters = [
        FGenericString('漢字', 'kanji', 'kanji__in', list),
        FYomi(),
        FBushu(),
        FGenericMinMax('画数', 'strokes'),
        FGenericCheckbox('種別', 'classification__classification', model,
                         order='-classification__classification', none_label='常用・人名以外'),
        FGenericCheckbox('JIS水準', 'jis__level', model, none_label='JIS水準不明'),
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericMinMax('例文数', 'ex_num'),
    ]
    table_data = TableData(model, [
        {'name': 'kanji', 'link': TableData.FieldProps.link_pk('kanji')},
        {'name': 'kouki_bushu', 'format': lambda x: str(x)[0]},
        'kanken', 'strokes', 'classification',
        {'name': 'ex_num', 'label': '例文数'},
    ])

    def get_filtered_list(self, request):
        val_ex = Count('exmap', filter=~Q(exmap__example__sentence=''))
        qry = Kanji.objects.annotate(ex_num=val_ex)

        for flt in self.filters:
            qry = flt.filter(request, qry)

        return qry


class YojiList(AjaxList):
    model = Yoji
    template_name = 'kukan/yoji_list.html'
    default_sort = 'kanken'
    filters = [
        FGenericString('漢字', 'yoji'),
        FGenericString('分類', 'bunrui__bunrui'),
        FYomiSimple('reading'),
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericYesNo('日課', 'in_anki', True, '日課に出る', '日課に出ない'),
    ]
    table_data = TableData(model, [
        {'name': 'yoji', 'link': TableData.FieldProps.link_pk('yoji')},
        'reading', 'kanken', 'in_anki'
    ])


class ExampleList(AjaxList):
    model = Example
    template_name = 'kukan/default_list.html'
    default_sort = 'kanken'
    list_title = '例文'
    filters = [
        FGenericString('単語', 'word'),
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericCheckbox('種類', 'ex_kind', model),
        FGenericYesNo('例文', 'sentence', '', '例文有り', '例文無し', True),
        FGenericDateRange('作成', 'created_time'),
        FGenericDateRange('変更', 'updated_time'),
        FGenericString('意味', 'definition'),
    ]
    table_data = TableData(model, [
        {'name': 'word', 'link': TableData.FieldProps.link_pk('example')},
        'yomi', 'sentence', 'kanken', 'is_joyo', 'ex_kind',
        {'name': 'updated_time', 'format': TableData.FieldProps.format_datetime_min}
    ])


class KotowazaList(AjaxList):
    model = Kotowaza
    template_name = 'kukan/default_list.html'
    default_sort = 'kotowaza'
    list_title = '諺'
    filters = [
        FGenericString('諺', 'kotowaza'),
    ]
    table_data = TableData(model, [
        {'name': 'kotowaza', 'link': TableData.FieldProps.link_pk('kotowaza')},
        'yomi'
    ])


class TestResultList(AjaxList):
    model = TestResult
    template_name = 'kukan/test_result_list.html'
    default_sort = 'date'
    filters = [
        FGenericCheckbox('名前', 'name', model),
        FGenericCheckbox('漢検', 'kanken__kyu', model, order='-kanken__difficulty'),
        FGenericDateRange('日付', 'date'),
    ]
    table_data = TableData(model, [
        {'name': 'name'},
        'kanken',
        'item_01', 'item_02', 'item_03', 'item_04', 'item_05', 'item_06', 'item_07', 'item_08', 'item_09', 'item_10',
        'score',
        'test_source', 'test_number',
        {'name': 'date', 'format': TableData.FieldProps.format_date}
    ])


class KanjiDetail(LoginRequiredMixin, generic.DetailView):
    model = Kanji
    table_data = {'例文': TableData(Example, [
                                    {'name': 'word', 'link': TableData.FieldProps.link_pk('example')},
                                    'yomi', 'sentence', 'kanken', 'ex_kind', 'is_joyo']),
                  '四字熟語': TableData(Yoji, [
                                    {'name': 'yoji', 'link': TableData.FieldProps.link_pk('yoji')},
                                    'reading', 'kanken', 'in_anki']),
                  '諺': TableData(Example, [
                      {'name': 'word', 'link': TableData.FieldProps.link_pk('example')},
                      'yomi', 'sentence', 'kanken']),
                  }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qry = {'例文': Example.objects.filter(word__contains=context['kanji']
                                            ).exclude(sentence='').exclude(ex_kind=Example.KOTOWAZA),
               '四字熟語': Yoji.objects.filter(yoji__contains=context['kanji']),
               '諺': Example.objects.filter(word__contains=context['kanji'], ex_kind=Example.KOTOWAZA)}
        context['ctx'] = json.dumps(
            [{'name': k, 'number': qry[k].count(), 'table_data': v.get_table_full(qry[k])}
             for k, v in self.table_data.items() if qry[k].count() > 0]
        )
        return context


class YojiDetail(LoginRequiredMixin, generic.DetailView):
    model = Yoji


class KotowazaDetail(LoginRequiredMixin, generic.DetailView):
    model = Kotowaza


class KotowazaCreate(LoginRequiredMixin, CreateView):
    template_name = 'kukan/example_update.html'
    model = Kotowaza
    form_class = KotowazaForm
    context_object_name = 'kotowaza'


class KotowazaUpdate(LoginRequiredMixin, UpdateView):
    template_name = 'kukan/kotowaza_update.html'
    model = Kotowaza
    form_class = KotowazaForm
    context_object_name = 'kotowaza'


class ExampleDetail(LoginRequiredMixin, generic.DetailView):
    model = Example


class ExampleCreate(LoginRequiredMixin, CreateView):
    template_name = 'kukan/example_update.html'
    model = Example
    form_class = ExampleForm
    context_object_name = 'example'


class ExampleUpdate(LoginRequiredMixin, UpdateView):
    template_name = 'kukan/example_update.html'
    model = Example
    form_class = ExampleForm
    context_object_name = 'example'


class ExampleDelete(LoginRequiredMixin, DeleteView):
    model = Example
    success_url = reverse_lazy('kukan:example_list')


@login_required
def yoji_anki(request):
    operation = request.POST.get('op', None)
    req_yoji = request.POST.get('yoji', None)
    status = 'failed'
    in_anki = ''
    if operation in ['add', 'remove']:
        try:
            yoji = Yoji.objects.get(yoji=req_yoji)
            yoji.in_anki = True if operation == 'add' else False
            yoji.save()
            status = 'success'
            in_anki = 'true' if yoji.in_anki else 'false'
        except Yoji.DoesNotExist:
            status = 'failed'

    data = {'status': status, 'in_anki': in_anki}
    return JsonResponse(data)


@login_required
def get_yomi(request):
    word = request.GET.get('word_native', None)
    if word is None or word == '':
        word = request.GET.get('word', None)
    ex_id = request.GET.get('ex_id', None)
    readings_input = request.GET.get('reading_selected', None)
    kj_readings = defaultdict(deque)

    if readings_input.replace(',', '') != '':
        for reading_pk in readings_input.split(','):
            if reading_pk[:6] == 'Ateji_':
                kj_readings[reading_pk[-1]].append((ExMap.ateji_option_disp, reading_pk))
            elif reading_pk != '':
                reading_obj = Reading.objects.get(id=reading_pk)
                kj_readings[Kanji.objects.get(reading=reading_pk).kanji].append((reading_obj.reading, reading_obj.pk))
    elif ex_id != '':
        for ex_map in ExMap.objects.filter(example__pk=ex_id).order_by('map_order'):
            if ex_map.is_ateji:
                kj_readings[ex_map.kanji.kanji].append((ExMap.ateji_option_disp, 'Ateji_' + ex_map.kanji.kanji))
            else:
                kj_readings[ex_map.kanji.kanji].append((ex_map.reading.reading, ex_map.reading.pk))

    joyo_members = {e.map_order: e
                    for e in ExMap.objects.filter(example__pk=ex_id or -1, in_joyo_list=True).order_by('map_order')}

    readings_output = []
    list_of_reading_data = []
    for idx, kj in enumerate(word):
        try:
            kanji = Kanji.objects.get(kanji=kj)
        except Kanji.DoesNotExist:
            continue
        reading_data = {
            'kanji': kj, 'kyu': kanji.kanken.kyu,
            'example_num': kanji.exmap_set.exclude(example__sentence='').count(),
            'readings': [{'key': 'Ateji_' + kj, 'read': ExMap.ateji_option_disp}] +
                        [{'key': x.id, 'read': x.get_full()} for x in Reading.objects.filter(kanji=kj)]
        }
        try:
            reading = kj_readings[kj].popleft()
            reading_data['selected'] = reading[0]
            readings_output.append(reading[1])
        except IndexError:
            reading_data['selected'] = None
            readings_output.append(None)

        ex_map_in_joyo = joyo_members.get(idx, None)
        if ex_map_in_joyo:
            r = ExMap.ateji_option_disp if ex_map_in_joyo.is_ateji else ex_map_in_joyo.reading.reading
            if r != reading_data['selected'] or ex_map_in_joyo.kanji.kanji != kj:
                raise ValueError('Readings in Joyo list are invariant')
            reading_data['joyo'] = True
        else:
            reading_data['joyo'] = False

        list_of_reading_data.append(reading_data)

    data = {'reading_selected': readings_output, 'reading_data': list_of_reading_data}
    return JsonResponse(data)


@login_required
def set_yomi(request):
    word = request.GET.get('word', None)
    word_native = request.GET.get('word_native', None)
    if word_native is not None and word_native != '':
        word = word_native
    yomi = request.GET.get('yomi', None)
    yomi = yomi.translate(jau.hir2kat)

    lst_reading = []
    lst_id = []
    for kj in word:
        readings = [x.reading.translate(jau.hir2kat).translate({ord(c): None for c in '（）'})
                    for x in Reading.objects.filter(kanji=kj)]
        if readings:
            lst_reading.append(readings)
            lst_id.append([x.id for x in Reading.objects.filter(kanji=kj)])

    candidate = reduce(lambda a, b: [x + y for x in a for y in b], lst_reading)
    candidate_id = reduce(lambda a, b: [([x] if isinstance(x, int) else x) + [y] for x in a for y in b], lst_id)
    data = {'candidate': None}
    if yomi in candidate:
        idx = candidate.index(yomi)
        ids = candidate_id[idx]
        # For the case there's only one element - will not be included in a list, so add it here
        if not type(ids) is list:
            ids = [ids]
        data = {'candidate': ids}
    return JsonResponse(data)


@login_required
def get_similar_word(request):
    word = request.GET.get('word', None)
    ex_id = request.GET.get('ex_id', None) or None
    qry_sim = Example.objects.filter(word__contains=word).exclude(id=ex_id)
    sim_count = qry_sim.count()
    if sim_count > 0:
        str_more = '、...' if sim_count > 5 else ''
        sim_word = ['単語を含む既存の例文（{}件）：'.format(sim_count),
                    '、'.join([x.word + ('（' + x.yomi + '）' if x.yomi != '' else '')
                              for x in qry_sim[:5]]) + str_more]
    else:
        sim_word = []

    data = {'word_notifications': {'items': sim_word, 'type': 'is-info'},
            'info_similar_word': sim_word}
    return JsonResponse(data)


@login_required
def get_goo(request):
    word = request.GET.get('word_native', None)
    if word == '':
        word = request.GET.get('word', None)
    link = request.GET.get('link', None)

    if link:
        definition_word = DefinitionWordBase.from_link(link)
    else:
        definition_word = DefinitionWordBase.from_word(word)

    if definition_word:
        definition, yomi, candidates = definition_word.get_definition()
    else:
        definition, yomi, candidates = None, None, []

    data = {'definition': definition, 'reading': yomi, 'candidates': candidates if len(candidates) > 0 else ''}

    return JsonResponse(data)


@login_required
def get_furigana(request):
    if request.GET.get('format', None) == 'bracket':
        return JsonResponse({
            'furigana': JpnText.from_simple_text(request.GET.get('word', '')).furigana() or '[||f]'
        })
    else:
        text = JpText(request.GET.get('word', None), request.GET.get('yomi', None))
        return JsonResponse({
            'furigana': text.guess_furigana(),
            'furigana_notifications': {'items': text.get_furigana_errors(), 'type': 'is-warning'},
        })


class ExportView(LoginRequiredMixin, generic.FormView):
    template_name = 'kukan/export.html'
    form_class = ExportForm
    success_url = reverse_lazy('kukan:export')

    def render_to_response(self, context, **response_kwargs):
        if self.request.method == 'POST':
            choice = self.request.POST.get('choice', None)
            profile = self.request.POST.get('profile', None)
            return ExporterAsResp(choice, profile).export()
        else:
            return super().render_to_response(context)
