from django.forms import Form, ModelForm, Textarea, CharField, TextInput, ChoiceField, Select, ValidationError
from .models import Kanji, Bushu, YomiType, YomiJoyo, Reading, Example, ExMap, Kotowaza
from django.utils.translation import gettext_lazy as _
import kukan.jautils as jau
from django.db import transaction
from django.forms import widgets
from django.db import models
from kukan.anki import AnkiProfile
from kukan.jautils import JpText


class SearchForm(Form):
    search = CharField(required=False,
                       widget=TextInput(attrs={'class': 'input is-medium', 'placeholder':'漢字・四字熟語・単語'}))


class Kana(CharField):
    translate_function = None
    kana_chart = None
    kana_type = None

    def to_python(self, value):
        """Normalize to Katakana."""
        if value:
            value = value.translate(self.translate_function).strip()
        return value

    def validate(self, value):
        """Check if value consists only of Kana."""
        super().validate(value)
        for char in value:
            if char not in self.kana_chart:
                raise ValidationError(
                            _('入力は%(type)s以外: %(value)s'),
                            code='invalid',
                            params={'type': self.kana_type, 'value': value},
                        )


class Katakana(Kana):
    translate_function = jau.hir2kat
    kana_chart = jau.katakana_chart
    kana_type = '片仮名'


class Hiragana(Kana):
    translate_function = jau.kat2hir
    kana_chart = jau.hiragana_chart
    kana_type = '平仮名'


class HiraganaPlus(Kana):
    translate_function = jau.kat2hir
    kana_chart = jau.hiragana_chart + jau.punctuation_chart \
                 + jau.fullwidth_digit_chart + jau.halfwidth_digit_chart \
                 + jau.alphabet_lower_chart + jau.alphabet_upper_chart
    kana_type = '平仮名'


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


class BTextInput(widgets.TextInput):
    template_name = 'widgets/input.html'


class BSelect(widgets.Select):
    template_name = 'widgets/bselect.html'
    test = 1

class BForm(ModelForm):

    class Meta:
        @staticmethod
        def set_widget(f, **kwargs):
            formfield = f.formfield()
            replacement_widgets = {widgets.TextInput: BTextInput,
                                   widgets.Select: BSelect}
            widget_type = type(formfield.widget)

            if 'widget' in kwargs:
                formfield.widget = kwargs['widget']
            elif widget_type in replacement_widgets.keys():
                if widget_type == widgets.Select:
                    formfield.widget = replacement_widgets[widget_type](**kwargs, choices=formfield.choices)
                else:
                    formfield.widget = replacement_widgets[widget_type](kwargs)

            return formfield

        formfield_callback = set_widget

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, fld in self.fields.items():
            optional = '（任意）' if fld.required == False else ''
            fld.widget.attrs['placeholder'] = optional + fld.widget.attrs.get('placeholder', fld.label)
            fld.widget.attrs['v-model'] = name

        for group in getattr(self.Meta, 'label_length_groups', []):
            label_length = max([len(self.fields[x].label) if x in self.fields else 0 for x in group])
            for x in group:
                self.fields[x].label = self.fields[x].label.ljust(label_length, '　')


class KotowazaForm(BForm):

    class Meta:
        model = Kotowaza
        fields = ['kotowaza', 'yomi', 'furigana', 'definition']
        widgets = {
            'yomi': BTextInput(attrs={'placeholder': '読み方（カタカナ）'}),
            'definition': BTextInput(attrs={'type': 'textarea', 'rows': '8'}),
        }
        field_classes = {
            'yomi': HiraganaPlus,
        }

    def clean(self):
        cleaned_data=super().clean()
        kotowaza = cleaned_data.get('kotowaza')
        yomi = cleaned_data.get('yomi')
        furigana = cleaned_data.get('furigana')
        for error in JpText(kotowaza, yomi, furigana).get_furigana_errors():
            self.add_error('furigana',
                           ValidationError(_('%(error)s'),
                                           code='invalid',
                                           params={'error': error}))


class ExampleForm(BForm):
    reading_selected = CharField(label='reading_selected', max_length=100)

    class Meta:
        model = Example
        fields = ['word', 'word_native', 'word_variation', 'yomi', 'yomi_native', 'sentence', 'definition',
                  'ex_kind']
        widgets = {
            'word': BTextInput(attrs={'placeholder': '単語（漢字・仮名）', '@blur': 'onChangeWord'}),
            'word_native': BTextInput(attrs={'placeholder': '例文中の語形'}),
            'yomi': BTextInput(attrs={'placeholder': '読み方（カタカナ）'}),
            'yomi_native': BTextInput(attrs={'placeholder': '例文中の読み方（カタカナ）'}),
            'sentence': BTextInput(attrs={'placeholder': '単語を含む例文を入力ください。'}),
            'definition': BTextInput(attrs={'type': 'textarea', 'rows': '12',
                                            'placeholder': '単語の意味・説明の文章を入力ください。'}),
        }
        field_classes = {
            'yomi': Katakana,
            'yomi_native': Katakana,
        }
        label_length_groups = [['word', 'yomi'],
                               ['word_native', 'yomi_native', 'word_variation']]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ex = kwargs['instance']
        if ex and ex.is_joyo:
            self.fields['word'].widget.attrs['readonly'] = True
        self['reading_selected'].initial = []

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

    @transaction.atomic
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
    profile = ChoiceField(choices=[(p, p) for p in AnkiProfile.profile_list()],
                          widget=Select(attrs={'class': 'select'}),
                          label='プロフィール')

    type = ChoiceField(choices=[('anki_kanji', '漢字'),
                                ('anki_kaki','書き取り'),
                                ('anki_yoji', '四字熟語'),
                                ('anki_yomi', '読み'),
                                ('anki_kotowaza', '諺'),
                                ],
                       widget=Select(attrs={'class': 'select'}),
                       label='ファイル')
