import logging
import os
import re
import weakref
from collections import namedtuple

import pandas as pd
from anki.collection import Collection
from anki.importing.csvfile import TextImporter
from anki.sync_pb2 import SyncStatusResponse
from anki.utils import ids2str
from django.conf import settings

Deck = namedtuple('Deck', ['name', 'model', 'file_name'])
logger = logging.getLogger(__name__)


class AnkiProfile:
    deck_list = [Deck(x, m, y + '.csv') for x, m, y in [
        ('四字熟語', 'Cloze Yoji', 'dj_anki_yoji'),
        ('書き取り', 'Kakitori', 'dj_anki_kaki'),
        # ('漢字', 'Japanese Kanji', 'dj_anki_kanji'),
        ('読み', 'Yomi', 'dj_anki_yomi'),
        ('諺', 'Kotowaza', 'dj_anki_kotowaza'),
    ]]

    profiles = {
        'Ayumi': {'syncKey': r'AKkTW8E20gyPnhXB',
                  'hostNum': '3', 'decks': deck_list},
        'Fred': {'syncKey': r'5cewjKL7Ji0bxmEI',
                 'hostNum': '3', 'decks': deck_list},
        'Test2': {'syncKey': r'B41alyqIHCZPnWsO',
                  'hostNum': '2', 'decks': deck_list},
    }

    # TODO: puts in settings_prod
    settings.ANKI_ACCOUNTS = {
        'Ayumi': {'user': 'xx', 'password': 'yy', 'decks': deck_list},
        'Fred': {'user': 'xx', 'password': 'yy', 'decks': deck_list},
        'Test2': {'user': 'xx', 'password': 'yy', 'decks': deck_list}
    }
    settings.ANKI_DB_DIR = ''

    def __init__(self, profile, max_delete_count=0):
        self.name = profile
        self.profile = self.profiles[profile]
        self.max_delete_count = max_delete_count
        self.col = None
        self._finalizer = weakref.finalize(self, self.close_collection)

    def open_collection(self):
        self.col = Collection(os.path.join(settings.TOP_DIR,
                                           r'.local/share/Anki2',
                                           self.name,
                                           r'collection.anki2'))

    def close_collection(self):
        if self.col:
            self.col.close()

    @classmethod
    def profile_list(cls):
        return cls.profiles.keys()

    @property
    def kind_list(self):
        return [d.file_name[3:-4] for d in self.profile['decks']]

    # Below functions require opening the Anki DB
    def import_file(self, deck, file_name):
        did = self.col.decks.id(deck.name)
        self.col.decks.select(did)

        # anki defaults to the last note type used in the selected deck
        m = self.col.models.byName(deck.model)
        deck = self.col.decks.get(did)
        deck['mid'] = m['id']
        self.col.decks.save(deck)
        # and puts cards in the last deck used by the note type
        m['did'] = did

        # import into the collection
        ti = TextImporter(self.col, file_name)
        ti.allowHTML = True
        ti.initMapping()
        ti.run()
        res = ('N/A', 'N/A', 'N/A')
        if ti.log:
            m = re.match(r'(\d+) notes? added, (\d+)'
                         r' notes? updated, (\d+) notes? unchanged.', ti.log[0])
            if m:
                res = (m[1], m[2], m[3])
        return res

    def delete_missing_notes(self, deck, file_name):
        lst_db_notes = pd.DataFrame(list(self.col.db.execute(
            "select id, flds from notes where id in "
            + ids2str(self.col.findNotes("deck:" + deck.name)))))
        lst_db_notes.iloc[:, 1] = lst_db_notes.iloc[:, 1].str.split(
            '\x1f').str.get(0)
        lst_db_notes.columns = ['db_key', 'anki_key']
        lst_db_notes = lst_db_notes.set_index('anki_key').sort_index()

        lst_new_keys = pd.read_csv(
            file_name, sep='\t', header=None, usecols=[0], dtype=str)
        lst_new_keys['csv'] = 'csv'
        lst_new_keys = lst_new_keys.set_index(0).sort_index()

        lst_db_notes['csv'] = lst_new_keys['csv']
        ids_to_del = lst_db_notes[
            lst_db_notes['csv'] != 'csv']['db_key'].tolist()
        len_del = len(ids_to_del)
        if len_del == 0:
            pass
        elif len_del > self.max_delete_count:
            print('Too many cards to delete ({})'.format(len_del))
            logger.error(f'{self.profile}: Too many cards to delete '
                         f'from deck {deck.name} '
                         f'({len_del}, max: {self.max_delete_count})')
        else:
            print('Delete {} card(s)'.format(len_del))
            logger.info(f'{self.profile}: Delete {len_del} cards '
                        f'from deck {deck.name}')
            self.col.remNotes(ids_to_del)
        return len_del

    def sync_server(self):
        auth = self.col.sync_login(self.profile['user'],
                                   self.profile['password'])

        if sync_status := self.col.sync_status(auth).required == \
                SyncStatusResponse.NORMAL_SYNC:
            logger.info('Sync from server: Need normal sync')
            logger.info(self.col.sync_collection(auth, True))
        elif sync_status == SyncStatusResponse.NO_CHANGES:
            logger.info('Sync from server: No change')
        elif sync_status == SyncStatusResponse.FULL_SYNC:
            logger.info('Sync from server: Need Full sync')
            Exception('Need Full sync')
        else:
            raise Exception('Return value not expected')

    def sync(self):

        self.open_collection()
        res_df = pd.DataFrame('-',
                              [p.name for p in self.profile['decks']],
                              ['added', 'updated', 'deleted', 'unchanged'])

        # Sync from the server
        self.sync_server()

        # Apply the changes
        for deck in self.profile['decks']:
            file_name = os.path.join(settings.ANKI_IMPORT_DIR, deck.file_name)
            if os.path.exists(file_name) and \
                    deck.name in self.col.decks.allNames():
                res_df.loc[deck.name, ['added', 'updated', 'unchanged']] = \
                    self.import_file(deck, file_name)
                res_df.loc[deck.name, 'deleted'] = self.delete_missing_notes(
                    deck, file_name)

        # Sync the change back
        self.sync_server()

        return res_df
