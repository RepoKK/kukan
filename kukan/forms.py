from django.forms import Form, ModelForm, Textarea, CharField, TextInput, ChoiceField, Select
from .models import Kanji, Bushu, YomiType, YomiJoyo, Reading, Example, ExMap
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class SearchForm(Form):
    search = CharField(widget=TextInput(attrs={'class': 'input is-medium', 'placeholder':'漢字・四字熟語・単語'}))

    def clean(self):
        cleaned_data=super(SearchForm, self).clean()
        raise ValidationError('Draft entries may not have a publication date.')



class ExampleForm(ModelForm):
    class Meta:
        model = Example
        fields = ['word', 'yomi', 'sentence', 'definition']
        widgets = {
            'sentence': Textarea(attrs={'cols': 80, 'rows': 1}),
            'definition': Textarea(attrs={'cols': 80, 'rows': 5}),
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
        raise ValidationError('Draft entries may not have a publication date.')



    def save(self, commit=True):
        if self.instance.is_joyo is None:
            self.instance.is_joyo = False
        example = super().save(commit=False)
        if commit:
            example.save()
            idx = 0
            for kj in example.word:
                if 'yomi_' + str(idx) in self.data:
                    reading = Reading.objects.get(kanji=kj, reading=self.data['yomi_' + str(idx)])
                    map, create = example.exmap_set.get_or_create(kanji = Kanji.objects.get(kanji=kj),
                                                                  example = example,
                                                                  map_order = idx,
                                                                  in_joyo_list = False)
                    if create:
                        map.reading = reading
                        map.save()
                    else:
                        if map.reading is None \
                                    or map.reading.reading != self.data['yomi_' + str(idx)]:
                            map.reading = reading
                            map.save()
                idx += 1
            extra = example.exmap_set.filter(map_order__gte=idx)
            extra.delete()

        return example


class ExportForm(Form):
    type = ChoiceField(choices=[('anki_kanji', 'Anki deck: 漢字'), ('anki_kaki','Anki deck: 書き取り')],
                       widget=Select(attrs={'class': 'select'}))