import os
import inspect
import importlib
from io import StringIO
from abc import ABC, abstractmethod
from django.core.management import call_command
from django.conf import settings
from kukan.models import Kanji
from kukan import models

# To create the fixtures, run some of the following from the console
#
# from kukan.test_helpers import FixtureKukan, FixtureKanji
# FixtureKukan('baseline').dump()
# FixtureKanji().dump_all()
# FixtureKanji().dump('覧')


class FixtureManager:

    def __init__(self, app, indent=4, subdir=None):
        self.app = app
        self.indent = indent
        if subdir is None:
            self.output_dir = os.path.join(settings.BASE_DIR, self.app, 'fixtures')
        else:
            self.output_dir = os.path.join(settings.BASE_DIR, self.app, 'fixtures', subdir)

    def get_fixture(self, model, primary_keys):
        with StringIO() as out:
            if self.app is not None:
                model = '.'.join([self.app, model])
            call_command('dumpdata', model, indent=self.indent, stdout=out, primary_keys=primary_keys)
            res = out.getvalue()
        return res


class FixtureModelLevel(FixtureManager, ABC):
    @property
    @abstractmethod
    def app(self):
        pass

    @property
    @abstractmethod
    def model(self):
        pass

    def __init__(self):
        super().__init__(app=self.app, subdir=self.model.__name__)

    @abstractmethod
    def _dump_one(self, primary_key):
        pass

    def dump(self, primary_key, to_file=True):
        fixture = self._dump_one(primary_key)
        fixture_text = '[' + ','.join([x[1:-2] for x in fixture]) + ']'
        if to_file:
            with open(os.path.join(self.output_dir, primary_key + '.json'), 'w') as f:
                f.write(fixture_text)
        else:
            return fixture_text

    def dump_all(self):
        """
        Function to dump all elements of the model as separate files
        """
        for item in self.model.objects.all():
            self.dump(item.pk, to_file=True)
            print(self.dump(item.pk))
            break


class FixtureAppLevel(FixtureManager):
    def __init__(self, app, file_name, include_models=None, exclude_models=None):
        self.file_name = file_name if file_name[-5:] == '.json' else file_name + '.json'
        self.include_models = include_models or []
        self.exclude_models = exclude_models or []
        super().__init__(app)

    def get_list_models(self):
        module = importlib.import_module(self.app + '.models')
        return [self.app + '.' + x[0] for x in inspect.getmembers(module, inspect.isclass) if
                x[1].__class__.__name__ == 'ModelBase'
                and x[0] not in self.exclude_models
                and (x[0] in self.include_models if len(self.include_models) else True)]

    def dump(self):
        file_path = os.path.join(self.output_dir, self.file_name)
        call_command('dumpdata', *self.get_list_models(), indent=self.indent, output=file_path)


class FixtureKukan(FixtureAppLevel):
    def __init__(self, file_name):
        include_models = ['Classification', 'JisClass', 'Kanken', 'YomiJoyo', 'YomiType']
        super().__init__('kukan', file_name, include_models=include_models)


class FixtureKanji(FixtureModelLevel):
    app = 'kukan'
    model = Kanji

    def _dump_one(self, primary_key):
        fixture = []
        for model in ['Kanji', 'Bushu', 'KoukiBushu', 'Reading', 'KanjiDetails']:
            objects = getattr(models, model).objects.filter(kanji=primary_key)
            if len(objects):
                fixture.append(self.get_fixture(model, primary_keys=','.join([str(x.pk) for x in objects])))
        return fixture
