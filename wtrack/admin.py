from django.contrib import admin

# Register your models here.
from wtrack.models import Scale, Settings, Measurement

admin.site.register(Scale)
admin.site.register(Settings)
admin.site.register(Measurement)