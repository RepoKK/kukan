from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.base import TemplateView
from django.urls import reverse_lazy
from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap, Yoji, TestResult, Kotowaza
from .forms import SearchForm, ExampleForm, ExportForm, KotowazaForm
from django.http import JsonResponse
from functools import reduce
from django.core.paginator import Paginator, EmptyPage
import kukan.jautils as jau
from kukan.jautils import JpText
from django.db.models import Count

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .filters import *
import time

from kukan.exporting import ExporterAsResp
from kukan.onlinepedia import DefinitionWordBase


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
        data = {}
        data['cat'] = '漢字'
        data['total'] = Kanji.objects.all().count()
        data['joyo'] = Kanji.objects.filter(classification__classification='常用漢字').count()
        data['non_joyo'] = Kanji.objects.exclude(classification__classification='常用漢字').count()
        data_list.append(data.copy())
        data = {}
        data['cat'] = '総合読み'
        data['total'] = Reading.objects.all().count()
        data['joyo'] = Reading.objects.exclude(joyo__yomi_joyo='表外').count()
        data['non_joyo'] = Reading.objects.filter(joyo__yomi_joyo='表外').count()
        data_list.append(data.copy())
        data['cat'] = '音読み'
        yomi_filt = Reading.objects.filter(yomi_type__yomi_type='音')
        data['total'] = yomi_filt.count()
        data['joyo'] = yomi_filt.exclude(joyo__yomi_joyo='表外').count()
        data['non_joyo'] = yomi_filt.filter(joyo__yomi_joyo='表外').count()
        data_list.append(data.copy())
        yomi_filt = Reading.objects.filter(yomi_type__yomi_type='訓')
        data['cat'] = '訓読み'
        data['total'] = yomi_filt.count()
        data['joyo'] = yomi_filt.exclude(joyo__yomi_joyo='表外').count()
        data['non_joyo'] = yomi_filt.filter(joyo__yomi_joyo='表外').count()
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
            filter_list += flt.toJSON() + ",\n"
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
    linked_ex = []
    example = None
    if ex_id != '':
        try:
            example = Example.objects.get(id=ex_id)
        except Example.DoesNotExist:
            pass

    ini_reading_selected = request.GET.get('reading_selected', None).split(',')
    ini_reading_selected = [int(x) if x != '' else -1 for x in ini_reading_selected]
    reading_data = {}
    reading_selected = []
    for idx, kj in enumerate(word):
        try:
            kanji = Kanji.objects.get(kanji=kj)
        except Kanji.DoesNotExist:
            continue
        reading_data[kj] = {}
        reading_data[kj]['kanji'] = kj
        reading_data[kj]['kyu'] = kanji.kanken.kyu
        reading_data[kj]['example_num'] = kanji.exmap_set.exclude(example__sentence='').count()
        if example is not None:
            linked_ex = ExMap.objects.filter(kanji=kj, example=example)

        reading_data[kj]['readings'] = \
            [{'key': x.id, 'read': x.get_full()} for x in Reading.objects.filter(kanji=kj)]
        reading_data[kj]['readings'] = [{'key': 0, 'read': ExMap.ateji_option_disp}] + reading_data[kj]['readings']
        if len(linked_ex) and (linked_ex[0].reading or linked_ex[0].is_ateji):
            if linked_ex[0].is_ateji:
                reading_data[kj]['selected'] = ExMap.ateji_option_disp
                reading_selected.append(0)
            else:
                reading_data[kj]['selected'] = linked_ex[0].reading.reading
                reading_selected.append(linked_ex[0].reading.id)
            reading_data[kj]['joyo'] = linked_ex[0].in_joyo_list

        elif len(ini_reading_selected) > idx \
                and ini_reading_selected[idx] > -1 \
                and (ini_reading_selected[idx] == 0
                     or Reading.objects.get(id=ini_reading_selected[idx]).kanji.kanji == kj):
            if ini_reading_selected[idx] == 0:
                reading_data[kj]['selected'] = ExMap.ateji_option_disp
            else:
                reading_data[kj]['selected'] = Reading.objects.get(id=ini_reading_selected[idx]).reading
            reading_data[kj]['joyo'] = False
            reading_selected.append(ini_reading_selected[idx])
        else:
            reading_data[kj]['selected'] = None
            reading_data[kj]['joyo'] = False
            reading_selected.append(None)
    data = {'reading_selected': reading_selected, 'reading_data': reading_data}
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
        lst_reading.append([x.reading.translate(jau.hir2kat) for x in Reading.objects.filter(kanji=kj)])
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
    ex_id = request.GET.get('ex_id', None)
    sim_word = [x.word + ('（' + x.yomi + '）' if x.yomi != '' else '')
                for x in Example.objects.filter(word__contains=word).exclude(id=ex_id)]
    data = {'info_similar_word': sim_word}
    return JsonResponse(data)


@login_required
def get_goo(request):
    word = request.GET.get('word_native', None)
    if word == '':
        word = request.GET.get('word', None)
    link = request.GET.get('link', None)

    if link:
        definition, yomi, candidates = DefinitionWordBase.from_link(link).get_definition()
    else:
        definition, yomi, candidates = DefinitionWordBase.from_word(word).get_definition()

    data = {'definition': definition, 'reading': yomi, 'candidates': candidates if len(candidates) > 0 else ''}

    return JsonResponse(data)


@login_required
def get_furigana(request):
    text = JpText(request.GET.get('word', None), request.GET.get('yomi', None))
    return JsonResponse({
        'furigana': text.guess_furigana(),
        'furigana_errors': text.get_furigana_errors(),
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


# TODO
# def read_from_bin():
#     res = []
#     str = str.replace("\n", "")
#     for x in zip(*[str[i::3] for i in range(3)]):
#         if x[0] == x[1] and x[0] == x[2]:
#             res.append(x[0])
#         else:
#             print('Problem: ', x[0], x[1], x[2])
#             if x[0] in [x[1], x[2]]:
#                 res.append(x[0])
#             elif x[1] == x[2]:
#                 res.append(x[1])
#             else:
#                 res.append('   zzz   ')
#     final = ''.join(res)
#     print(final, '\nError' if 'z' in res else '\nOK')
#     print(bz2.decompress(b''.fromhex(final)))
#     with open(r"D:\testOCR\res.py.txt", "wb") as file:
#         file.write(bz2.decompress(b''.fromhex(final)))
#
# C:\Program Files (x86)\Tesseract-OCR>tesseract.exe D:\testOCR\test.bmp D:\testOCR\out -c tessedit_char_whitelist=0123456789Abcdef -c load_system_dawg=f -c load_freq_dawg=f
