from django.forms import Form, ModelForm, Textarea, CharField, TextInput, ChoiceField, Select, ValidationError
from .models import Kanji, Bushu, YomiType, YomiJoyo, Reading, Example, ExMap
from django.utils.translation import gettext_lazy as _
import kukan.jautils as jau

class SearchForm(Form):
    search = CharField(required=False,
                       widget=TextInput(attrs={'class': 'input is-medium', 'placeholder':'漢字・四字熟語・単語'}))



class Katakana(CharField):

    def to_python(self, value):
        """Normalize to Katakana."""
        if value:
            value = value.translate(jau.hir2kat).strip()
        return value

    def validate(self, value):
        """Check if value consists only of Katakana."""
        super().validate(value)
        for char in value:
            if char not in jau.katakana_chart:
                raise ValidationError(
                            _('入力は片仮名以外: %(value)s'),
                            code='invalid',
                            params={'value': value},
                        )

class ReadingSelect(CharField):

    def validate(self, value):
        """Check all the selections are > -1 (something is actually selected)"""
        super().validate(value)
        for elem in value.split(','):
            if elem == '-1':
                raise ValidationError(
                            _('未設定の読みがあります'),
                            code='invalid',
                        )


class ExampleForm(ModelForm):
    reading_selected = CharField(label='reading_selected', max_length=100)

    class Meta:
        model = Example
        fields = ['word', 'word_native', 'yomi', 'yomi_native', 'sentence', 'definition']
        widgets = {
            'sentence': Textarea(attrs={'cols': 80, 'rows': 1}),
            'definition': Textarea(attrs={'cols': 80, 'rows': 5}),
        }
        field_classes = {
            'yomi': Katakana,
            'yomi_native': Katakana,
        }

    def __init__(self, *args, **kwargs):
        super(ExampleForm, self).__init__(*args, **kwargs)
        ex = kwargs.pop('instance')
        if not ex is None:
            self.fields['word'].disabled=ex.is_joyo

        # for kj_map in ex.exmap_set.all():
        #     if not kj_map.reading is None:
        #         lst_rd = [['None', '--未定--']]
        #         for rd in Reading.objects.filter(kanji=kj_map.kanji):
        #             lst_rd.append([rd.reading, rd.reading])
        #         self.fields[kj_map.kanji.kanji] = ChoiceField(choices=lst_rd,
        #                                                initial=kj_map.reading.reading)

    def clean(self):
        cleaned_data=super(ExampleForm, self).clean()
        sentence = cleaned_data.get('sentence')
        word = cleaned_data.get('word_native')
        if word == '':
            word = cleaned_data.get('word')

        reading_nb = 0
        for kj in word:
            if Kanji.objects.filter(kanji=kj).count() > 0:
                reading_nb += 1
        reading_selected = self.cleaned_data['reading_selected'].split(',')
        if len(reading_selected) != reading_nb:
            self.add_error('sentence',
                           ValidationError(_('漢字と設定された読みの数が合わない'),
                                           code='invalid',
                                           ))

        if sentence != '':
            if word not in sentence:
                self.add_error('sentence',
                               ValidationError(_('例文は単語「%(word)s」を含んでない。'),
                                               code='invalid',
                                               params={'word': word}))
            no_word_sentence=sentence.replace(word, '')
            for kj in word:
                if Kanji.objects.filter(kanji=kj).count() > 0:
                    if kj in no_word_sentence:
                        self.add_error('sentence',
                                   ValidationError(
                                       _('漢字「%(kj)s」は単語「%(word)s」以外では使えない。'),
                                       code = 'invalid',
                                       params = {'kj': kj, 'word':word}))
            if sentence.count(word) > 1:
                self.add_error('sentence',
                               ValidationError(
                                   _('単語「%(word)s」は一回しか使えない。'),
                                   code='invalid',
                                   params={'word': word}))
        return self.cleaned_data



    def save(self, commit=True):
        if self.instance.is_joyo is None:
            self.instance.is_joyo = False
        example = super().save(commit=False)
        if commit:
            example.save()
            reading_selected = self.cleaned_data['reading_selected'].split(',')
            map_list = []
            idx = 0
            for kj in example.get_word_native():
                try:
                    kanji = Kanji.objects.get(kanji=kj)
                    # check if the reading is a Joyo one - in which case it can't be changed
                    try:
                        map = example.exmap_set.get(kanji = kanji,
                                                             example = example,
                                                             map_order = idx,
                                                             in_joyo_list = True)
                    except ExMap.DoesNotExist:
                        if reading_selected[idx] == '0':
                            map, create = example.exmap_set.get_or_create(kanji=kanji,
                                                                          example=example,
                                                                          map_order=idx,
                                                                          is_ateji=True,
                                                                          in_joyo_list=False)
                        else:
                            reading = Reading.objects.get(kanji=kj, id=reading_selected[idx])
                            map, create = example.exmap_set.get_or_create(kanji = kanji,
                                                                      reading = reading,
                                                                      example = example,
                                                                      map_order = idx,
                                                                      is_ateji=False,
                                                                      in_joyo_list = False)
                    map_list.append(map.id)
                    idx += 1
                except Kanji.DoesNotExist:
                    # Not a Kanji (kana, or kanji not in the list)
                    pass
            # Delete the maps not relevant anymore
            extra_maps = ExMap.objects.filter(example = example).exclude(id__in=map_list)
            extra_maps.delete()

        return example


class ExportForm(Form):
    type = ChoiceField(choices=[('anki_kanji', 'Anki deck: 漢字'),
                                ('anki_kaki_ayu','Anki deck: 書き取り（あゆみ）'),
                                ('anki_kaki_fred', 'Anki deck: 書き取り（フレッド）'),
                                ('anki_yoji', 'Anki deck: 四字熟語'),
                                ],
                       widget=Select(attrs={'class': 'select'}))