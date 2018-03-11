from django.http import HttpResponse
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from kukan.models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
from kukan.forms import SearchForm, ExampleForm, ExportForm
from django.template.loader import render_to_string
from django.db.models import Q
from django.http import JsonResponse
from functools import reduce
from django.core.paginator import Paginator
import csv
import re
import kukan.jautils as jau




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