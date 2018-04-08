from kukan.models import Kanji, Kanken, Bunrui, Yoji
import lxml
from lxml import html
import requests
import csv
import pickle
import html2text

listFile = r'E:\CloudStorage\Google Drive\Kanji\資料\Sources\ref_yoji_all.csv'

def get_list(kanji_type, tree):
    yojiMap = {}
    targetFile = r'E:\CloudStorage\Google Drive\Kanji\資料\Sources\ref_yoji_all_tmp.csv'
    block = tree.xpath('//*[@class="jukugolist"]/tr/td/a')
    for node in block:
        reading = node.getparent().getparent().getchildren()[1].text
        yojiMap[node.text] = [node.attrib.get("href"), reading]

    with open(targetFile, "w", encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerows(yojiMap.items())

    return yojiMap


def init_jitenon(kanji_type):
    page_addr = 'http://yoji.jitenon.jp/cat/' + kanji_type + '.html'
    page = requests.get(page_addr)
    return html.fromstring(page.content)


def h3_row_nb_all(kanji, node):
    if len(node.getchildren()) == 0:
        nname = node.text
    else:
        nname = node.getchildren()[0].text
    nb_row = node.attrib.get("rowspan")
    if nb_row is None:
        nb_row = 1
    else:
        nb_row = int(nb_row)
    return nname, nb_row

class CYoji:
    def __init__(self, yoji):
        self._Yoji = yoji
        self._jitenonItem = {'読み方':[], '意味':[], '出典':[], '類義語':[],
                            '漢字検定':[], '分類':[], '漢字詳細':[]}

    def __iter__(self):
        return iter(self._propList)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False


    def _get_kanji_file_name(self):
        root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\Yoji_all\\' + self._Yoji + '.html'
        return root_dir

    def ProcessJitenon(self):
        page = pickle.load(open(self._get_kanji_file_name(), "rb"));
        tree = html.fromstring(page.content)

        block = tree.xpath('//*[@id="maininner"]/table/tr/th')
        startIdx = 0
        endIdx = 0
        print("**** " + self._Yoji + " ****")
        for blk in block:

            blkName, blkRow = h3_row_nb_all(self._Yoji, blk)

            startIdx = endIdx
            endIdx += blkRow
            print("Block " + blkName + ", nb row: " + str(blkRow)
                  + " [" + str(startIdx) + ";" + str(endIdx) + "].")
            subblock = tree.xpath('//*[@id="maininner"]/table/tr/td')
            for idx in range(startIdx, endIdx):
                if blkName in ['読み方', '出典']:
                    content = subblock[idx].text
                elif blkName in ['意味']:
                    content = lxml.html.tostring(subblock[idx], encoding='unicode')
                    h = html2text.HTML2Text()
                    h.ignore_links = True
                    content = h.handle(content)
                elif blkName in ['類義語', '漢字検定', '分類']:
                    if len(subblock[idx].getchildren()) > 0:
                        content = subblock[idx].getchildren()[0].text
                elif blkName in ['漢字詳細']:
                    content = '-'
                else:
                    stop_problem
                self._jitenonItem[blkName].append(content)

            print(self._jitenonItem[blkName])





def get_full_list_of_yoji():
    yojiMap = {}
    for num in range(1, 45):
        kanji_type = "yomi" + '{:02}'.format(num)
        tree = init_jitenon(kanji_type)
        yojiMap.update(get_list(kanji_type, tree))

        # listFile = r'E:\CloudStorage\Google Drive\Kanji\資料\Sources\ref_yoji_all.csv'
    with open(listFile, "w", encoding='utf-8') as f:
        for key,value in sorted(yojiMap.items(), key=lambda e: e[1][1]):
            f.write("0," + key + "," + value[1] + "," + value[0] + "\n")


def get_yojifiles():
    with open(listFile, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            page = requests.get(row[3])
            targetKanjiFile = r'E:\CloudStorage\Google Drive\Kanji\資料\Yoji_all\\' + row[1] + '.html'
            pickle.dump( page, open( targetKanjiFile, "wb" ) )

def process_yojifiles():
    with open(listFile, 'r', encoding='utf-8') as fDeck:
        csvIn = csv.reader(fDeck, delimiter=',', quotechar='"')
        for row in csvIn:
            # Only process yoji with kanji included in the DB
            if Kanji.objects.filter(kanji__in=row[1]).count() == len(set(row[1])):
                yoji = CYoji(row[1])
                yoji.ProcessJitenon()
                yj, created = Yoji.objects.get_or_create(yoji=row[1])
                yj.reading = yoji._jitenonItem['読み方'][0]
                yj.meaning = yoji._jitenonItem['意味'][0]
                if len(yoji._jitenonItem['漢字検定']) > 0 and '級' in yoji._jitenonItem['漢字検定'][0]:
                    yj.has_jitenon_kyu = True
                else:
                    yj.has_jitenon_kyu = False
                for bunrui in yoji._jitenonItem['分類']:
                    br, created = Bunrui.objects.get_or_create(bunrui=bunrui)
                    yj.bunrui.add(br)
                yj.save()


# get_full_list_of_yoji()
# get_yojifiles()
# process_yojifiles()