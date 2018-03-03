from django.http import HttpResponse
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.views.generic.base import TemplateView
from django.urls import reverse_lazy
from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
from .forms import SearchForm, ExampleForm, ExportForm
from django.template.loader import render_to_string
from django.db.models import Q
from django.http import JsonResponse
from functools import reduce
from django.core.paginator import Paginator
import csv
import re
import kukan.jautils as jau
import json

import html2text

from lxml import html
import requests

from utilskanji import CKanjiDeck



class StatsPage(TemplateView):
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
        data['joyo'] = Reading.objects.exclude(joyo__yomi_joyo = '表外').count()
        data['non_joyo'] = Reading.objects.filter(joyo__yomi_joyo = '表外').count()
        data_list.append(data.copy())
        data['cat'] = '音読み'
        yomi_filt=Reading.objects.filter(yomi_type__yomi_type='音')
        data['total'] = yomi_filt.count()
        data['joyo'] = yomi_filt.exclude(joyo__yomi_joyo = '表外').count()
        data['non_joyo'] = yomi_filt.filter(joyo__yomi_joyo = '表外').count()
        data_list.append(data.copy())
        yomi_filt = Reading.objects.filter(yomi_type__yomi_type='訓')
        data['cat'] = '訓読み'
        data['total'] = yomi_filt.count()
        data['joyo'] = yomi_filt.exclude(joyo__yomi_joyo = '表外').count()
        data['non_joyo'] = yomi_filt.filter(joyo__yomi_joyo = '表外').count()
        data_list.append(data.copy())
        data['cat'] = '例文'
        data['total'] = Example.objects.all().count()
        data['joyo'] = 0
        data['non_joyo'] = 0
        data_list.append(data.copy())
        context['stats_table_data'] = json.dumps(data_list)
        return context

class ContactView(generic.FormView):
    template_name = 'kukan/index.html'
    form_class = SearchForm

    def form_valid(self, form):
        search = form.cleaned_data['search']
        if 'yoji' in self.request.POST:
            pass
        elif 'tango' in self.request.POST:
            self.success_url = reverse('kukan:example_search') + '?search=' + search
        else:
            self.success_url = reverse('kukan:kanji_multi') + '?search=' + search
        return super().form_valid(form)

    def get_success_url(self):
        return self.success_url



class KanjiList(generic.ListView):
    model = Kanji

    def get_queryset(self):
        #TODO - interesting
        #val_ex = Count('exmap', filter=~Q(exmap__example__yomi=''))
        # #some_interesting_query = Kanji.objects.annotate(ex_num = val_ex).filter(ex_num__gt=0).filter(kanken_kyu='２級')

        search = self.request.GET.get('search')
        if search == '' or search is None:
            search='漢字'
        q_objects = Q()
        for item in search:
            q_objects |= Q(pk=item)
        return Kanji.objects.filter(q_objects)


class KanjiListFilter(generic.ListView):
    model = Kanji
    template_name = 'kukan/kanji_lstfilter.html'


def get_kanji_list(request):
    page = request.GET.get('page', None)
    sort = request.GET.get('sort_by', None)
    p = Paginator(Kanji.objects.all().order_by(sort), 20)
    res = [obj.as_dict() for obj in p.page(page).object_list]
    col_tmplt = [{ 'title': '漢字2', 'field': 'kanji', 'visible': 'true' },
                { 'title': 'First Name', 'field': 'first_name', 'visible': 'true' }]
    col_tmplt = Kanji.fld_lst()
    data = {'page': page, 'total_results': p.count, 'results': res, 'columnsTemplate': col_tmplt}
    return JsonResponse(data)



class KanjiDetail(generic.DetailView):
    model = Kanji
    #template_name = 'kukan/detail.html'


class ExampleList(generic.ListView):
    model = Example

    def get_queryset(self):
        #TODO
        #return Example.objects.exclude(exmap__example__yomi='').filter(exmap__kanji__kanken_kyu='２級')
        #return Example.objects.filter(exmap__reading=None).distinct()
        search = self.request.GET.get('search')
        return Example.objects.filter(word__contains=search)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search')
        return context


class ExampleList2(generic.ListView):
    model = Example

    def get_queryset(self):
        #TODO
        return Example.objects.exclude(exmap__example__yomi='').filter(exmap__kanji__kanken_kyu='２級').distinct()




class ExampleDetail(generic.DetailView):
    model = Example

class ReadingDetail(generic.DetailView):
    model = Reading




def import_file(request):

    exit
    root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
    importFileName = root_dir + r'AnkiExport\漢字.txt'
    outputFileName = root_dir + r'AnkiImport\DeckKanji.txt'

    deck = CKanjiDeck.CKanjiDeck()
    deck.CreateDeckFromAnkiFile(importFileName)
    deck.ProcessJitenon()
    yomi = YomiType.objects.all()
    joyo = YomiJoyo.objects.all()
    for kj in Kanji.objects.all():
         deck_kj = deck[kj.kanji]
         for reading in deck_kj._readingList:
             if reading.isOn:
                 yt = yomi[0]
             else:
                 yt = yomi[1]

             if reading.isHyoGai:
                 jy = joyo[2]
             else:
                 jy = joyo[0]
             kj.reading_set.get_or_create(
                reading=reading.reading,
                yomi_type=yt,
                joyo=jy
             )
    return HttpResponse("y9o")



class ExampleCreate(CreateView):
    template_name = 'kukan/example_update.html'
    model = Example
    form_class = ExampleForm
    context_object_name = 'example'

    def form_valid(self, form):
        # This method is called when valid form data has been POSTed.
        # It should return an HttpResponse.
        fld = form.fields
        return super().form_valid(form)


class ExampleUpdate2(UpdateView):
    model = Example
    fields = ['word', 'yomi', 'sentence', 'definition']

    def form_valid(self, form):
        # This method is called when valid form data has been POSTed.
        # It should return an HttpResponse.
        fld = form.fields
        return super().form_valid(form)


class ExampleUpdate(UpdateView):
    template_name = 'kukan/example_update.html'
    model = Example
    form_class = ExampleForm
    context_object_name = 'example'


class ExampleDelete(DeleteView):
    model = Example
    success_url = reverse_lazy('example-list')


def get_yomi(request):
    word = request.GET.get('word', None)
    ex_id= request.GET.get('ex_id', None)
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
            [{'key': x.id, 'read': x.reading} for x in Reading.objects.filter(kanji=kj)]
        if len(linked_ex) and linked_ex[0].reading:
            reading_data[kj]['selected'] = linked_ex[0].reading.reading
            reading_data[kj]['joyo'] = linked_ex[0].in_joyo_list
            reading_selected.append(linked_ex[0].reading.id)
        elif len(ini_reading_selected) > idx \
                and ini_reading_selected[idx] > -1\
                and Reading.objects.get(id=ini_reading_selected[idx]).kanji.kanji == kj:

            reading_data[kj]['selected'] = Reading.objects.get(id=ini_reading_selected[idx]).reading
            reading_data[kj]['joyo'] = False
            reading_selected.append(ini_reading_selected[idx])
        else:
            reading_data[kj]['selected'] = None
            reading_data[kj]['joyo'] = False
            reading_selected.append(None)
    data = {'reading_selected': reading_selected, 'reading_data': reading_data}
    return JsonResponse(data)


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
        data = {'candidate':ids}
    return JsonResponse(data)


def get_similar_word(request):
    word = request.GET.get('word', None)
    sim_word=[x.word + ('（'+ x.yomi +'）' if x.yomi!='' else '')
                        for x in Example.objects.filter(word__contains=word)]
    data={'info_similar_word':sim_word}
    return JsonResponse(data)

def get_goo(request):
    word = request.GET.get('word', None)
    link = request.GET.get('link', None)
    if link == '':
        link = 'https://dictionary.goo.ne.jp/srch/jn/' + word + '/m1u/'
    else:
        link = 'https://dictionary.goo.ne.jp' + link
    page = requests.get(link)
    tree = html.fromstring(page.content)
    text = ""
    candidates = ""
    try:
        block = tree.xpath('//*[@id="NR-main-in"]/section/div/div[2]/div')
        text = html.tostring(block[0], encoding='unicode')
        definition = block[0].getchildren()[0].text
    except IndexError:
        block = tree.xpath('//dt[@class="title search-ttl-a"]')
        candidates=[]
        for block in tree.xpath('//dt[@class="title search-ttl-a"]'):
            candidates.append({'word':block.text,'link':block.getparent().getparent().get('href')})

    h = html2text.HTML2Text()
    h.ignore_links = True
    if text != '':
        text = text.replace('<ol', '<ul')
        # text = text.replace('<li', '<ul')
        text = h.handle(text)
        # text = text.replace('\n\n', '\n')
        text = re.sub(r'  \* \*\*(\d*)\*\*',
                      lambda match: match.group(1).translate(jau.digit_ful2half) + '. ',
                      text)

        #text=text.strip()
    data = {'definition':text, 'candidates':candidates}

    return JsonResponse(data)


class ExportView(generic.FormView):
    template_name = 'kukan/export.html'
    form_class = ExportForm
    success_url = reverse_lazy('kukan:export')

    def form_valid(self, form):
        type = form.cleaned_data['type']
        return super().form_valid(form)

def export_anki_kanji(request):
    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="djangoAnki.csv"'

    writer = csv.writer(response, delimiter='\t', quotechar='"')
    for kj in Kanji.objects.filter():
        anki_read_table = render_to_string('kukan/AnkiReadTable.html', {'kanji': kj})
        anki_read_table = re.sub('^( *)', '', anki_read_table, flags=re.MULTILINE)
        anki_read_table = anki_read_table.replace('\n', '')
        writer.writerow([kj.kanji,
                     kj.anki_Onyomi,
                     kj.anki_Kunyomi,
                     kj.anki_Nanori,
                     kj.anki_English,
                     kj.anki_Examples,
                     kj.anki_JLPT_Level,
                     kj.anki_Jouyou_Grade,
                     kj.anki_Frequency,
                     kj.anki_Components,
                     kj.anki_Number_of_Strokes,
                     kj.anki_Kanji_Radical,
                     kj.anki_Radical_Number,
                     kj.anki_Radical_Strokes,
                     kj.anki_Radical_Reading,
                     kj.anki_Traditional_Form,
                     kj.anki_Classification,
                     kj.anki_Keyword,
                     kj.anki_Traditional_Radical,
                     anki_read_table,
                     kj.bushu.bushu,
                     kj.anki_kjBushuMei,
                     kj.kanken_kyu,
                     kj.classification,
                     kj.anki_kjIjiDoukun])
    return response
