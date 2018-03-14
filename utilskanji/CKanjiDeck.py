import csv
from utilskanji.Kanji import CKanji
from kukan.models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
import json

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
            db_kj = Kanji.objects.get(kanji=kj._Kanji)
            kj.ProcessJitenon()
            db_kj.strokes = int(kj._jitenonItem['画数'][0].replace('画',''))
            db_kj.meaning = json.dumps(kj._jitenonItem['意味'])
            db_kj.save()

    def GetNbOfReading(self):
        nbOfReading = [0, 0, 0, 0]
        for kj in iter(self._kanjiMap.values()):
            nbOfReading = [sum(x) for x in zip(nbOfReading, kj.GetNbOfReading())]
        return nbOfReading

    # Return list: Kanji with OnYomi Gai, KunYomi Gai, eith On or Kun Gai
    def GetNbOfKanjiWithGaiYomi(self):
        nb_kanji_with_gai_yomi = [0, 0]
        nb_with_gai_on_or_kun = 0
        for kj in iter(self._kanjiMap.values()):
            has_gai = kj.hasGaiYomi()
            nb_kanji_with_gai_yomi = [sum(x) for x in zip(nb_kanji_with_gai_yomi, has_gai)]
            nb_with_gai_on_or_kun += has_gai[0] or has_gai[1]
        nb_kanji_with_gai_yomi.append(nb_with_gai_on_or_kun)
        return nb_kanji_with_gai_yomi
