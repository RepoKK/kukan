import itertools as it
import json
import logging
import random
import re

import markdown
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.urls import reverse
from django.utils.functional import cached_property

import kukan.jautils as jau
from utils_django.decorators import OrderFromAttr, QuickGetKey

logger = logging.getLogger(__name__)


class Classification(models.Model):
    classification = models.CharField('種別', max_length=6)

    def __str__(self):
        return self.classification


@QuickGetKey('yomi_joyo')
class YomiJoyo(models.Model):
    yomi_joyo = models.CharField('常用漢字表', max_length=5)

    def __str__(self):
        return self.yomi_joyo


@QuickGetKey('yomi_type')
class YomiType(models.Model):
    yomi_type = models.CharField('読み種別', max_length=1)

    def __str__(self):
        return self.yomi_type


@OrderFromAttr('difficulty')
@QuickGetKey('kyu')
class Kanken(models.Model):
    kyu = models.CharField('漢字検定', max_length=3)
    difficulty = models.IntegerField()

    item_01_name = models.CharField(max_length=20, blank=True)
    item_01 = models.IntegerField(default=0, verbose_name='一')
    item_02_name = models.CharField(max_length=20, blank=True)
    item_02 = models.IntegerField(default=0, verbose_name='二')
    item_03_name = models.CharField(max_length=20, blank=True)
    item_03 = models.IntegerField(default=0, verbose_name='三')
    item_04_name = models.CharField(max_length=20, blank=True)
    item_04 = models.IntegerField(default=0, verbose_name='四')
    item_05_name = models.CharField(max_length=20, blank=True)
    item_05 = models.IntegerField(default=0, verbose_name='五')
    item_06_name = models.CharField(max_length=20, blank=True)
    item_06 = models.IntegerField(default=0, verbose_name='六')
    item_07_name = models.CharField(max_length=20, blank=True)
    item_07 = models.IntegerField(default=0, verbose_name='七')
    item_08_name = models.CharField(max_length=20, blank=True)
    item_08 = models.IntegerField(default=0, verbose_name='八')
    item_09_name = models.CharField(max_length=20, blank=True)
    item_09 = models.IntegerField(default=0, verbose_name='九')
    item_10_name = models.CharField(max_length=20, blank=True)
    item_10 = models.IntegerField(default=0, verbose_name='十')

    success_line = models.IntegerField(default=0, verbose_name='合格基準')

    def __str__(self):
        return self.kyu

    class Meta:
        ordering = ['difficulty']


class Bushu(models.Model):
    bushu = models.CharField('BUSHU', max_length=1, primary_key=True)
    reading = models.CharField('READING', max_length=3)

    def __str__(self):
        return f'{self.bushu}　({self.reading})'


class KoukiBushu(models.Model):
    bushu = models.CharField('BUSHU', max_length=1, primary_key=True)
    variations = models.CharField('VARIATIONS', max_length=5)
    reading = models.CharField('READING', max_length=50)
    number = models.IntegerField()
    kakusu = models.IntegerField()

    def __str__(self):
        return f'{self.bushu}　({self.reading})'


class JisClass(models.Model):
    level = models.CharField('JIS水準', max_length=10, primary_key=True)

    def __str__(self):
        return self.level


@QuickGetKey('kanji')
class Kanji(models.Model):
    kanji = models.CharField('漢字', max_length=1, primary_key=True)
    bushu = models.ForeignKey(Bushu, on_delete=models.CASCADE, verbose_name='部首',
                              blank=True, null=True)
    kouki_bushu = models.ForeignKey(KoukiBushu, on_delete=models.CASCADE, verbose_name='康煕部首',
                                    blank=True, null=True)
    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    strokes = models.IntegerField('画数')
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, verbose_name='種別',
                                       blank=True, null=True)
    jis = models.ForeignKey(JisClass, on_delete=models.CASCADE, verbose_name='JIS水準',
                            blank=True, null=True)

    def __str__(self):
        return self.kanji

    def basic_info2(self):
        list_fld = []
        for fld in ['bushu', 'kouki_bushu', 'strokes', 'classification', 'kanken', 'jis']:
            list_fld.append([self._meta.get_field(fld).verbose_name, getattr(self, fld)])
        list_fld.append(['外部辞典', '<a href="' + self.kanjidetails.external_ref + '">漢字辞典オンライン</a>'])

        if self.jitai['std'][1] == self and self.jitai['alt']:
            lst = []
            for kj in self.jitai['alt'][1]:
                lst.append('<a href="' + reverse('kukan:kanji_detail', kwargs={'pk': kj}) + '">' + kj.kanji + '</a>')
            list_fld.append([self.jitai['alt'][0], "、 ".join(lst)])

        if self.jitai['std'][1] != self:
            if self.kanjidetails.std_kanji is not None:
                list_fld.append(['標準字体',
                                 '<a href="'
                                 + reverse('kukan:kanji_detail', kwargs={'pk': self.jitai['std'][1]}) + '">'
                                 + str(self.jitai['std'][1].kanji) + '</a>'])
        return list_fld

    @cached_property
    def jitai(self):
        jitai_dict = {}
        std_kanji = self.kanjidetails.std_kanji or self
        jitai_dict['std'] = ['標準字体', std_kanji]
        jitai_dict['alt'] = ['許容字体' if std_kanji.kanken.difficulty > 10 else '旧字体',
                             list(Kanji.objects.filter(kanjidetails__std_kanji=std_kanji))]
        if not jitai_dict['alt'][1]:
            jitai_dict['alt'][0] = None
        return jitai_dict

    def get_jukuji(self):
        list_jukuji = []
        maps = ExMap.objects.filter(kanji=self.kanji, in_joyo_list=True, is_ateji=True)
        for jk_ex in self.example_set.filter(exmap__in=maps):
            jk = jk_ex.word
            word = re.sub(r'（.*', '', jk)
            # TODO: just to be able to do the comparison with old data
            word = re.sub(r'（.*', '', word)
            res = '<a href=https://dictionary.goo.ne.jp/srch/all/'
            res += word
            res += '/m0u/>'
            res += jk
            res += '</a>'
            list_jukuji.append(res)
        res = ''
        if len(list_jukuji) > 0:
            res = "<tr><td class='C_read C_special' colspan=2>"
            res += '<br>'.join(list_jukuji)
            res += "</td></tr>"
        return res


class KanjiDetails(models.Model):
    kanji = models.OneToOneField(Kanji, on_delete=models.CASCADE, verbose_name='漢字')
    meaning = models.TextField('意味', max_length=1000, blank=True)
    external_ref = models.CharField('外部辞典', max_length=1000, blank=True)

    std_kanji = models.ForeignKey(Kanji, related_name='kyoyojitai', on_delete=models.CASCADE, null=True, blank=True)

    anki_English = models.CharField(max_length=1000, blank=True)
    anki_Examples = models.CharField(max_length=1000, blank=True)
    anki_Kanji_Radical = models.CharField(max_length=10, blank=True)
    anki_Traditional_Form = models.CharField(max_length=10, blank=True)
    anki_Traditional_Radical = models.CharField(max_length=10, blank=True)
    anki_Reading_Table = models.CharField(max_length=10000, blank=True)
    anki_kjBushuMei = models.CharField(max_length=100, blank=True)
    anki_kjIjiDoukun = models.CharField(max_length=5000, blank=True)

    def meaning_list(self):
        res = ""
        if self.meaning != "":
            res = json.loads(self.meaning)
        return res


class Reading(models.Model):
    kanji = models.ForeignKey(Kanji, on_delete=models.CASCADE, verbose_name='漢字')
    reading = models.CharField('読み', max_length=20)
    reading_simple = models.CharField('読み', max_length=20)
    yomi_type = models.ForeignKey(YomiType, on_delete=models.CASCADE, verbose_name='音訓')
    joyo = models.ForeignKey(YomiJoyo, on_delete=models.CASCADE, verbose_name='常用漢字表')
    joyo_order = models.IntegerField('常用漢字表・順番', blank=True)
    remark = models.CharField('備考', max_length=200, blank=True)
    ijidokun = models.CharField('異字同訓', max_length=200, blank=True)

    class Meta:
        unique_together = ["kanji", "reading"]
        ordering = ['yomi_type', 'joyo_order']

    def __str__(self):
        return self.kanji.kanji + ' - ' + self.reading

    def save(self, *args, **kwargs):
        self.reading_simple = self.get_simple().translate(jau.kat2hir)
        super().save(*args, **kwargs)

    def get_simple(self):
        res = re.sub("（", "", str(self.reading))
        res = re.sub("）", "", res)
        return res

    def get_full(self):
        res = self.reading
        if self.joyo.yomi_joyo == '常用・特別':
            res = '▽' + str(res)
        if self.joyo.yomi_joyo == '表外':
            res = '✘ ' + res
        return res

    def get_html_format(self):
        res = re.sub('（', "<span class='okuri'>", str(self.reading))
        res = re.sub('）', '</span>', res)
        if self.joyo.yomi_joyo == '常用・特別':
            res = '▽' + res
        if self.joyo.yomi_joyo == '表外':
            res = '✘ ' + res
        return res

    def get_list_ex(self):
        # noinspection PyUnresolvedReferences
        list_ex = "、".join(map(Example.get_url, list(self.example_set.all())))
        return list_ex

    def get_list_ex2(self):
        list_ex = "、".join(map(Example.get_url,
                               Example.objects.filter(exmap__reading=self,
                                                      exmap__in_joyo_list=True)))
        list_ex_non_joyo = "、".join(map(Example.get_url,
                                        Example.objects.filter(exmap__reading=self,
                                                               exmap__in_joyo_list=False)))
        if list_ex_non_joyo != '':
            list_ex += ' / ' + list_ex_non_joyo

        return list_ex

    def get_list_ex_anki(self):
        list_ex = "、".join(map(Example.goo_link,
                               Example.objects.filter(exmap__reading=self,
                                                      exmap__in_joyo_list=True)))
        return list_ex

    def is_joyo(self):
        return self.joyo.yomi_joyo != '表外'


class Kotowaza(models.Model):
    kotowaza = models.CharField('諺', max_length=100)
    yomi = models.CharField('読み方', max_length=100, blank=True)
    furigana = models.CharField('振り仮名', max_length=200, blank=True)
    definition = models.CharField('諺の意味', max_length=10000, blank=True)

    def __str__(self):
        return '{1} - {0}'.format(self.kotowaza, self.pk)

    def get_absolute_url(self):
        return reverse('kukan:kotowaza_detail', kwargs={'pk': self.pk})

    def get_definition_html(self):
        return markdown.markdown(self.definition)


class Example(models.Model):
    KAKI = 'KAKI'
    YOMI = 'YOMI'
    HYOGAI = 'HYOGAI'
    TAIGI = 'TAIGI'
    RUIGI = 'RUIGI'
    KOTOWAZA = 'KOTOWAZA'
    JUKUICHI = 'JUKUICHI'
    EX_KIND_CHOICES = (
        (KAKI, '書き取り'),
        (YOMI, '読み'),
        (HYOGAI, '表外読み'),
        (TAIGI, '対義語'),
        (RUIGI, '類義語'),
        (KOTOWAZA, '故事・諺'),
        (JUKUICHI, '熟語と一字訓'),
    )

    ex_kind = models.CharField(max_length=8, verbose_name='種類', choices=EX_KIND_CHOICES, default=KAKI)
    kotowaza = models.ForeignKey(Kotowaza, on_delete=models.CASCADE, verbose_name='諺', null=True, blank=True)

    created_time = models.DateTimeField('作成日付', auto_now_add=True)
    updated_time = models.DateTimeField('変更日付', auto_now=True)
    readings = models.ManyToManyField(Reading)
    kanjis = models.ManyToManyField(Kanji, through='ExMap')
    # The 'display' version of the word - for instance the infinitive for verb, extra info, etc...
    word = models.CharField('単語', max_length=20)
    # The word as per the sentence - optional
    word_native = models.CharField('単語（例文）', max_length=10, blank=True)
    yomi = models.CharField('読み方', max_length=30, blank=True)
    yomi_native = models.CharField('読み方（例文）', max_length=30, blank=True)
    word_variation = models.CharField('他の書き方', max_length=20, blank=True)
    sentence = models.CharField('例文', max_length=300, blank=True)
    definition = models.CharField('意味', max_length=10000, blank=True)
    definition2 = models.CharField('意味（乙）', max_length=10000, blank=True)
    is_joyo = models.BooleanField('常表例')
    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')

    @property
    def word1(self):
        return self.split_and_get(self.word, 0)

    @property
    def word2(self):
        return self.split_and_get(self.word, 1)

    @property
    def yomi1(self):
        return self.split_and_get(self.yomi, 0)

    @property
    def yomi2(self):
        return self.split_and_get(self.yomi, 1)

    class Meta:
        indexes = [
            models.Index(fields=['word', 'yomi']),
            models.Index(fields=['word'])
        ]

    def __str__(self):
        return self.word

    @staticmethod
    def split_and_get(field, index):
        try:
            return field.split('・')[index]
        except IndexError:
            return ''


    def validate_unique(self, exclude=None):
        if not self.pk:
            if self.ex_kind == Example.KOTOWAZA:
                if Example.objects.filter(word=self.word, yomi=self.yomi, sentence=self.sentence).exists():
                    raise ValidationError('この諺は既に登録されている。')
            elif self.ex_kind in [Example.RUIGI, Example.TAIGI]:
                if Example.objects.filter(word=self.word, yomi=self.yomi, sentence=self.sentence).exists():
                    raise ValidationError('この対義語・類義語は既に登録されている。')
            else:
                if Example.objects.filter(word=self.word, yomi=self.yomi, ex_kind=self.ex_kind).exists():
                    raise ValidationError('この言葉は既に登録されている。')

    def save(self, *args, **kwargs):
        self.validate_unique()
        kanken = Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.word).
                                    aggregate(Max('kanken'))['kanken__max'])
        # Any example with 表外 reading is at least 準一級
        if (self.pk is not None
                and kanken.difficulty < Kanken.objects.get(kyu='準１級').difficulty
                and Reading.objects.filter(exmap__example__pk=self.pk, joyo__yomi_joyo='表外').exists()):
            kanken = Kanken.objects.get(kyu='準１級')
        self.kanken = kanken

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('kukan:example_detail', kwargs={'pk': self.pk})

    def get_url(self):
        link = "<a href=" + self.get_absolute_url() + ">" + str(self.word) + "</a>"
        return link

    def get_word_native(self):
        return str(self.word_native or self.word)

    def goo_link(self):
        link = ''
        if self.word:
            simple = re.sub(r'（.*）', '', str(self.word))
            link = "<a href=https://dictionary.goo.ne.jp/srch/all/" + simple + "/m0u/>{}</a>".format(
                self.word)
        return link

    def goo_link_exact(self):
        link = ''
        if self.word:
            simple = re.sub(r'（.*）', '', str(self.word))
            link = "<a href=https://dictionary.goo.ne.jp/srch/all/" + simple + "/m1u/>" \
                   + '「' + str(self.word) + "」で一致する言葉を検索</a>"
        return link

    def get_definition_html(self):
        return markdown.markdown(self.definition)

    def get_definition2_html(self):
        return markdown.markdown(self.definition2)

    def is_hyogai(self):
        return ((Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.word).
                                    aggregate(Max('kanken'))['kanken__max'])
                 <= Kanken.objects.get(kyu='２級'))
                and
                (self.kanken >= Kanken.objects.get(kyu='準１級')))

    @transaction.atomic
    def create_exmap(self, reading_selected: list):
        """
        Recreate the links between the word and the Reading. Old mappings not relevant anymore are deleted
        :param reading_selected: list of Reading ID, in the order of the kanji of the word.
                "Ateji_<kanji>" can be used as well. Example: "1245, Ateji_宴"
        """

        self.save()

        # Filter out all characters not in the Kanji database (Kana, ...)
        word = [x for x in self.get_word_native() if Kanji.objects.filter(kanji=x).exists()]

        if len(word) != len(reading_selected):
            logger.error(f'Kanji and reading number mismatch for {self}({self.pk}); '
                         f'{len(word)} kanji and {len(reading_selected)} readings; '
                         f'word: {word}, reading_selected: {reading_selected}')
            raise AssertionError('Reading number mismatch')

        # Ensure we're not trying to change readings of a Joyo Kanji
        joyo_exmaps = ExMap.objects.filter(example=self, in_joyo_list=True).order_by('map_order')
        joyo_exmaps_per_order = {x.map_order: x for x in joyo_exmaps}
        try:
            for joyo_exmap in joyo_exmaps:
                i = joyo_exmap.map_order
                if joyo_exmap.is_ateji:
                    reading_match = reading_selected[i] == f'Ateji_{joyo_exmap.kanji}'
                else:
                    reading_match = reading_selected[i] == str(joyo_exmap.reading.id)
                if not (joyo_exmap.kanji.kanji == word[i] and reading_match):
                    raise AssertionError
        except (AssertionError, IndexError):
            logger.error(f'Trying to modify a Joyo reading for {self}({self.pk}); '
                         f'word: {word}, reading_selected: {reading_selected}')
            raise AssertionError('Existing Joyo reading cannot be modified')

        map_list = []
        for map_order, (kj, reading) in enumerate(zip(word, reading_selected)):
            kanji = Kanji.qget(kj)

            if map_order in joyo_exmaps_per_order.keys():
                ex_map = joyo_exmaps_per_order[map_order]
            elif reading[:6] == 'Ateji_':
                ex_map, create = self.exmap_set.get_or_create(kanji=kanji,
                                                              example=self,
                                                              map_order=map_order,
                                                              is_ateji=True,
                                                              in_joyo_list=False)
            else:
                ex_map, create = self.exmap_set.get_or_create(kanji=kanji,
                                                              reading=Reading.objects.get(kanji=kj, id=reading),
                                                              example=self,
                                                              map_order=map_order,
                                                              is_ateji=False,
                                                              in_joyo_list=False)
            map_list.append(ex_map.id)

        # Delete the maps not relevant anymore
        ExMap.objects.filter(example=self).exclude(id__in=map_list).delete()

        # Save again to trigger the update of the Kyu done part of Example.save (issue #27)
        self.save()
        logger.info(f'Modified {self}({self.pk}) with reading_selected: {reading_selected}')

    @staticmethod
    def find_yomi_pk(word, yomi):
        """
        Given a word (kanji) and its yomi (kana), return a matching combination a Reading IDs.
        The first matching combination is returned, which could lead to incorrect answer in rare case.

        :param word: word in kanji
        :param yomi: its reading in Kana
        :return: list of Reading objects ids, which lead to the word / yomi
        """
        data = []
        yomi = yomi.translate(jau.hir2kat).replace('・', '')
        for candidate in it.product(*filter(None, (Reading.objects.filter(kanji=kj) for kj in word))):
            if ''.join([re.sub('[（）]', '', r.reading.translate(jau.hir2kat)) for r in candidate]) == yomi:
                data = [r.id for r in candidate]
                break
        return data


class ExMap(models.Model):
    example = models.ForeignKey(Example, on_delete=models.CASCADE)
    kanji = models.ForeignKey(Kanji, on_delete=models.CASCADE)
    reading = models.ForeignKey(Reading,
                                on_delete=models.CASCADE,
                                null=True,
                                blank=True)
    is_ateji = models.BooleanField()
    ateji_option_disp = '当て字・熟字'
    in_joyo_list = models.BooleanField()
    map_order = models.IntegerField()

    class Meta:
        ordering = ['map_order']

    def __str__(self):
        return self.kanji.kanji + ' - ' + self.example.word


class Bunrui(models.Model):
    bunrui = models.CharField('分類', max_length=50)

    def __str__(self):
        return self.bunrui


@QuickGetKey('yoji')
class Yoji(models.Model):
    yoji = models.CharField('四字熟語', max_length=4, primary_key=True)
    reading = models.CharField('読み方', max_length=100)
    meaning = models.TextField('意味', max_length=10000, blank=True)

    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    bunrui = models.ManyToManyField(Bunrui, blank=True)
    # True if the jitenon site gives a kanken kyu
    has_jitenon_kyu = models.BooleanField('級記有無', default=False)
    external_ref = models.CharField('外部辞典', max_length=1000, blank=True)
    in_anki = models.BooleanField('日課', default=False)
    anki_cloze = models.CharField('Cloze sequence', max_length=4, blank=True)

    def __str__(self):
        return self.yoji

    def save(self, *args, **kwargs):
        self.kanken = Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.yoji).
                                         aggregate(Max('kanken'))['kanken__max'])
        # Only create the cloze pattern once
        if self.anki_cloze == '':
            idx_list = ["11", "22"]
            random.shuffle(idx_list)
            self.anki_cloze = idx_list[0] + idx_list[1]
        super().save(*args, **kwargs)

    def get_definition_html(self):
        return markdown.markdown(self.meaning, output_format="html5")

    def reading_as_list(self):
        return re.sub(r'（', '-（', str(self.reading)).split('-')


class TestSource(models.Model):
    series = models.CharField(max_length=50, verbose_name='問題集')
    kyu = models.CharField(max_length=20, verbose_name='級')
    year = models.CharField(max_length=20, verbose_name='年度')
    section = models.CharField(max_length=20, verbose_name='区分', blank=True, default='')

    def __str__(self):
        return f'{self.series} - {self.kyu} - {self.year}' \
               + ('' if not self.section else f' ({self.section})')


class TestResult(models.Model):
    NAME_CHOICES = (
        ('OGU', '大具'),
        ('COGU', '小具'),
    )

    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    date = models.DateField(verbose_name='日付')
    source = models.ForeignKey(TestSource, on_delete=models.PROTECT, verbose_name='問題元')
    test_number = models.IntegerField(default=0, verbose_name='問題番号')
    name = models.CharField(max_length=4, choices=NAME_CHOICES, verbose_name='名前')

    item_01 = models.IntegerField(default=0, verbose_name='一')
    item_02 = models.IntegerField(default=0, verbose_name='二')
    item_03 = models.IntegerField(default=0, verbose_name='三')
    item_04 = models.IntegerField(default=0, verbose_name='四')
    item_05 = models.IntegerField(default=0, verbose_name='五')
    item_06 = models.IntegerField(default=0, verbose_name='六')
    item_07 = models.IntegerField(default=0, verbose_name='七')
    item_08 = models.IntegerField(default=0, verbose_name='八')
    item_09 = models.IntegerField(default=0, verbose_name='九')
    item_10 = models.IntegerField(default=0, verbose_name='十')

    score = models.IntegerField(editable=False, default=0, verbose_name='総合得点')

    def save(self, *args, **kwargs):
        self.score = 0
        for i in range(1, 11):
            self.score += getattr(self, 'item_{:02d}'.format(i))
        super().save(*args, **kwargs)

    def __str__(self):
        return '{} {} {} - {}'.format(self.name, self.kanken.kyu, self.test_number, self.date)
