from django.urls import reverse
from django.db import models
from django.utils import timezone
import datetime
import re
import csv
from django.db.models import Count

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


class Bushu(models.Model):
    bushu = models.CharField('BUSHU', max_length=1, primary_key=True)
    reading = models.CharField('READING', max_length=3)
    def __str__(self):
        return self.bushu + '　(' + self.reading + ')'


class Kanji(models.Model):
    update_time = models.DateTimeField('変更日付')

    kanji = models.CharField('漢字', max_length=1, primary_key=True)
    bushu = models.ForeignKey(Bushu, on_delete=models.CASCADE, verbose_name='部首')
    kanken_kyu = models.CharField('漢字検定', max_length=3)
    strokes = models.IntegerField('画数')
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, verbose_name='種別')

    jukuji = models.CharField('熟字・当て字', max_length=200, blank=True)

    anki_Kanji = models.CharField(max_length=10)
    anki_Onyomi = models.CharField(max_length=100)
    anki_Kunyomi = models.CharField(max_length=100)
    anki_Nanori = models.CharField(max_length=100)
    anki_English = models.CharField(max_length=1000)
    anki_Examples = models.CharField(max_length=1000)
    anki_JLPT_Level = models.CharField(max_length=10)
    anki_Jouyou_Grade = models.CharField(max_length=10)
    anki_Frequency = models.CharField(max_length=10)
    anki_Components = models.CharField(max_length=1000)
    anki_Number_of_Strokes = models.CharField(max_length=10)
    anki_Kanji_Radical = models.CharField(max_length=10)
    anki_Radical_Number = models.CharField(max_length=10)
    anki_Radical_Strokes = models.CharField(max_length=10)
    anki_Radical_Reading = models.CharField(max_length=10)
    anki_Traditional_Form = models.CharField(max_length=10)
    anki_Classification = models.CharField(max_length=10)
    anki_Keyword = models.CharField(max_length=100)
    anki_Traditional_Radical = models.CharField(max_length=10)
    anki_Reading_Table = models.CharField(max_length=10000)
    anki_kjBushu = models.CharField(max_length=10)
    anki_kjBushuMei = models.CharField(max_length=100)
    anki_kjKanjiKentei = models.CharField(max_length=10)
    anki_kjBunrui = models.CharField(max_length=10)
    anki_kjIjiDoukun = models.CharField(max_length=5000)


    def __str__(self):
        return self.kanji


    def save(self, *args, **kwargs):
        self.pub_date = datetime.now()
        super(models.Model, self).save(*args, **kwargs)


    def as_dict(self):
        res = {}
        for fld in Kanji._meta.get_fields():
            if fld.concrete:
                if fld.name == 'bushu':
                    res['bushu'] = self.bushu.bushu
                elif fld.name == 'classification':
                    res['classification'] = self.classification.classification
                else:
                    res[fld.name] = getattr(self, fld.name)
        return res


    @classmethod
    def fld_lst(cls):
        list_fld = []
        for fld in Kanji._meta.get_fields():
            if fld.concrete:
                list_fld.append({'title': fld.verbose_name if fld.verbose_name != '' else fld.name,
                                 'field': fld.name,
                                 'visible': fld.name not in ['anki_Examples', 'anki_Reading_Table', 'anki_kjIjiDoukun']})
        return list_fld

    class Meta:
        ordering = ['kanji']

    def get_absolute_url(self):
        return reverse('kukan:kanji', kwargs={'pk': self.pk})

    def basic_info(self):
        list_fld = []
        for fld in Kanji._meta.get_fields():
            if fld.concrete:
                if fld.verbose_name[0:4]!='anki':
                    list_fld.append([fld.name, fld.verbose_name, getattr(self, fld.name)])
        return list_fld

    def get_anki_read(self):
        self.reading

    def get_jukiji_old(self):
        list_juku = []
        for jk in self.jukuji.split(','):
            jk = jk.replace(' ', '')
            word = re.sub(r'（.*', '', jk)
            #TODO: just to be able to do the comparaison with old data
            word = re.sub(r'（.*','' ,word)
            res = '<a href=https://dictionary.goo.ne.jp/srch/all/'
            res += word
            res += '/m0u/>'
            res += jk
            res += '</a>'
            list_juku.append(res)
        return '<br>'.join(list_juku)

    def get_jukiji(self):
        list_juku = []
        for jk_ex in self.example_set.annotate(num_readings=Count('exmap__reading')).filter(num_readings=0).order_by('exmap__id'):
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
                                 kj.kanken_kyu,
                                 kj.classification,
                                 kj.anki_kjIjiDoukun])


class Reading(models.Model):
    kanji = models.ForeignKey(Kanji, on_delete=models.CASCADE, verbose_name='漢字')
    reading = models.CharField('読み', max_length=20)
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
        return list_ex

    def get_list_ex_anki(self):
        list_ex = "、".join(map(Example.goo_link,
                               Example.objects.filter(exmap__reading=self,
                                                      exmap__in_joyo_list=True)))
        return list_ex

    def is_joyo(self):
        return self.joyo.yomi_joyo != '表外'



class Example(models.Model):
    readings = models.ManyToManyField(Reading)
    kanjis = models.ManyToManyField(Kanji, through='ExMap')
    word = models.CharField('例', max_length=5)
    yomi = models.CharField('読み方', max_length=30, blank=True)
    sentence = models.CharField('文章', max_length=300, blank=True)
    definition = models.CharField('定義', max_length=2000, blank=True)
    is_joyo = models.BooleanField('常用漢字表の例')

    class Meta:
        unique_together = ['word', 'yomi']
        indexes = [
            models.Index(fields=['word', 'yomi']),
            models.Index(fields=['word'])
        ]

    def get_absolute_url(self):
        return reverse('example_detail', kwargs={'pk': self.pk})

    def __str__(self):
        return self.word

    def get_absolute_url(self):
        return reverse('kukan:example_detail', kwargs={'pk': self.pk})

    def get_url(self):
        link = "<a href=" + self.get_absolute_url() + ">" + self.word + "</a>"
        return link

    def goo_link(self):
        link = ''
        if self.word:
            simple = re.sub(r'（.*）','' ,self.word)
            link = "<a href=https://dictionary.goo.ne.jp/srch/all/" + simple + "/m0u/>" + self.word + "</a>"
        return link


class ExMap(models.Model):
    example = models.ForeignKey(Example, on_delete=models.CASCADE)
    kanji = models.ForeignKey(Kanji, on_delete=models.CASCADE)
    reading = models.ForeignKey(Reading,
                                on_delete=models.CASCADE,
                                null = True,
                                blank=True)
    in_joyo_list = models.BooleanField()
    map_order = models.IntegerField()

    class Meta:
        ordering = ['map_order']

    def __str__(self):
        return self.kanji.kanji + ' - ' + self.example.word