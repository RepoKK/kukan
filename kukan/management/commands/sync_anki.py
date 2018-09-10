import sys, os
import pandas as pd
from collections import namedtuple

from django.core.management.base import BaseCommand
from django.conf import settings
from kukan.exporting import Exporter

sys.path.append(os.path.join(settings.TOP_DIR, r'anki', r'anki-2.1.4'))
from anki import Collection
from anki.sync import RemoteServer, Syncer
from anki.importing.csvfile import TextImporter

Deck = namedtuple('Deck', ['name', 'file_name'])


def create_user_deck_list(suffix):
    deck_with_suffix = ['書き取り']
    return [Deck(x, y + '.csv') if x not in deck_with_suffix else Deck(x, y + '_' + suffix +'.csv')
            for x, y in deck_list]


deck_list = [
    ('四字熟語', 'dj_anki_yoji'),
    ('書き取り', 'dj_anki_kaki'),
    ('漢字', 'dj_anki_kanji'),
    ('読み', 'dj_anki_yomi'),
    ('諺', 'dj_anki_kotowaza'),
]


profiles = {
    #'Fred': {'syncKey': r'5cewjKL7Ji0bxmEI', 'hostNum': '3', 'decks': create_user_deck_list('fred')},
    #'Ayumi': {'syncKey': r'AKkTW8E20gyPnhXB', 'hostNum': '3', 'decks': create_user_deck_list('ayu')},
    'Test2': {'syncKey': r'B41alyqIHCZPnWsO', 'hostNum': '2', 'decks': create_user_deck_list('fred')},
}


def import_file(col, file):
    did = col.decks.id("書き取り")
    col.decks.select(did)

    # anki defaults to the last note type used in the selected deck
    m = col.models.byName("Kakitori")
    deck = col.decks.get(did)
    deck['mid'] = m['id']
    col.decks.save(deck)
    # and puts cards in the last deck used by the note type
    m['did'] = did

    # import into the collection
    ti = TextImporter(col, file)
    ti.initMapping()
    ti.run()
    if ti.log:
        print(ti.log)


def delete_missing_notes(col, file_name):
    lst_db_notes = pd.DataFrame(list(col.db.execute("select id, flds from notes")))
    lst_db_notes.iloc[:,1] = lst_db_notes.iloc[:,1].str.split('\x1f').str.get(0)
    lst_db_notes.columns = ['db_key', 'anki_key']
    lst_db_notes.set_index('anki_key', inplace=True)
    #print(lst_db_notes)

    lst_new_keys = pd.read_csv(file_name, sep='\t', header=None, usecols=[0], dtype=str)
    lst_new_keys['csv'] = 'csv'
    lst_new_keys.set_index(0, inplace=True)
    #print(lst_new_keys)

    lst_db_notes['csv'] = lst_new_keys['csv']
    ids_to_del = lst_db_notes[lst_db_notes['csv']!='csv']['db_key'].tolist()
    #print(len(ids_to_del))
    len_del = len(ids_to_del)
    if len_del == 0:
        print('No card to delete')
    elif len_del > 5:
        print('Too many cards to delete ({})'.format(len_del))
    else:
        print('Delete {} card(s)'.format(len_del))
        col.remNotes(ids_to_del)


def sync_server(profile, col):
    server = RemoteServer(profiles[profile]['syncKey'], profiles[profile]['hostNum'])
    client = Syncer(col, server)
    res = client.sync()
    print('Sync result: ', res)


def sync_profile(profile):
    col = Collection(os.path.join(settings.TOP_DIR, r'.local/share/Anki2', profile, r'collection.anki2'))

    try:
        # Sync from the server
        sync_server(profile, col)

        # Apply the changes
        for deck in profiles[profile]['decks']:
            file_name = os.path.join(settings.TOP_DIR, r'anki/import', deck.file_name)
            if os.path.exists(file_name):
                import_file(col, file_name)
                delete_missing_notes(col, file_name)

        # Sync the change back
        sync_server(profile, col)

    finally:
        col.close()


class Command(BaseCommand):
    help = 'Sync Anki'

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        Exporter('all').export()
        for prof in profiles.keys():
            sync_profile(prof)
