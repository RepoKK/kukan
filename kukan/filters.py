from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap
import kukan.jautils as jau
from django.db.models import Q

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


class FJisClass(FFilter):
    def __init__(self):
        super().__init__('JIS水準', 'fr-comp-jis')

    def add_to_query(self, flt, qry):
        flt = flt.split(', ')
        q = Q(jis__level__in=flt)
        if 'JIS水準不明' in flt:
            q = q | Q(jis__isnull=True)
        qry = qry.filter(q)
        return qry


class FYoji(FFilter):
    def __init__(self):
        super().__init__('漢字', 'fr-comp-yoji')

    def add_to_query(self, flt, qry):
        qry = qry.filter(yoji__contains=flt)
        return qry


class FBunrui(FFilter):
    def __init__(self):
        super().__init__('分類', 'fr-comp-bunrui')

    def add_to_query(self, flt, qry):
        qry = qry.filter(bunrui__bunrui__contains=flt).distinct()
        return qry

class FInAnki(FFilter):
    def __init__(self):
        super().__init__('Anki', 'fr-comp-in-anki')

    def add_to_query(self, flt, qry):
        if flt=='Anki':
            qry = qry.filter(in_anki=True)
        elif flt=='非Anki':
            qry = qry.filter(in_anki=False)
        return qry