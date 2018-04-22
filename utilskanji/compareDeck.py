import csv
import html
import re
#import jaconv

import lxml
from lxml import html
import requests
import re
import pickle


# *****************************************************************************
# 異字同訓

def get_ijdoukun_table(ij_tree, kunyomi):
    if kunyomi == "たっとい":
        kunyomi = "たっとい・とうとい"
    if kunyomi == "たっとぶ":
        kunyomi = "たっとぶ・とうとぶ"

    if kunyomi == "とうとい" or kunyomi == "とうとぶ":
        return ""
    
    block = tree.xpath('//*[@id="iji_' + kunyomi + '"]')

    if len(block) < 1:
        block = tree.xpath('//*[@id="iji_' + kunyomi + 'だ"]')
        if len(block) < 1:
            fout_log.write("LOG_WARN get_ijdoukun not found " + kunyomi + "\n")
            fout_nf.write("ijdoukun: " + kunyomi + "\n")
            fout_nf.flush()
            return ""

    if len(block[0].getchildren()) > 3 or len(block[0].getchildren()) < 2:
        fout_log.write("LOG_WARN get_ijdoukun too many child " + kunyomi + "\n")
        
    title = block[0].getchildren()[0].text
    title = "<tr><td class='E_top'>" + title + "</td></tr>"

    words = lxml.html.tostring(block[0].getchildren()[1], encoding='unicode')
    words = re.sub("\n","",words)
    words = "<tr><td> " + words + "</td></tr>"

    footnote = ""
    if len(block[0].getchildren()) == 3:
        footnote = lxml.html.tostring(block[0].getchildren()[2], encoding='unicode')
        footnote = re.sub("\n","",footnote)
        footnote = "<tr><td> " + footnote + "</td></tr>"

    return(re.sub("\"","'",title + words + footnote))

def init_ijdoukun():
    all_contents = b''
    page_addr = 'https://joyokanji.info/iji.html?'
    for page_idx in ["a", "ka", "sa", "ta", "na", "ha", "ma", "ya", "ra", "wa"]:
        page = requests.get(page_addr + page_idx)
        all_contents = all_contents + page.content
    return html.fromstring(all_contents)


# *****************************************************************************
# 例

# EDICT file processing : http://www.edrdg.org/jmdict/edict_doc_old.html
def create_meaning_cell (line):
    m = re.search("/.*",line)
    
    # The kanji and its reading
    reading = line[:m.start()]

    # Remove the " char, replace with '
    meaning = re.sub(r"\"","'",m.group())
    # Remove the io, ik tag
    meaning = re.sub(r"\(io\) ","",meaning)
    meaning = re.sub(r"\(ik\) ","",meaning)
    # Remove the Part of Speech (POS) tags from the meaning text
    meaning = re.sub(r"/\(\D(\w|,|-)*\) ","/",meaning)
    # Remove the Regional Words part
    meaning = re.sub(r"/\(\w\w\w:\) ","",meaning)
    # Remove the final /(P)/ and /
    meaning = re.sub(r"/\(P\)/","",meaning)
    meaning = re.sub(r"/$","",meaning)

    # Split the numbered meaning
    if re.search("/\(1\) ", meaning):
        meaning = re.sub(r"/\(1\) ","<ol><li>",meaning)
        meaning = re.sub(r"/\(\d*\) ","<XXli><li>",meaning)
        meaning = re.sub(r"/", ", ", meaning)
        meaning = re.sub(r"<XXli>", "</li>", meaning) + "</li></ol>"
    else:
        meaning = re.sub(r"^/","",meaning)
        meaning = "<dl><dt>" + \
            re.sub(r"/", ", ", meaning) + "</dt></dl>"

    fout_log.write("***\n" + line + "\n")
    fout_log.write("***\n" + reading + "\n")
    fout_log.write(meaning + "\n")
    fout_log.flush()

    res = "<tr><td> " + reading + meaning + "</td></tr>"
    return res

def search_meaning (w, read_ex):
    tbl = ""
    found = 0
    fedict = open(r'edict',encoding='euc-jp')
    candidate_line = ""
    for line in fedict:
        # For single kanji, use the reading for the lookup
        if len(w) == 1:
            if line.find(w + " [" + read_ex + "]") == 0:
                fout_log.write("Found single kanji in line " + line + "\n")
                tbl = create_meaning_cell(line)
                break
        else:
            if line.find(w + " [") == 0:
                if line.find(r"/(P)/") > 0:
                    fout_log.write("Accepted common line " + line + "\n")
                    tbl = create_meaning_cell(line)
                else:
                    fout_log.write("Added line as candidate" + line + "\n")
                    candidate_line = line                  

    if tbl == "" and candidate_line != "":
        tbl = create_meaning_cell(candidate_line)

    fedict.close()
    return tbl


def create_exemple_table (list_ex, read_ex):
    tbl = ""
    if read_ex[0:1] == "▽":
        fout_log.write("▽ word: " + read_ex + "\n")
        read_ex = read_ex [1:]
        
    for w in list_ex:
        if "〔" in w:
            fout_log.write("〔x〕word: " + w + "\n")
            w = w [:-3]

        fout_log.write("****************\n Search: " + w + " (" + read_ex + ")\n")
        tbl_item = search_meaning(w, read_ex)

        if tbl_item == "":
            if w[-1:] == "だ":
                tbl_item = search_meaning(w[:-1], read_ex)

        if tbl_item == "":
            tbl_item = "<tr><td> " + w + " / not_found" + "</td></tr>"
            fout_log.write(w + " / not_found\n")
            fout_nf.write(kanji + " : " + w + "\n")
            fout_nf.flush()

        tbl += tbl_item

    return tbl

def flush_output (kanji, res_reading, res_example, res_iji):
    fout_log.write("<<<<<<  / " + kanji + "\n")
    fout_csv.write(kanji + ';"' + res_example + '"\n')
    fout_csv.flush()

# *****************************************************************************
# Class

def h3_row_nb (node):
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

katakana_chart = "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴヵヶヽヾ"
hiragana_chart = "ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔゕゖゝゞ" 

class CYomi:
    def __init__(self, reading, isHyoGai):
        self.isOn = reading[0] in katakana_chart
        self.isHyoGai = isHyoGai
        self.reading = reading
        self.formated = re.sub("（", "<span class='okuri'>", reading)
        self.formated = re.sub("）", "</span>", self.formated)

    # Return the type of Yomi as a list of Boolean: On, OnGai, Kun, KunGai
    def GetType(self):
#        print("XXXX:" + str(self.isOn) + str(self.isHyoGai) + str(self.isOn and self.isHyoGai))
        return [self.isOn and not self.isHyoGai,
                self.isOn and self.isHyoGai,
                not self.isOn and not self.isHyoGai,
                not self.isOn and self.isHyoGai]
        

class CKanji:
    listFields = ['Kanji', 'Onyomi', 'Kunyomi', 'Nanori', 'English', 'Examples', 'JLPT Level', 'Youyou Grade', 'Frequency', 'Components',
                  'Number of Strokes', 'Kanji Radical', 'Radical Number', 'Radical Strokes', 'Radical Reading', 'Traditional Form',
                  'Classification', 'Keyword', 'Traditional Radical', 'Reading Table',
                  'kjBushu', 'kjBushuMei', 'kjKanjiKentei', 'kjBunrui', 'kjIjiDoukun']
    
    def __init__(self, kanji):
        self._Kanji = kanji
        self._propList = []
        self._readingList = []
        self._readingTypeOn = 0
        self._readingTypeOnGai = 0
        self._readingTypeKun = 0
        self._readingTypeKunGai = 0

    def __iter__(self):
        return iter(self._propList)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False
        
    def __getitem__(self, key):
        idx = CKanji.listFields.index(key)
        return(self._propList[idx])
        
    def __setitem__(self, key, value):
        idx = CKanji.listFields.index(key)
        self._propList[idx] = value

    def SetFromRow(self,row):
        for idx in range(len(row)):
            self._propList = row

    def _get_kanji_file_name(self):
        return r'..\Kanji\Kanji_' + self._Kanji + '.html'

    def ProcessJitenon(self):
        page = pickle.load( open( self._get_kanji_file_name(), "rb" ) );
        tree = html.fromstring(page.content)

        block = tree.xpath('//*[@id="kanjiright"]/table/tr/th')
        startIdx = h3_row_nb(block[0]) + h3_row_nb(block[1])
        endIdx = startIdx + h3_row_nb(block[2]) + h3_row_nb(block[3])

        # issue with kanji.jineton for 平
        if self._Kanji == "平":
            endIdx += 1
        
        block = tree.xpath('//*[@id="kanjiright"]/table/tr/td')
        for idx in range(startIdx,endIdx):
            read = block[idx].getchildren()[0].text
            self._readingList.append(CYomi(read, "△" in block[idx].text))
    
    def GetNbOfReading(self):
        nbOfReading = [0, 0, 0, 0]
        for yomi in self._readingList:
            nbOfReading = [sum(x) for x in zip(nbOfReading, yomi.GetType())]
        return(nbOfReading)

    def hasGaiYomi(self):
        hasGai = [False, False]
        for yomi in self._readingList:
            hasGai = [x or y for x,y in zip(hasGai, [yomi.GetType()[i] for i in (1,3)])]
        return(hasGai)


class CKanjiDeck:
    def DiffDeck(deck1, deck2):
        diffNb = 0
        for k, v in deck1._kanjiMap.items():
            if not v == deck2._kanjiMap[k]:
                diffNb += 1
                print("Diff on key: " + k)
                for idx in range(len(CKanji.listFields)):
                    field = CKanji.listFields[idx]
                    if v[field] != deck2[k][field]:
                        print("  Diff on field: " + field)
                        print("  1. " + v[field])
                        print("  2. " + deck2[k][field])
        if diffNb == 0:
            print("No difference found")
        else:
            print(str(diffNb) + " difference(s) found")
        
    def __init__(self):
        self._kanjiMap = {}

    def __iter__(self):
        return iter(self._kanjiMap.values())

    def __getitem__(self, key):
        return self._kanjiMap[key]

    def __contains__(self, value):
        return value in self._kanjiMap

    def CreateDeckFromAnkiFile(self, fileName):
        with open(fileName, 'r', encoding='utf-8') as fDeck:
            csvIn = csv.reader(fDeck, delimiter='\t', quotechar='"')
            for row in csvIn:
                self._kanjiMap[row[0]] = CKanji(row[0])
                self._kanjiMap[row[0]].SetFromRow(row)
                
    def OutputToCsv(self, fileName):
        with open(fileName, 'w', encoding='utf-8', newline='') as fDeck:
            csvOut = csv.writer(fDeck, delimiter='\t', quotechar='"')
            for k, v in self._kanjiMap.items():
                csvOut.writerow(v)

    def ProcessJitenon(self):
        for kj in iter(self._kanjiMap.values()):
            kj.ProcessJitenon()

    def GetNbOfReading(self):
        nbOfReading = [0, 0, 0, 0]
        for kj in iter(self._kanjiMap.values()):
            nbOfReading = [sum(x) for x in zip(nbOfReading, kj.GetNbOfReading())]
        return(nbOfReading)

    # Return list: Kanji with OnYomi Gai, KunYomi Gai, eith On or Kun Gai
    def GetNbOfKanjiWithGaiYomi(self):
        nbOfKanjiWithGaiYomi = [0, 0]
        nbWithGaiOnOrKun = 0
        for kj in iter(self._kanjiMap.values()):
            hasGai = kj.hasGaiYomi()
            nbOfKanjiWithGaiYomi = [sum(x) for x in zip(nbOfKanjiWithGaiYomi, hasGai)]
            nbWithGaiOnOrKun += hasGai[0] or hasGai[1]
        nbOfKanjiWithGaiYomi.append(nbWithGaiOnOrKun)
        return(nbOfKanjiWithGaiYomi)
    
def CreateDictLink(expr):
    # location of the first bracket
    firstBracket = expr.find('（')
    word = expr
    if firstBracket > 0:
        word = expr[:firstBracket]
    return "<a href=https://dictionary.goo.ne.jp/srch/all/" + word + "/m0u/>" + expr + "</a>"
    

# *****************************************************************************
# MAIN
importFileName = r'E:\CloudStorage\Google Drive\Kanji\資料\AnkiExport/漢字.txt'
#importFileName = r'../AnkiExport/漢字 - Copie.txt'
outputFileName = r'E:\CloudStorage\Google Drive\Kanji\資料\AnkiImport/djAnkiKanji.csv'

print("start")
deck = CKanjiDeck()
deck.CreateDeckFromAnkiFile(importFileName)
print("created")
#deck.ProcessJitenon()
print("mid")
#print(deck.GetNbOfKanjiWithGaiYomi())
#print(deck.GetNbOfReading())


#To change a propery of a kanji:
#deck["万"]["Nanori"] = "Yo uuu"

DIFF_OUTFILE = True
if DIFF_OUTFILE:
    deck1 = CKanjiDeck()
    deck1.CreateDeckFromAnkiFile(importFileName)
    
    deck2 = CKanjiDeck()
    deck2.CreateDeckFromAnkiFile(outputFileName)
    CKanjiDeck.DiffDeck(deck1, deck2)
    CKanjiDeck.DiffDeck(deck2, deck1)
