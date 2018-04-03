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
    kouki_bushu = models.ForeignKey(KoukiBushu, on_delete=models.CASCADE, verbose_name='部首',
                              blank=True, null=True)
    kanken = models.ForeignKey(Kanken, on_delete=models.CASCADE, verbose_name='漢検')
    strokes = models.IntegerField('画数')
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, verbose_name='種別',
                                       blank=True, null=True)
    meaning = models.CharField('意味', max_length=1000, blank=True)
    external_ref = models.CharField('外部辞典', max_length=1000, blank=True)
    jis = models.ForeignKey(JisClass, on_delete=models.CASCADE, verbose_name='JIS水準',
                              blank=True, null=True)
    new_kanji = models.ForeignKey('self', related_name='kyuji', on_delete=models.CASCADE, null=True, blank=True)

    anki_English = models.CharField(max_length=1000)
    anki_Examples = models.CharField(max_length=1000)
    anki_Kanji_Radical = models.CharField(max_length=10)
    anki_Traditional_Form = models.CharField(max_length=10)
    anki_Traditional_Radical = models.CharField(max_length=10)
    anki_Reading_Table = models.CharField(max_length=10000)
    anki_kjBushuMei = models.CharField(max_length=100)
    anki_kjIjiDoukun = models.CharField(max_length=5000)


    def __str__(self):
        return self.kanji

    def as_dict(self):
        res = {}
        for fld in Kanji._meta.get_fields():
            if fld.concrete:
                if fld.name == 'bushu' or fld.name == 'kouki_bushu':
                    if self.bushu is not None:
                        res['bushu'] = self.bushu.bushu
                    if self.kouki_bushu is not None:
                        res['bushu'] = self.kouki_bushu.bushu
                elif fld.name == 'kanken':
                    res['kanken'] = self.kanken.kyu
                elif fld.name == 'classification':
                    if self.classification is not None:
                        res['classification'] = self.classification.classification
                    else:
                        res['classification'] = ""
                elif fld.name == 'jis' and self.jis is not None:
                    res['jis'] = self.jis.level
                elif fld.name == 'new_kanji':
                    if self.new_kanji is not None:
                        res['new_kanji'] = self.new_kanji.kanji
                    else:
                        res['new_kanji'] = ''
                else:
                    res[fld.name] = getattr(self, fld.name)
        res['ex_num'] = Example.objects.filter(kanjis=self.kanji).exclude(sentence='').count()

        res['link'] = self.pk
        return res


    @classmethod
    def fld_lst(cls):
        list_fld = []
        for fld in Kanji._meta.get_fields():
            if fld.concrete and fld.name[0:4]!='anki' and fld.name!='kouki_bushu' and fld.name!='new_kanji' and fld.name!='jis':
                list_fld.append({'label': fld.verbose_name if fld.verbose_name != '' else fld.name,
                                 'field': fld.name,
                                 # TODO: really bad way to set link
                                 'link': '/kanji/' if fld.name == 'kanji' else '',
                                 'type': '',
                                 'visible': fld.name not in ['anki_Examples', 'anki_Reading_Table',
                                                             'anki_kjIjiDoukun', 'meaning', 'external_ref']})
        list_fld.append({'label': '例文数', 'field': 'ex_num', 'link':'', 'type': '', 'visible': True})
        return list_fld

    class Meta:
        ordering = ['kanji']


    def basic_info(self):
        list_fld = []
        for fld in Kanji._meta.get_fields():
            if fld.concrete:
                if fld.verbose_name[0:4]!='anki' and fld.name!='meaning':
                    list_fld.append([fld.name, fld.verbose_name, getattr(self, fld.name)])
        return list_fld

    def basic_info2(self):
        list_fld = []
        for fld in ['bushu', 'kouki_bushu','strokes', 'classification', 'kanken', 'jis']:
                    list_fld.append([ self._meta.get_field(fld).verbose_name, getattr(self, fld)])
        list_fld.append(['外部辞典', '<a href="' + self.external_ref + '">漢字辞典オンライン</a>'])
        if self.new_kanji is not None:
            list_fld.append(['新字体',
                             '<a href="' + reverse('kukan:kanji_detail', kwargs={'pk': self.new_kanji}) + '">' + self.new_kanji.kanji + '</a>'])
        old_kanji = Kanji.objects.filter(new_kanji=self)
        if old_kanji.count()>0:
            lst = []
            for kj in old_kanji:
                lst.append('<a href="' + reverse('kukan:kanji_detail', kwargs={'pk': kj}) + '">' + kj.kanji + '</a>')
            list_fld.append(['旧字体',"、 ".join(lst)])
        return list_fld

    def meaning_list(self):
        res = ""
        if self.meaning != "":
            res = json.loads(self.meaning)
        return res


    def get_anki_read(self):
        self.reading

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


    def get_anki(self):
        root_dir = r'E:\CloudStorage\Google Drive\Kanji\資料\\'
        exportFileName = root_dir + r'AnkiImport\DjangoKanji.txt'
        with open(exportFileName, 'w', encoding='utf-8', newline='') as fDeck:
            csvOut = csv.writer(fDeck, delimiter='\t', quotechar='"')
            for kj in Kanji.objects.filter():
                csvOut.writerow([kj.kanji,
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
                                 kj.anki_Reading_Table,
                                 kj.bushu.bushu,
                                 kj.bushu.reading,
                                 kj.kanken.kyu,
                                 kj.classification,
                                 kj.anki_kjIjiDoukun])


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
        unique_together = ['word', 'yomi']
        indexes = [
            models.Index(fields=['word', 'yomi']),
            models.Index(fields=['word'])
        ]

    def __str__(self):
        return self.word

    def save(self, *args, **kwargs):
        self.kanken=Kanken.objects.get(id=Kanji.objects.filter(kanji__in=self.word).
                                       aggregate(Max('kanken'))['kanken__max'])
        super().save(*args, **kwargs)

    def as_dict(self):
        res = {}
        res['word'] = self.word
        res['yomi'] = self.yomi
        res['sentence'] = self.sentence
        res['is_joyo'] = self.is_joyo
        res['kanken'] = self.kanken.kyu
        class_date = timezone.localtime(self.updated_time)
        res['updated_time'] = class_date.strftime("%Y.%m.%d %H:%M")
        res['link'] = self.pk
        return res


    @classmethod
    def fld_lst(cls):
        list_fld = []
        for fld in ['word', 'yomi', 'sentence', 'is_joyo', 'kanken', 'updated_time']:
            fld = Example._meta.get_field(fld)
            if fld.concrete:
                list_fld.append({'label': fld.verbose_name if fld.verbose_name != '' else fld.name,
                                 'field': fld.name,
                                 'link': '/example/' if fld.name == 'word' else '',
                                 'type': 'bool' if fld.name == 'is_joyo' else '',
                                 'visible': True})
        return list_fld

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
