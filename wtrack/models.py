from django.core.exceptions import ValidationError
from django.db import models

# Create your models here.
from django.db.models import ForeignKey
from django.utils.formats import date_format


class Scale(models.Model):
    maker = models.CharField('メーカー', max_length=50)
    model = models.CharField('機種', max_length=100)

    def __str__(self):
        return f'{self.maker} {self.model}'


class Settings(models.Model):
    default_scale = models.ForeignKey(Scale, on_delete=models.PROTECT,
                                      verbose_name='基本体重計',
                                      blank=True, null=True)

    def validate_single(self):
        if not self.pk:
            if Settings.objects.count():
                raise ValidationError('設定は一つしか登録出来ない')

    def clean(self):
        self.validate_single()

    def save(self, *args, **kwargs):
        self.validate_single()
        super().save(*args, **kwargs)

    def __str__(self):
        return '設定'


class Measurement(models.Model):
    scale = ForeignKey(Scale, on_delete=models.PROTECT, verbose_name='体重計',
                       blank=True, null=True)
    measure_date = models.DateTimeField('測定日')
    weight = models.FloatField('体重')
    fat_pct = models.FloatField('体脂肪率', null=True, blank=True, default=None)
    muscle_pct = models.FloatField('骨格筋率', null=True, blank=True,
                                   default=None)

    def __str__(self):
        formatted_date = date_format(self.measure_date,
                                     format="SHORT_DATETIME_FORMAT")
        return f'{formatted_date}: {self.weight} kg'
