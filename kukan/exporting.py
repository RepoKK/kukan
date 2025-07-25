import csv
import os
from collections import defaultdict
from functools import reduce

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import render_to_string

from kukan.anki_dj import AnkiProfile
from kukan.jautils import JpnText
from kukan.templatetags.ja_tags import furigana_ruby
from .models import Kanji, Example, Yoji


class Exporter:
    kind_list = ['anki_yoji', 'anki_kaki', 'anki_kanji', 'anki_yomi',
                 'anki_kotowaza']

    excl_in_progress = reduce(lambda x, y: x | y,
                              [Q(definition__contains=x) for x
                               in ['kaki', 'yomi', 'hyogai', 'kotowaza']])

    def __init__(self, kind, profile_name, out_dir=settings.ANKI_IMPORT_DIR):
        self.kind = kind
        self.profile = AnkiProfile(profile_name)
        self.out_dir = out_dir

    def export(self):
        if self.kind == 'all':
            self._export_all()
        else:
            self._export_kind(self.kind)

    def _export_all(self):
        for kind in self.profile.kind_list:
            if kind[0] != Example.JUKUICHI:
                self._export_kind(kind)

    def _export_kind(self, choice):
        with open(os.path.join(self.out_dir, 'dj_' + choice + '.csv'),
                  'w', newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter='\t', quotechar='"')
            writer.writerow(['#separator:tab'])
            writer.writerow(['#html:true'])
            writer.writerow(['#notetype column:1'])
            writer.writerow(['#deck column:2'])
            getattr(self, 'export_' + choice)(writer)

    @staticmethod
    def std_alt_maps():
        q_alt = Kanji.objects.filter(
            kanjidetails__std_kanji__isnull=False,
            kanjidetails__std_kanji__kanken__difficulty__gte=11
        ).select_related('kanjidetails__std_kanji')
        std_to_alt = {}
        alt_to_std = {}
        for kyo, std in [(k.kanji, k.kanjidetails.std_kanji) for k in q_alt]:
            std_to_alt.setdefault(std.kanji, []).append(kyo)
            alt_to_std[kyo] = std.kanji

        return std_to_alt, alt_to_std

    def export_anki_kaki(self, writer):
        std_to_alt, alt_to_std = Exporter.std_alt_maps()

        q_set = (Example.objects
                 .filter(ex_kind__in=[Example.KAKI, Example.TAIGI,
                                      Example.RUIGI])
                 .exclude(sentence='')
                 .exclude(kanken__difficulty__gt=11)
                 .exclude(self.excl_in_progress))
        if self.profile.name == 'Ayumi':
            q_set = q_set.filter(Q(kanken__difficulty__gte=8) |
                                 Q(ex_kind__in=[Example.TAIGI, Example.RUIGI]))

        for example in q_set:
            word = example.word_native or example.word
            yomi = example.yomi_native or example.yomi
            hyogai_tag = '<span class=tag_hyogai>表外</span>' \
                if example.is_hyogai() else ''
            sentence = furigana_ruby(hyogai_tag + example.sentence.replace(
                word, '<span class="font-color01">' + yomi + '</span>'))

            word = ''.join([alt_to_std.get(k, k) for k in word])
            alt_word = ''.join([alt[0] + ('（{}）'.format('・'.join(alt[1:]))
                                          if len(alt) > 1 else '') for alt in
                                [std_to_alt.get(k, k) for k in word]])
            if word != alt_word:
                word = word + '[{}]'.format(alt_word)

            if example.word_variation != '':
                word += '\n（{}）'.format(example.word_variation)

            writer.writerow(['Kakitori', '書き取り',
                             example.id,
                             sentence,
                             word,
                             example.kanken])

    def export_anki_yomi(self, writer):
        std_to_alt, alt_to_std = Exporter.std_alt_maps()

        q_set = Example.objects.exclude(sentence='').exclude(
            kanken__difficulty__gt=11).exclude(self.excl_in_progress)
        q_set = q_set.filter(
            Q(kanken__difficulty__gte=11) | Q(ex_kind=Example.YOMI)
        ).exclude(ex_kind=Example.KOTOWAZA)

        for example in q_set:
            word = example.word_native or example.word
            yomi = example.yomi_native or example.yomi
            hyogai_tag = '<span class=tag_hyogai>表外</span>' \
                if example.is_hyogai() else ''
            if example.ex_kind == example.JUKUICHI:
                definition = (f'<p><strong>「{example.word1}（{example.yomi1}）」'
                              f'：</strong></p>' +
                              example.get_definition_html() +
                              '<br>' +
                              f'<p><strong>「{example.word2}（{example.yomi2}）」'
                              f'：</strong></p>' +
                              example.get_definition2_html())
            else:
                definition = example.get_definition_html()

            sentence = furigana_ruby(hyogai_tag + example.sentence.replace(
                word, '<span class="font-color01">' + word + '</span>'))

            word = ''.join([alt_to_std.get(k, k) for k in word])
            alt_word = ''.join([alt[0] + ('（{}）'.format('・'.join(alt[1:]))
                                          if len(alt) > 1 else '') for alt in
                                [std_to_alt.get(k, k) for k in word]])
            if word != alt_word:
                word = word + '[{}]'.format(alt_word)

            if example.word_variation != '':
                word += '\n（{}）'.format(example.word_variation)

            writer.writerow(['Yomi',
                             '読み',
                             example.id,
                             sentence,
                             yomi,
                             definition])

    @staticmethod
    def export_anki_kotowaza(writer):
        q_set = (Example.objects.filter(ex_kind=Example.KOTOWAZA)
                 .exclude(kotowaza__isnull=True)
                 .exclude(kotowaza__yomi=''))

        for example in q_set:
            word = example.word_native or example.word
            yomi = example.yomi_native or example.yomi
            furigana = JpnText.from_furigana_format(
                example.kotowaza.furigana, word, yomi).furigana('simple', word)
            sentence = furigana.replace(
                word, '<span class="font-color01">' + yomi + '</span>')

            writer.writerow(['Kotowaza',
                             '諺',
                             example.id,
                             sentence,
                             word,
                             example.kotowaza.get_definition_html(),
                             example.kotowaza.yomi])

    @staticmethod
    def export_anki_kanji(writer):
        for kj in Kanji.objects.exclude(kanken__difficulty__gt=10):
            anki_read_table = render_to_string('kukan/AnkiReadTable.html',
                                               {'kanji': kj})
            writer.writerow(['Japanese Kanji',
                             '漢字',
                             kj.kanji,
                             kj.kanjidetails.anki_English,
                             kj.kanjidetails.anki_Examples,
                             kj.kanjidetails.anki_Kanji_Radical,
                             kj.kanjidetails.anki_Traditional_Form,
                             kj.kanjidetails.anki_Traditional_Radical,
                             anki_read_table,
                             kj.bushu.bushu,
                             kj.kanjidetails.anki_kjBushuMei,
                             kj.kanken.kyu,
                             kj.classification,
                             kj.kanjidetails.anki_kjIjiDoukun])

    @staticmethod
    def export_anki_yoji(writer):
        test_start = defaultdict(list)
        test_end = defaultdict(list)
        for yoji in Yoji.objects.filter(in_anki=True):
            test_start[yoji.yoji[0:2]].append(yoji.yoji[2:4])
            test_end[yoji.yoji[2:4]].append(yoji.yoji[0:2])

        for yoji in Yoji.objects.filter(in_anki=True):
            cloze = "{{{{c{0}::{1}::{2}}}}}{{{{c{3}::{4}::{5}}}}}".format(
                yoji.anki_cloze[0],
                yoji.yoji[0:2],
                '、'.join([x for x in test_end[yoji.yoji[2:4]]
                          if x != yoji.yoji[0:2]]),
                yoji.anki_cloze[2],
                yoji.yoji[2:4],
                '、'.join([x for x in test_start[yoji.yoji[0:2]]
                          if x != yoji.yoji[2:4]]),
            )
            writer.writerow(['Cloze Yoji',
                             '四字熟語',
                             yoji.yoji,
                             cloze,
                             yoji.reading,
                             yoji.get_definition_html()[3:-4],
                             ])


class ExporterAsResp(Exporter):
    def __init__(self, kind, profile_name):
        super().__init__(kind, profile_name)

    def export(self):
        choice = self.kind
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="dj_' \
                                          + choice + '.csv"'
        writer = csv.writer(response, delimiter='\t', quotechar='"')
        getattr(self, 'export_' + choice)(writer)

        return response
