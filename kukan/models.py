from django.urls import reverse
from django.db import models
from django.utils import timezone
import datetime
import re
import csv
import json
from django.db.models import Count
import markdown
from django.db.models import Max
import kukan.jautils as jau
import random
from django.core.exceptions import ValidationError


class Classification(models.Model):
    classification = models.CharField('種別', max_length=6)

    def __str__(self):
        return self.classification


class YomiJoyo(models.Model):
    yomi_joyo = models.CharField('常用漢字表', max_length=5)
    def __str__(self):
        return self.yomi_joyo


class YomiType(models.Model):
    yomi_type = models.CharField('読み種別', max_length=1)
    def __str__(self):
        return self.yomi_type


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
        return self.bushu + '　(' + self.reading + ')'


class KoukiBushu(models.Model):
    bushu = models.CharField('BUSHU', max_length=1, primary_key=True)
    variations = models.CharField('VARIATIONS', max_length=5)
    reading = models.CharField('READING', max_length=50)
    number = models.IntegerField()
    kakusu = models.IntegerField()

    def __str__(self):
        return self.bushu + '　(' + self.reading + ')'


class JisClass(models.Model):
    level = models.CharField('JIS水準', max_length=10, primary_key=True)
    def __str__(self):
        return self.level


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
        for fld in ['bushu', 'kouki_bushu','strokes', 'classification', 'kanken', 'jis']:
                    list_fld.append([ self._meta.get_field(fld).verbose_name, getattr(self, fld)])
        list_fld.append(['外部辞典', '<a href="' + self.kanjidetails.external_ref + '">漢字辞典オンライン</a>'])
        if self.kanjidetails.new_kanji is not None:
            list_fld.append(['新字体',
                             '<a href="'
                             + reverse('kukan:kanji_detail', kwargs={'pk': self.kanjidetails.new_kanji}) + '">'
                             + self.kanjidetails.new_kanji.kanji + '</a>'])
        old_kanji = Kanji.objects.filter(kanjidetails__new_kanji=self)
        if old_kanji.count()>0:
            lst = []
            for kj in old_kanji:
                lst.append('<a href="' + reverse('kukan:kanji_detail', kwargs={'pk': kj}) + '">' + kj.kanji + '</a>')
            list_fld.append(['旧字体',"、 ".join(lst)])
        return list_fld

    def get_jukiji(self):
        list_juku = []
        maps=ExMap.objects.filter(kanji=self.kanji, in_joyo_list=True, is_ateji=True)
        for jk_ex in self.example_set.filter(exmap__in=maps):
            jk = jk_ex.word
            word = re.sub(r'（.*', '', jk)
            #TODO: just to be able to do the comparaison with old data
            word = re.sub(r'（.*','' ,word)
            res = '<a href=https://dictionary.goo.ne.jp/srch/all/'
            res += word
            res += '/m0u/>'
            res += jk
            res += '</a>'
            list_juku.append(res)
        res = ''
        if len(list_juku) > 0:
            res = "<tr><td class='C_read C_special' colspan=2>"
            res += '<br>'.join(list_juku)
            res += "</td></tr>"
        return res


class KanjiDetails(models.Model):
    kanji = models.OneToOneField(Kanji, on_delete=models.CASCADE, verbose_name='漢字')
    meaning = models.TextField('意味', max_length=1000, blank=True)
    external_ref = models.CharField('外部辞典', max_length=1000, blank=True)

    new_kanji = models.ForeignKey(Kanji, related_name='kyuji', on_delete=models.CASCADE, null=True, blank=True)

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
        self.reading_simple=self.get_simple().translate(jau.kat2hir)
        super().save(*args, **kwargs)

    def get_simple(self):
        res = re.sub("（", "", self.reading)
        res = re.sub("）", "", res)
        return res

    def get_full(self):
        res = self.reading
        if self.joyo.yomi_joyo == '常用・特別':
            res = '▽' + res
        if self.joyo.yomi_joyo == '表外':
            res = '✘ ' + res
        return res

    def get_html_format(self):
        res = re.sub('（', "<span class='okuri'>", self.reading)
        res = re.sub('）', '</span>', res)
        if self.joyo.yomi_joyo == '常用・特別':
            res = '▽' + res
        if self.joyo.yomi_joyo == '表外':
            res = '✘ ' + res
        return res

    def get_list_ex(self):
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


class Example(models.Model):

    created_time = models.DateTimeField('作成日付', auto_now_add=True)
    updated_time = models.DateTimeField('変更日付', auto_now=True)
    readings = models.ManyToManyField(Reading)
    kanjis = models.ManyToManyField(Kanji, through='ExMap')
    # The 'display' version of the word - for instance the infinitive for verb, extra info, etc...
    word = models.CharField('単語', max_length=20)
    # The word as per the sentence - optional
    word_native = models.CharField('単語-例文', max_length=10, blank=True)
    yomi = models.CharField('読み方', max_length=30, blank=True)
    yomi_native = models.CharField('読み方-例文', max_length=30, blank=True)
    sentence = models.CharField('文章', max_length=300, blank=True)
    definition = models.CharField('定義', max_length=10000, blank=True)
    is_joyo = models.BooleanField('常表例')
    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')

    class Meta:
        indexes = [
            models.Index(fields=['word', 'yomi']),
            models.Index(fields=['word'])
        ]

    def __str__(self):
        return self.word

    def validate_unique(self, exclude=None):
        if not self.pk:
            if self.word[-3:] == '（諺）':
                if Example.objects.filter(word=self.word, yomi=self.yomi, sentence=self.sentence).exists():
                    raise ValidationError('この諺は既に登録されている。')
            else:
                if Example.objects.filter(word=self.word, yomi=self.yomi).exists():
                    raise ValidationError('この言葉は既に登録されている。')

    def save(self, *args, **kwargs):
        self.validate_unique()
        self.kanken=Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.word).
                                       aggregate(Max('kanken'))['kanken__max'])
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('kukan:example_detail', kwargs={'pk': self.pk})

    def get_url(self):
        link = "<a href=" + self.get_absolute_url() + ">" + self.word + "</a>"
        return link

    def get_word_native(self):
        return self.word_native if self.word_native != '' else self.word

    def goo_link(self):
        link = ''
        if self.word:
            simple = re.sub(r'（.*）', '', self.word)
            link = "<a href=https://dictionary.goo.ne.jp/srch/all/" + simple + "/m0u/>" + self.word + "</a>"
        return link

    def goo_link_exact(self):
        link = ''
        if self.word:
            simple = re.sub(r'（.*）', '', self.word)
            link = "<a href=https://dictionary.goo.ne.jp/srch/all/" + simple + "/m1u/>" \
                   + '「' + self.word + "」で一致する言葉を検索</a>"
        return link

    def get_definition_html(self):
        return markdown.markdown(self.definition)


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


class Yoji(models.Model):
    yoji = models.CharField('四字熟語', max_length=4, primary_key=True)
    reading = models.CharField('読み方', max_length=100)
    meaning = models.TextField('意味', max_length=10000, blank=True)
    # Ruigigo
    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    bunrui = models.ManyToManyField(Bunrui, blank=True)
    # True if the jitenon site gives a kanken kyu
    has_jitenon_kyu = models.BooleanField('級記有無', default=False)
    external_ref = models.CharField('外部辞典', max_length=1000, blank=True)
    in_anki = models.BooleanField('Anki', default=False)
    anki_cloze = models.CharField('Cloze sequence', max_length=4, blank=True)

    def __str__(self):
        return self.yoji

    def save(self, *args, **kwargs):
        self.kanken = Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.yoji).
                                       aggregate(Max('kanken'))['kanken__max'])
        # Only create the cloze pattern once
        if self.anki_cloze == '':
            idxList = ["11", "22"]
            random.shuffle(idxList)
            self.anki_cloze = idxList[0]+idxList[1]
        super().save(*args, **kwargs)

    def get_definition_html(self):
        return markdown.markdown(self.meaning, output_format="html5")

    def reading_as_list(self):
        return re.sub(r'（', '-（', self.reading).split('-')


class TestResult(models.Model):
    NAME_CHOICES = (
        ('OGU', '大具'),
        ('COGU', '小具'),
    )
    TEST_SOURCE_CHOICES = (
        ('TEST', '試験'),
        ('3K1', '漢字検定試験問題集３級－平成２９年版'),
        ('J2K1', '漢字検定試験問題集準２級－平成２９年版'),
        ('2K1', '漢字検定試験問題集２級－平成３０年版'),
        ('2K2', '漢字検定インターネット問題例'),
        ('2K3', '漢検過去問題集２級－平成３０年度版'),
    )

    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    date = models.DateField(verbose_name='日付')
    test_source = models.CharField(max_length=4, choices=TEST_SOURCE_CHOICES, verbose_name='問題集')
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
        return self.name + ' ' + self.kanken.kyu + ' ' + str(self.test_number) + str(self.date)