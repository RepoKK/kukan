from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
import kukan.jautils as jau

class FFilter():
    type = ''
    label = ''
    value = ''

    def __init__(self, label, type):
        self.type = type
        self.label = label
        self.value = ''

    def toJSON(self):
        return "{'name':'" + self.type + "', 'label':'" + self.label + "', 'value':'" + self.value + "'}"

    def filter(self, request, qry):
        flt = request.GET.get(self.label, None)
        if flt is not None:
            qry = self.add_to_query(flt, qry)
        return qry


class FKanji(FFilter):
    def __init__(self):
        super().__init__('漢字', 'fr-comp-string-simple')

    def add_to_query(self, flt, qry):
        qry = qry.filter(kanji__in=list(flt))
        return qry


class FYomi(FFilter):
    def __init__(self):
        super().__init__('読み', 'fr-comp-string-simple')

    def add_to_query(self, flt, qry):
        readings = Reading.objects.filter(reading_simple=flt.translate(jau.kat2hir)).exclude(joyo__yomi_joyo='表外')
        qry = qry.filter(reading__in=readings)
        return qry


class FKakusu(FFilter):
    def __init__(self):
        super().__init__('画数', 'fr-comp-kakusu')

    def add_to_query(self, flt, qry):
        flt = flt.split('~')
        qry = qry.filter(strokes__gte=flt[0]).filter(strokes__lte=flt[1])
        return qry


class FExNum(FFilter):
    def __init__(self):
        super().__init__('例文数', 'fr-comp-kakusu')

    def add_to_query(self, flt, qry):
        flt = flt.split('~')
        qry = qry.filter(ex_num__gte=flt[0]).filter(ex_num__lte=flt[1])
        return qry


class FKanken(FFilter):
    def __init__(self):
        super().__init__('漢検', 'fr-comp-kanken')

    def add_to_query(self, flt, qry):
        flt = flt.split(', ')
        qry = qry.filter(kanken__kyu__in=flt)
        return qry


class FKanjiType(FFilter):
    def __init__(self):
        super().__init__('種別', 'fr-comp-type')

    def add_to_query(self, flt, qry):
        flt = flt.split(', ')
        qry = qry.filter(classification__classification__in=flt)
        return qry

class FWord(FFilter):
    def __init__(self):
        super().__init__('単語', 'fr-comp-word')

    def add_to_query(self, flt, qry):
        qry = qry.filter(word__contains=flt)
        return qry


class FSentence(FFilter):
    def __init__(self):
        super().__init__('例文', 'fr-comp-has-sentence')

    def add_to_query(self, flt, qry):
        if flt=='例文有り':
            qry = qry.exclude(sentence='')
        elif flt=='例文無し':
            qry = qry.filter(sentence='')
        return qry