from django.http import HttpResponse
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from kukan.models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap, Yoji
from kukan.forms import SearchForm, ExampleForm, ExportForm
from django.template.loader import render_to_string
from django.db.models import Q
from django.http import JsonResponse
from functools import reduce
from django.core.paginator import Paginator
import csv
import re
import kukan.jautils as jau
from utilskanji import CKanjiDeck
from lxml import html
import requests
import html2text


def TODO_export_anki_csv(request):
    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="djangoAnki.csv"'

    root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
    exportFileName = root_dir + r'AnkiImport\DjangoKanji.txt'
    with open(exportFileName, 'w', encoding='utf-8', newline='') as fDeck:
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
                         #kj.anki_Reading_Table,
                         anki_read_table,
                         kj.bushu.bushu,
                         kj.anki_kjBushuMei,
                         kj.kanken.kyu,
                         kj.classification,
                         kj.anki_kjIjiDoukun])
    return response



def example_from_csv():
    exDict = {}

    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\AnkiExport\書き取り.txt'
    exportCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\AnkiExport\書き取り_proc.txt'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck, open(exportCsvName, 'w', encoding='utf-8') as outputDeck:
        csvOut = csv.writer(outputDeck, delimiter='\t', quotechar='"')
        csvIn = csv.reader(fDeck, delimiter='\t', quotechar='"')
        for row in csvIn:
            if row[0]!='':
                continue

            inc = False
            if '級' not in row[3]:
                inc = True
                print('Check ex:' + row[2] )
            else:
                continue

            for kj in row[2]:
                try:
                    kanji=Kanji.objects.get(kanji=kj)
                except Kanji.DoesNotExist:
                    print('Skip Kanji ' + row[2])
                    inc = False
            if not inc: continue


            m = re.search('<span class="font-color01">(.*)</span>', row[1])
            sentence = re.sub('<span class="font-color01">.*</span>', row[2], row[1])

            if not Example.objects.filter(word__contains=row[2]).exists():

                ex = Example(word=row[1], yomi=m[1], sentence=sentence, is_joyo=False )
                ex.save()
                idx = -1
                for kj in row[1]:
                    idx += 1
                    try:
                        m1 = ExMap(example=ex,
                                   kanji=Kanji.objects.get(kanji=kj),
                                   map_order=idx,
                                   in_joyo_list=False)
                        m1.save()
                    except Kanji.DoesNotExist:
                        print('Skip Kanji ' + kj)
            elif Example.objects.filter(word=row[2]).count()==1:
                example = Example.objects.get(word=row[1])
                example.sentence = sentence
                example.yomi=m[1]
                example.save()
            elif Example.objects.filter(word=row[2]).count()>1:
                print('Multiple candidate example - ' + row[1])
            else:
                print('Failed condition - ' + row[2])
                row[1]=sentence
                csvOut.writerow(row)


def example_from_csv_old():
    exDict = {}

    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\AnkiExport\書き取り.txt'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter='\t', quotechar='"')
        for row in csvIn:
            exDict[row[1]] = row[0]

    for example in Example.objects.filter(kanken__kyu='２級'):
        if example.word in exDict:
            example.sentence = exDict[example.word]
            m = re.search('<span class="font-color01">(.*)</span>', example.sentence)
            example.yomi = m[1]
            example.sentence = re.sub('<span class="font-color01">.*</span>', example.word, example.sentence)
            example.save()


def read_from_csv(request):
    readingDict = {}
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\joyo_ref.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            reading = row[3]
            if reading[0] == "▽":
                special = True
                reading = reading[1:]
            else:
                special = False
            readingDict[(row[0], reading)] = (special, row[5], row[6])

    joyo = YomiJoyo.objects.all()
    for reading in Reading.objects.all():
        if reading.is_joyo():
            dct = readingDict[(reading.kanji.kanji, reading.get_simple())]
            reading.remark = dct[1]
            reading.ijidokun = dct[2]
            if dct[0]:
                reading.joyo = joyo[1]
            reading.save()

    return HttpResponse("readcsv")


def add_ex():
    readingDict = {}
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\joyo_ref.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            reading = row[3]
            if reading[0] == "▽":
                special = True
                reading = reading[1:]
            else:
                special = False
            readingDict[(row[0], reading)] = (special, row[5], row[6], row[4])

    ex_set = set()
    joyo = YomiJoyo.objects.all()

    for reading in Reading.objects.all():
        if reading.is_joyo():
            kj=reading.kanji.kanji
            dct = readingDict[(kj, reading.get_simple())]
            for ex in dct[3].split('、'):
                if ex=='':
                    continue
                # print(reading.kanji.kanji + str(reading.id))
                if (kj, ex) in ex_set:
                    print('Already exists:' + str((kj, ex)))
                    ex_obj=Example.objects.create(word=ex, yomi='Exists, new id ' + str(reading.id), is_joyo=True)
                else:
                    ex_set.add((kj, ex))
                    ex_obj, created = Example.objects.get_or_create(word=ex, yomi='', is_joyo=True)
                m1 = ExMap(example=ex_obj,
                           kanji=reading.kanji,
                           reading=reading,
                           map_order=ex.index(reading.kanji.kanji),
                           in_joyo_list=True)
                #reading.example_set.add(ex)
                m1.save()



def check_ex_dup():
    ex_set = set()
    readingDict = {}
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\joyo_ref.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            reading = row[3]
            if reading[0] == "▽":
                special = True
                reading = reading[1:]
            else:
                special = False
            for ex in row[4].split('、'):
                if (row[0], ex) in ex_set:
                    print('duplicate: ' + str((row[0], ex)) )
                else:
                    ex_set.add((row[0], ex))


def check_typo():
    ex_set = set()
    readingDict = {}
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\joyo_ref.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            for ex in row[4].split('、'):
                if row[0] not in ex:
                    print('wrong kanji: ' + row[0] + ' / ' + ex)

def add_ex_special():
    readingDict = {}
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\joyo_ref.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            for ex in row[7].split('、'):
                if ex=='':
                    continue
                ex_obj, created = Example.objects.get_or_create(word=ex, yomi='jukuji', is_joyo=True)
                m1 = ExMap(example=ex_obj,
                           kanji=Kanji.objects.get(kanji=row[0]),
                           map_order=ex.index(row[0]),
                           in_joyo_list=True)
                m1.save()


def import_kanji():

    root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
    importFileName = root_dir + r'AnkiExport\漢字.txt'
    outputFileName = root_dir + r'AnkiImport\DeckKanji.txt'

    deck = CKanjiDeck.CKanjiDeck()
    deck.CreateDeckFromAnkiFile(importFileName)
    deck.ProcessJitenon()

def import_yoji_anki():
    root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
    importFileName = root_dir + r'AnkiExport\四字熟語.txt'
    outputFileName = root_dir + r'AnkiExport\四字熟語_leftover.txt'

    with open(importFileName, 'r', encoding='utf-8') as fDeck, open(outputFileName, 'w', encoding='utf-8') as fleft:
        csvIn = csv.reader(fDeck, delimiter='\t', quotechar='"')
        for row in csvIn:
            try:
                yj = Yoji.objects.get(yoji=row[0])
                yj.in_anki = True
                yj.anki_cloze = row[1][3] + row[1][12] + row[1][21] + row[1][30]
                yj.save()
            except Yoji.DoesNotExist:
                fleft.write(row[0] + '\n')


def get_goo_definition(word, link=''):
    if link == '':
        link = 'https://dictionary.goo.ne.jp/srch/jn/' + word + '/m1u/'
    else:
        link = 'https://dictionary.goo.ne.jp' + link
    page = requests.get(link)
    tree = html.fromstring(page.content)
    text = ""
    candidates = []
    yomi=""
    try:
        block = tree.xpath('//*[@id="NR-main-in"]/section/div/div[2]/div')
        text = html.tostring(block[0], encoding='unicode')
        yomi = tree.xpath('//*[@id="NR-main-in"]/section/div/div[1]/h1/text()')[0]
        yomi = yomi[0:yomi.index('【')].replace('‐','')
        yomi = yomi.translate(jau.hir2kat)
        yomi = yomi.replace('・', '')
        yomi = re.sub('〔.*〕','', yomi)
        definition = block[0].getchildren()[0].text
    except IndexError:
        block = tree.xpath('//dt[@class="title search-ttl-a"]')
        for block in tree.xpath('//dt[@class="title search-ttl-a"]'):
            if block.getparent().getparent().get('href')[0:3] == '/jn':
                candidates.append({'word':block.text,'link':block.getparent().getparent().get('href')})

    if text != '':
        h = html2text.HTML2Text()
        h.ignore_links = True
        text = text.replace('<ol', '<ul')
        text = h.handle(text)
        text = re.sub(r'  \* \*\*(\d*)\*\*',
                      lambda match: match.group(1).translate(jau.digit_ful2half) + '. ',
                      text)
        text = re.sub(r'__「(.*)の全ての意味を見る\n\n', '', text)

    data = {'definition': text, 'reading': yomi, 'candidates': candidates if len(candidates) > 0 else ''}
    return data

def set_yomi(word, yomi):
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
        data = {'candidate':ids}

    return data

def save_ex(example, reading_selected):
    map_list = []
    idx = 0
    for kj in example.get_word_native():
        try:
            kanji = Kanji.objects.get(kanji=kj)
            # check if the reading is a Joyo one - in which case it can't be changed
            try:
                map = example.exmap_set.get(kanji=kanji,
                                            example=example,
                                            map_order=idx,
                                            in_joyo_list=True)
            except ExMap.DoesNotExist:
                if reading_selected[idx] == '0':
                    map, create = example.exmap_set.get_or_create(kanji=kanji,
                                                                  example=example,
                                                                  map_order=idx,
                                                                  is_ateji=True,
                                                                  in_joyo_list=False)
                else:
                    reading = Reading.objects.get(kanji=kj, id=reading_selected[idx])
                    map, create = example.exmap_set.get_or_create(kanji=kanji,
                                                                  reading=reading,
                                                                  example=example,
                                                                  map_order=idx,
                                                                  is_ateji=False,
                                                                  in_joyo_list=False)
            map_list.append(map.id)
            idx += 1
        except Kanji.DoesNotExist:
            # Not a Kanji (kana, or kanji not in the list)
            pass
    # Delete the maps not relevant anymore
    extra_maps = ExMap.objects.filter(example=example).exclude(id__in=map_list)
    extra_maps.delete()

def fill_example(example):
    print('process: ' + example.word)
    d1 = get_goo_definition(example.word)
    d2 = set_yomi(example.word, d1['reading'])['candidate']
    if example.yomi == '' and d1['reading']!='':
        example.yomi = d1['reading']
        print('   yomi: ' + d1['reading'])
        example.save()
        if d2 is not None:
            save_ex(example, d2)
    if example.definition == '' and d1['definition'] != '':
        example.definition = d1['definition']
        print('   yomi: ' + d1['definition'])
        example.save()

