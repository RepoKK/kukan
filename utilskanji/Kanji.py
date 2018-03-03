import html
import lxml
from lxml import html
import re
import pickle
import jsonpickle


katakana_chart = ("ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノ"
                  "ハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヽヾ")
hiragana_chart = ("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねの"
                  "はばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖゝゞ")


def h3_row_nb(node):
    nname = node.getchildren()[0].text
    if nname in ["部首", "画数", "音読み", "訓読み"]:
        nb_row = node.attrib.get("rowspan")
        if nb_row is None:
            nb_row = 1
        else:
            nb_row = int(nb_row)
    else:
        nb_row = 0
    return nb_row


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


class CExample:
    def __init__(self, word, reading, sentence):
        self.word = word
        self.reading = reading
        self.sentence = sentence

class CYomi:
    def __init__(self, reading, isHyoGai):
        self.isOn = reading[0] in katakana_chart
        self.isHyoGai = isHyoGai
        self.reading = reading
        self.formated = re.sub("（", '<span class="okuri">', reading)
        self.formated = re.sub("）", "</span>", self.formated)
        self._example_list = []
        self._example_list.append(CExample("統帥", "トウスイ", "統帥でござる"))

    # Return the type of Yomi as a list of Boolean: On, OnGai, Kun, KunGai
    def GetType(self):
        #        print("XXXX:" + str(self.isOn) + str(self.isHyoGai) + str(self.isOn and self.isHyoGai))
        return [self.isOn and not self.isHyoGai,
                self.isOn and self.isHyoGai,
                not self.isOn and not self.isHyoGai,
                not self.isOn and self.isHyoGai]

    def tmp_enrich_with_reading_table(self, read_tbl):
        tree = html.fromstring(read_tbl)
        read_list = tree.xpath('//*[@class="C_read"]')
        #read_list = tree.cssselect('//[@class="C_read"]')
        for read_item in read_list:
            content = lxml.html.tostring(read_item, encoding='unicode')
            targ = '<td class="C_read">' + self.formated + '</td>'
            if content == targ:
                print(self.formated + self.reading)

class CKanji:
    listFields = ['Kanji', 'Onyomi', 'Kunyomi', 'Nanori', 'English', 'Examples', 'JLPT Level', 'Jouyou Grade',
                  'Frequency', 'Components',
                  'Number of Strokes', 'Kanji Radical', 'Radical Number', 'Radical Strokes', 'Radical Reading',
                  'Traditional Form',
                  'Classification', 'Keyword', 'Traditional Radical', 'Reading Table',
                  'kjBushu', 'kjBushuMei', 'kjKanjiKentei', 'kjBunrui', 'kjIjiDoukun']

    def __init__(self, kanji):
        self._Kanji = kanji
        self._propList = []
        self._readingList = []
        self._jitenonItem = {'部首':[], '画数':[], '音読み':[], '訓読み':[],
                            '漢字検定':[], '学年':[], 'JIS水準':[], '意味':[], 'Unicode':[],
                             '種別':[], '異体字':[]}

    def __iter__(self):
        return iter(self._propList)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False

    def __getitem__(self, key):
        idx = CKanji.listFields.index(key)
        return self._propList[idx]

    def __setitem__(self, key, value):
        idx = CKanji.listFields.index(key)
        self._propList[idx] = value

    def SetFromRow(self, row):
        for idx in range(len(row)):
            self._propList = row

    def _get_kanji_file_name(self):
        root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
        return root_dir + r'Kanji\Kanji_' + self._Kanji + '.html'

    def ProcessJitenon_ini(self):
        page = pickle.load(open(self._get_kanji_file_name(), "rb"));
        tree = html.fromstring(page.content)

        block = tree.xpath('//*[@id="kanjiright"]/table/tr/th')
        startIdx = h3_row_nb(block[0]) + h3_row_nb(block[1])
        endIdx = startIdx + h3_row_nb(block[2]) + h3_row_nb(block[3])

        # issue with kanji.jineton for 平
        if self._Kanji == "平":
            endIdx += 1

        block = tree.xpath('//*[@id="kanjiright"]/table/tr/td')
        for idx in range(startIdx, endIdx):
            read = block[idx].getchildren()[0].text
            self._readingList.append(CYomi(read, "△" in block[idx].text))

        self['Jouyou Grade'] = jsonpickle.encode(self._readingList)
        #for yomi in self._readingList:
        #    yomi.tmp_enrich_with_reading_table(self["Reading Table"])

    def ProcessJitenon(self):
        page = pickle.load(open(self._get_kanji_file_name(), "rb"));
        tree = html.fromstring(page.content)

        block = tree.xpath('//*[@id="kanjiright"]/table/tr/th')
        startIdx = 0
        endIdx = 0
        print("**** " + self._Kanji + " ****")
        for blk in block:
            if self._Kanji == "点" and len(blk.getchildren()) == 0: continue

            blkName, blkRow = h3_row_nb_all(self._Kanji, blk)

            # issue with kanji.jineton for 平
            if self._Kanji == "平" and blkName=='訓読み':
                blkRow += 1
            if self._Kanji == "平" and blkName=='意味':
                blkRow -= 1
            if self._Kanji == "点" and blkName=='意味':
                blkRow += 1

            startIdx = endIdx
            endIdx += blkRow
            print("Block " + blkName + ", nb row: " + str(blkRow)
                  + " [" + str(startIdx) + ";" + str(endIdx) + "].")
            subblock = tree.xpath('//*[@id="kanjiright"]/table/tr/td')
            for idx in range(startIdx, endIdx):
                if blkName in ['部首', '画数', '音読み', '訓読み', '漢字検定', '学年', '異体字']:
                    content = subblock[idx].getchildren()[0].text
                elif blkName in ['意味', 'Unicode', '種別']:
                    content = subblock[idx].text
                elif blkName in ['JIS水準']:
                    if len(subblock[idx].getchildren()) > 0:
                        content = subblock[idx].getchildren()[0].text
                    else:
                        content = subblock[idx].text
                self._jitenonItem[blkName].append(content)

            print(self._jitenonItem[blkName])

    def GetNbOfReading(self):
        nbOfReading = [0, 0, 0, 0]
        for yomi in self._readingList:
            nbOfReading = [sum(x) for x in zip(nbOfReading, yomi.GetType())]
        return (nbOfReading)

    def hasGaiYomi(self):
        hasGai = [False, False]
        for yomi in self._readingList:
            hasGai = [x or y for x, y in zip(hasGai, [yomi.GetType()[i] for i in (1, 3)])]
        return (hasGai)

    def get_json(self):
        return jsonpickle.encode(self)