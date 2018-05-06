from django.http import HttpResponse
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.base import TemplateView
from django.urls import reverse_lazy
from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap, Yoji
from .forms import SearchForm, ExampleForm, ExportForm
from django.template.loader import render_to_string
from django.db.models import Q
from django.http import JsonResponse
from functools import reduce
from django.core.paginator import Paginator, EmptyPage
import csv
import re
import kukan.jautils as jau
import json
from django.db.models import Count
import html2text

from lxml import html
import requests

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from .filters import *
import time

class Index(LoginRequiredMixin, generic.FormView):
    template_name = 'kukan/index.html'
    form_class = SearchForm

    def form_valid(self, form):
        search = form.cleaned_data['search']
        if 'yoji' in self.request.POST:
            self.success_url = reverse('kukan:yoji_list')
            if search != '':
                self.success_url += '?漢字=' + search + '&Anki=Anki'
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


class AjaxList(LoginRequiredMixin, generic.TemplateView):

    def dispatch(self, request, *args, **kwargs):
        if request.method.lower() == 'get' and request.GET.get('ajax', None)=='1':
            handler = self.get_list
        else:
            handler = super().dispatch
        return handler(request, *args, **kwargs)

    def get_list(self, request, *args, **kwargs):
        page = request.GET.get('page', None)
        sort = request.GET.get('sort_by', None)
        start_time = time.time()
        qry = self.get_filtered_list(request)

        col_tmplt = self.model.fld_lst()
        try:
            p = Paginator(qry.order_by(sort), 20, allow_empty_first_page=True)
            res = [obj.as_dict() for obj in p.page(page).object_list]
            end_time = time.time()
            data = {'page': page, 'total_results': p.count, 'results': res, 'columnsTemplate': col_tmplt,
                    'stats': [ str(p.count) + ' 件',
                               'Q:' + '{:d}'.format(int((end_time - start_time)*1000)),]}
        except EmptyPage:
            data = {'page': 0, 'total_results': 0, 'results': [], 'columnsTemplate': col_tmplt, 'stats': '0 件'}

        return JsonResponse(data)

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
        context['page'] = self.request.GET.get('page', 1)
        sortOrder = self.request.GET.get('sort_by', self.default_sort)
        if sortOrder[0] == '-':
            context['sort_by'] = sortOrder[1:]
            context['sort_order'] = 'desc'
        else:
            context['sort_by'] = sortOrder
            context['sort_order'] = 'asc'

        return context


class KanjiListFilter(AjaxList):
    model = Kanji
    template_name = 'kukan/kanji_list.html'
    default_sort = 'kanken'
    filters = [
        FGenericString('漢字', 'kanji','kanji__in', list),
        FYomi(),
        FBushu(),
        FGenericMinMax('画数', 'strokes'),
        FGenericCheckbox('種別', 'classification__classification', model,
                         order='-classification__classification', none_label='常用・人名以外'),
        FGenericCheckbox('JIS水準', 'jis__level', model, none_label='JIS水準不明'),
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericMinMax('例文数', 'ex_num'),
        ]

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
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericYesNo('Anki', 'in_anki', True, 'Anki', '非Anki'),
        ]

class ExampleList(AjaxList):
    model = Example
    template_name = 'kukan/example_list.html'
    default_sort = 'kanken'
    filters = [
        FGenericString('単語', 'word'),
        FGenericCheckbox('漢検', 'kanken__kyu', model, is_two_column=True, order='-kanken__difficulty'),
        FGenericYesNo('例文', 'sentence', '', '例文有り', '例文無し', True),
        FGenericDateRange('作成', 'created_time'),
        FGenericDateRange('変更', 'updated_time'),
        ]


class KanjiDetail(LoginRequiredMixin, generic.DetailView):
    model = Kanji

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qry=Example.objects.filter(word__contains=context['kanji']).exclude(sentence='')
        context['data'] = json.dumps([obj.as_dict() for obj in qry])
        context['columns'] = json.dumps(Example.fld_lst())
        return context


class YojiDetail(LoginRequiredMixin, generic.DetailView):
    model = Yoji


class ExampleDetail(LoginRequiredMixin, generic.DetailView):
    model = Example


class ExampleCreate(LoginRequiredMixin, CreateView):
    template_name = 'kukan/example_update.html'
    model = Example
    form_class = ExampleForm
    context_object_name = 'example'

    def form_valid(self, form):
        # This method is called when valid form data has been POSTed.
        # It should return an HttpResponse.
        fld = form.fields
        return super().form_valid(form)


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
        if len(Kanji.objects.filter(kanji=kj)) == 0:
            continue
        reading_data[kj] = {}
        reading_data[kj]['kanji'] = kj
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
    yomi = request.GET.get('yomi', None)
    yomi = yomi.translate(jau.hir2kat)

    data = {}
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
    sim_word = [x.word + ('（' + x.yomi + '）' if x.yomi != '' else '')
                for x in Example.objects.filter(word__contains=word)]
    data = {'info_similar_word': sim_word}
    return JsonResponse(data)


@login_required
def get_goo(request):
    word = request.GET.get('word_native', None)
    if word == '':
        word = request.GET.get('word', None)
    link = request.GET.get('link', None)
    if link == '':
        link = 'https://dictionary.goo.ne.jp/srch/jn/' + word + '/m1u/'
    else:
        link = 'https://dictionary.goo.ne.jp' + link
    page = requests.get(link)
    tree = html.fromstring(page.content)
    text = ""
    candidates = []
    yomi = ""
    try:
        block = tree.xpath('//*[@id="NR-main-in"]/section/div/div[2]/div')
        text = html.tostring(block[0], encoding='unicode')
        yomi = tree.xpath('//*[@id="NR-main-in"]/section/div/div[1]/h1/text()')[0]
        yomi = yomi[0:yomi.index('【')].replace('‐', '')
        yomi = yomi.translate(jau.hir2kat)
        yomi = yomi.replace('・', '')
        yomi = re.sub('〔.*〕', '', yomi)
        definition = block[0].getchildren()[0].text
    except IndexError:
        block = tree.xpath('//dt[@class="title search-ttl-a"]')
        for block in tree.xpath('//dt[@class="title search-ttl-a"]'):
            if block.getparent().getparent().get('href')[0:3] == '/jn':
                candidates.append({'word': block.text, 'link': block.getparent().getparent().get('href')})

    if text != '':
        h = html2text.HTML2Text()
        h.ignore_links = True
        text = text.replace('<ol', '<ul')
        # text = text.replace('<li', '<ul')
        text = h.handle(text)
        # text = text.replace('\n\n', '\n')
        text = re.sub(r'  \* \*\*(\d*)\*\*',
                      lambda match: match.group(1).translate(jau.digit_ful2half) + '. ',
                      text)
        text = re.sub(r'__「(.*)の全ての意味を見る\n\n', '', text)

    data = {'definition': text, 'reading': yomi, 'candidates': candidates if len(candidates) > 0 else ''}

    return JsonResponse(data)


class ExportView(LoginRequiredMixin, generic.FormView):
    template_name = 'kukan/export.html'
    form_class = ExportForm
    success_url = reverse_lazy('kukan:export')

    def render_to_response(self, context, **response_kwargs):
        # Look for a 'format=json' GET argument
        if self.request.method == 'POST':
            choice = self.request.POST.get('choice', None)
            if choice[0:9] == 'anki_kaki':
                return self.export_anki_kakitori(choice)
            elif choice == 'anki_yoji':
                return self.export_anki_yoji()
            elif choice == 'anki_kanji':
                return self.export_anki_kanji()
        else:
            return super().render_to_response(context)

    def export_anki_kakitori(self, choice):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="djAnkiKakitori_'+ choice[10:] +'.csv"'
        writer = csv.writer(response, delimiter='\t', quotechar='"')

        q_set = Example.objects.exclude(sentence='').exclude(kanken__difficulty__gt=10)
        if choice == 'anki_kaki_ayu':
            q_set = q_set.exclude(kanken__difficulty__lt=8)

        for example in q_set:
            word = example.word_native if example.word_native != "" else example.word
            yomi = example.yomi_native if example.yomi_native != "" else example.yomi
            sentence = example.sentence.replace(word,
                                                '<span class="font-color01">' +
                                                yomi + '</span>')
            writer.writerow([example.id,
                             sentence,
                             word,
                             example.kanken])
        return response

    def export_anki_kanji(request):
        # Create the HttpResponse object with the appropriate CSV header.
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="djAnkiKanji.csv"'

        writer = csv.writer(response, delimiter='\t', quotechar='"')
        for kj in Kanji.objects.exclude(kanken__difficulty__gt=10):
            anki_read_table = render_to_string('kukan/AnkiReadTable.html', {'kanji': kj})
            writer.writerow([kj.kanji,
                             kj.anki_English,
                             kj.anki_Examples,
                             kj.anki_Kanji_Radical,
                             kj.anki_Traditional_Form,
                             kj.anki_Traditional_Radical,
                             anki_read_table,
                             kj.bushu.bushu,
                             kj.anki_kjBushuMei,
                             kj.kanken.kyu,
                             kj.classification,
                             kj.anki_kjIjiDoukun])
        return response


    def export_anki_yoji(request):
        # Create the HttpResponse object with the appropriate CSV header.
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="djAnkiYoji.csv"'

        writer = csv.writer(response, delimiter='\t', quotechar='"')
        for yoji in Yoji.objects.filter(in_anki=True):
            cloze = ''
            for yj, idx in zip(yoji.yoji, yoji.anki_cloze):
                cloze += "{{c" + str(idx) + "::" + yj + "}}"
            writer.writerow([yoji.yoji,
                             cloze,
                             yoji.reading,
                             yoji.get_definition_html()[3:-4],
                             ])
        return response


def read_from_bin():
    res = []
    str = str.replace("\n", "")
    for x in zip(*[str[i::3] for i in range(3)]):
        if x[0] == x[1] and x[0] == x[2]:
            res.append(x[0])
        else:
            print('Problem: ', x[0], x[1], x[2])
            if x[0] in [x[1], x[2]]:
                res.append(x[0])
            elif x[1] == x[2]:
                res.append(x[1])
            else:
                res.append('   zzz   ')
    final = ''.join(res)
    print(final, '\nError' if 'z' in res else '\nOK')
    print(bz2.decompress(b''.fromhex(final)))
    with open(r"D:\testOCR\res.py.txt", "wb") as file:
        file.write(bz2.decompress(b''.fromhex(final)))