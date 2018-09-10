import os, csv
from functools import reduce
from collections import defaultdict
from .models import Kanji, YomiType, YomiJoyo, Reading, Example, ExMap, Yoji, TestResult, Kotowaza
from django.db.models import Q
from django.template.loader import render_to_string
from django.conf import settings


class Exporter:
    type_list = ['anki_yoji', 'anki_kaki_ayu', 'anki_kaki_fred',
                 'anki_kanji', 'anki_yomi', 'anki_kotowaza']

    def __init__(self, type, out_dir=settings.ANKI_IMPORT_DIR):
        self.type = type
        self.out_dir = out_dir

    def export(self):
        if self.type == 'all':
            self._export_all()
        else:
            self._export_type(self.type)

    def _export_all(self):
        for type in self.type_list:
            self._export_type(type)

    def _export_type(self, choice):
        with open(os.path.join(self.out_dir, 'dj_' + choice + '.csv'), 'w', newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter='\t', quotechar='"')

            if choice[0:9] == 'anki_kaki':
                self.export_anki_kakitori(writer, choice)
            elif choice == 'anki_yoji':
                self.export_anki_yoji(writer)
            elif choice == 'anki_kanji':
                self.export_anki_kanji(writer)
            elif choice == 'anki_yomi':
                self.export_anki_yomi(writer)
            elif choice == 'anki_kotowaza':
                self.export_anki_kotowaza(writer)


    @staticmethod
    def std_alt_maps():
        q_alt = Kanji.objects.filter(kanjidetails__std_kanji__isnull=False,
                                     kanjidetails__std_kanji__kanken__difficulty__gte=11
                                     ).select_related('kanjidetails__std_kanji')
        std_to_alt = {}
        alt_to_std = {}
        for kyo, std in [(k.kanji, k.kanjidetails.std_kanji) for k in q_alt]:
            std_to_alt.setdefault(std.kanji, []).append(kyo)
            alt_to_std[kyo] = std.kanji

        return std_to_alt, alt_to_std


    @staticmethod
    def export_anki_kakitori(writer, choice):
        std_to_alt, alt_to_std = Exporter.std_alt_maps()

        excl_in_progress = reduce(lambda x, y: x | y,
                                  [Q(definition__contains=x) for x in ['kaki', 'yomi', 'hyogai', 'kotowaza']])
        q_set = Example.objects.exclude(sentence='').exclude(kanken__difficulty__gt=11).exclude(excl_in_progress)
        if choice == 'anki_kaki_ayu':
            q_set = q_set.filter(Q(kanken__difficulty__gte=8) | Q(word__endswith='義語）'))

        for example in q_set:
            word = example.word_native if example.word_native != "" else example.word
            yomi = example.yomi_native if example.yomi_native != "" else example.yomi
            sentence = example.sentence.replace(word,
                                                '<span class="font-color01">' +
                                                yomi + '</span>')

            word = ''.join([alt_to_std.get(k, k) for k in word])
            alt_word = ''.join([alt[0] + ('（{}）'.format('・'.join(alt[1:])) if len(alt) > 1 else '') for alt in
                                [std_to_alt.get(k, k) for k in word]])
            if word != alt_word:
                word = word + '[{}]'.format(alt_word)

            if example.word_variation != '':
                word += '\n（{}）'.format(example.word_variation)

            writer.writerow([example.id,
                             sentence,
                             word,
                             example.kanken])


    @staticmethod
    def export_anki_yomi(writer):
        std_to_alt, alt_to_std = Exporter.std_alt_maps()

        excl_in_progress = reduce(lambda x, y: x | y,
                                  [Q(definition__contains=x) for x in ['kaki', 'yomi', 'hyogai', 'kotowaza']])
        q_set = Example.objects.exclude(sentence='').exclude(kanken__difficulty__gt=11).exclude(excl_in_progress)
        q_set = q_set.filter(
            Q(kanken__difficulty__gte=11) | Q(ex_type=Example.TypeChoice.YOMI.name)
        ).exclude(ex_type=Example.TypeChoice.KOTOWAZA.name)

        for example in q_set:
            word = example.word_native if example.word_native != "" else example.word
            yomi = example.yomi_native if example.yomi_native != "" else example.yomi
            sentence = example.sentence.replace(word,
                                                '<span class="font-color01">' +
                                                word + '</span>')

            word = ''.join([alt_to_std.get(k, k) for k in word])
            alt_word = ''.join([alt[0] + ('（{}）'.format('・'.join(alt[1:])) if len(alt) > 1 else '') for alt in
                                [std_to_alt.get(k, k) for k in word]])
            if word != alt_word:
                word = word + '[{}]'.format(alt_word)

            if example.word_variation != '':
                word += '\n（{}）'.format(example.word_variation)

            writer.writerow([example.id,
                             sentence,
                             yomi,
                             example.get_definition_html()])


    @staticmethod
    def export_anki_kotowaza(writer):
        q_set = Example.objects.filter(ex_type=Example.TypeChoice.KOTOWAZA.name).exclude(kotowaza__yomi='')

        for example in q_set:
            word = example.word_native if example.word_native != "" else example.word
            yomi = example.yomi_native if example.yomi_native != "" else example.yomi
            sentence = example.sentence.replace(word, '<span class="font-color01">' + yomi + '</span>')

            writer.writerow([example.id,
                             sentence,
                             word,
                             example.kotowaza.get_definition_html()])


    # noinspection PyUnusedLocal
    @staticmethod
    def export_anki_kanji(writer):
        for kj in Kanji.objects.exclude(kanken__difficulty__gt=10):
            anki_read_table = render_to_string('kukan/AnkiReadTable.html', {'kanji': kj})
            writer.writerow([kj.kanji,
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


    # noinspection PyUnusedLocal
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
                '、'.join([x for x in test_end[yoji.yoji[2:4]] if x != yoji.yoji[0:2]]),
                yoji.anki_cloze[2],
                yoji.yoji[2:4],
                '、'.join([x for x in test_start[yoji.yoji[0:2]] if x != yoji.yoji[2:4]]),
            )
            writer.writerow([yoji.yoji,
                             cloze,
                             yoji.reading,
                             yoji.get_definition_html()[3:-4],
                             ])