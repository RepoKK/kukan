from django.db import transaction
from django.forms import Form, ModelForm, CharField, TextInput, ChoiceField, Select, ValidationError
from django.utils.translation import gettext_lazy as _

import kukan.jautils as jau
from kukan.anki_dj import AnkiProfile
from kukan.jautils import JpnText
from .models import Kanji, Example, Kotowaza


class SearchForm(Form):
    search = CharField(required=False,
                       widget=TextInput(attrs={'class': 'input is-medium',
                                               'placeholder': '漢字・四字熟語・単語'}))


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
    kana_chart = (jau.hiragana_chart + jau.punctuation_chart
                  + jau.fullwidth_digit_chart + jau.halfwidth_digit_chart
                  + jau.alphabet_lower_chart + jau.alphabet_upper_chart)
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


class BForm(ModelForm):

    class Meta:

        # Override of standard templates with custom ones using Buefy
        override = {TextInput: 'widgets/binput.html',
                    Select: 'widgets/bselect.html'}

        @staticmethod
        def override_widget_template(f, **kwargs):
            formfield = f.formfield(**kwargs)
            if type(formfield.widget) in BForm.Meta.override.keys():
                formfield.widget.template_name = BForm.Meta.override[type(formfield.widget)]
            return formfield

        formfield_callback = override_widget_template

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, fld in self.fields.items():
            optional = '（任意）' if fld.required is False else ''
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
            'yomi': TextInput(attrs={'placeholder': '読み方（カタカナ）'}),
            'definition': TextInput(attrs={'type': 'textarea', 'rows': '8'}),
        }
        field_classes = {
            'yomi': HiraganaPlus,
        }

    def clean(self):
        cleaned_data = super().clean()
        kotowaza = cleaned_data.get('kotowaza')
        yomi = cleaned_data.get('yomi')
        furigana = cleaned_data.get('furigana')
        for error in JpnText.from_furigana_format(furigana, kotowaza, yomi).get_furigana_errors():
            self.add_error('furigana',
                           ValidationError(_('%(error)s'),
                                           code='invalid',
                                           params={'error': error}))


class ExampleForm(BForm):
    reading_selected = CharField(label='reading_selected', max_length=100)

    class Meta:
        model = Example
        fields = ['word', 'word_native', 'word_variation', 'yomi', 'yomi_native', 'sentence', 'definition',
                  'ex_kind', 'kotowaza']
        widgets = {
            'word': TextInput(attrs={'placeholder': '単語（漢字・仮名）', '@blur': 'onChangeWord'}),
            'word_native': TextInput(attrs={'placeholder': '例文中の語形'}),
            'yomi': TextInput(attrs={'placeholder': '読み方（カタカナ）'}),
            'yomi_native': TextInput(attrs={'placeholder': '例文中の読み方（カタカナ）'}),
            'sentence': TextInput(attrs={'placeholder': '単語を含む例文を入力ください。'}),
            'definition': TextInput(attrs={'type': 'textarea', 'rows': '12',
                                           'placeholder': '単語の意味・説明の文章を入力ください。'}),
            'kotowaza': Select(attrs={'expanded': 'true'}),
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
        # Bypass the check that a kanji part of the word is only present once in the sentence (issue #50)
        self.ignore_duplicate_kanji = False
        if ex and ex.is_joyo:
            self.fields['word'].widget.attrs['readonly'] = True

    def clean_sentence(self):
        sentence = self.cleaned_data['sentence']
        if sentence and sentence[0] == 'x':
            self.ignore_duplicate_kanji = True
            sentence = sentence[1:]
        return sentence

    def clean(self):
        cleaned_data = super(ExampleForm, self).clean()
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
            no_word_sentence = sentence.replace(word, '')
            if not self.ignore_duplicate_kanji:
                for kj in word:
                    if Kanji.objects.filter(kanji=kj).exists() and kj in no_word_sentence:
                        self.add_error('sentence',
                                       ValidationError(
                                           _('漢字「%(kj)s」は単語「%(word)s」以外では使えない。(\'x\'で無視可)'),
                                           code='invalid',
                                           params={'kj': kj, 'word': word}))
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
            example.create_exmap(self.cleaned_data['reading_selected'].split(','))
        return example


class ExportForm(Form):
    profile = ChoiceField(choices=[(p, p) for p in AnkiProfile.profile_list()],
                          widget=Select(attrs={'class': 'select'}),
                          label='プロフィール')

    type = ChoiceField(choices=[('anki_kanji', '漢字'),
                                ('anki_kaki', '書き取り'),
                                ('anki_yoji', '四字熟語'),
                                ('anki_yomi', '読み'),
                                ('anki_kotowaza', '諺'),
                                ],
                       widget=Select(attrs={'class': 'select'}),
                       label='ファイル')
