from django.http import HttpResponse
from django.urls import reverse
from django.views import generic
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from kukan.models import Kanji, Kanken, Bushu, YomiType, YomiJoyo, Reading, Example, ExMap, Classification, \
    KoukiBushu, JisClass, KanjiDetails
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
from .Kanji import CKanji
import json


def read_from_csv():

    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\ref_jiten_kyu01.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            kanji = CKanji(row[0])
            kanji.ProcessJitenon()
            ji_kanken = kanji._jitenonItem['漢字検定'][0]
            if ji_kanken == '１級 / 準１級':
                ji_kanken = '準１級'

            classification = None
            if len(kanji._jitenonItem['種別'])>0 and kanji._jitenonItem['種別'][0] == '人名用漢字':
                classification = Classification.objects.get(classification='人名用漢字')



            kj, create = Kanji.objects.get_or_create(
                kanji=row[0],
                strokes=int(kanji._jitenonItem['画数'][0].replace('画', '')),
                kanken = Kanken.objects.get(kyu = ji_kanken),
                kouki_bushu = KoukiBushu.objects.filter(variations__contains=kanji._jitenonItem['部首'][0][0])[0],
                classification = classification,
                )

            kj.meaning = json.dumps(kanji._jitenonItem['意味'])
            kj.external_ref = row[1]
            kj.save()

            for read in kanji._jitenonItem['音読み']:
                Reading.objects.get_or_create(
                    kanji = kj,
                    reading = read,
                    yomi_type = YomiType.objects.get(yomi_type='音'),
                    joyo = YomiJoyo.objects.get(yomi_joyo='表外'),
                    joyo_order = 9999,
                )
            for read in kanji._jitenonItem['訓読み']:
                Reading.objects.get_or_create(
                    kanji = kj,
                    reading = read,
                    yomi_type = YomiType.objects.get(yomi_type='訓'),
                    joyo = YomiJoyo.objects.get(yomi_joyo='表外'),
                    joyo_order = 9999,
                )


def create_bushu_list():
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\bushu-list-20110425.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for idx, row in enumerate(csvIn):
            KoukiBushu.objects.create(
                bushu = row[0][0],
                variations = row[0],
                reading = row[2],
                number = idx + 1
            )

def fill_existing():
    # importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\ref_jiten.csv'
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\ref_jiten_kyu0101j.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            kanji = CKanji(row[0])
            kanji.ProcessJitenon()
            kj=Kanji.objects.get(kanji=row[0])
            kj.external_ref = row[1]
            if kanji._jitenonItem['部首'][0][0] == '⺍':
                kj.kouki_bushu = KoukiBushu.objects.filter(variations__contains=kanji._jitenonItem['部首'][1][0])[0]
            else:
                kj.kouki_bushu = KoukiBushu.objects.filter(variations__contains=kanji._jitenonItem['部首'][0][0])[0]
            if 'JIS' in kanji._jitenonItem['JIS水準'][0]:
                kj.jis = JisClass.objects.get(level = kanji._jitenonItem['JIS水準'][0])
            kj.save()


def process_kyuji():
    importCsvName = r'E:\CloudStorage\Google Drive\Kanji\資料\ref_jiten_kyu01.csv'
    with open(importCsvName, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            kanji = CKanji(row[0])
            kanji.ProcessJitenon()
            if len(kanji._jitenonItem['異体字']) > 0:
                kj = Kanji.objects.get(kanji=row[0])
                for iji in kanji._jitenonItem['異体字']:
                    if iji is not None:
                        nj = Kanji.objects.get(kanjidetails__external_ref__contains=iji[1])
                        if iji[0]=='新字体':
                            kj.kanjidetails.new_kanji = nj
                        elif iji[0] == '標準字体':
                            kj.kanjidetails.std_kanji = nj
                        kj.kanjidetails.save()