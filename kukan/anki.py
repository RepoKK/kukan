import sys, os, re
import pandas as pd
from collections import namedtuple

from django.conf import settings

sys.path.append(settings.ANKI_SRC)
from anki import Collection
from anki.sync import RemoteServer, Syncer, FullSyncer
from anki.importing.csvfile import TextImporter
from anki.utils import ids2str

Deck = namedtuple('Deck', ['name', 'model', 'file_name'])


class AnkiProfile:

    deck_list = [Deck(x, m, y + '.csv') for x, m, y in [
        ('四字熟語', 'Cloze Yoji', 'dj_anki_yoji'),
        ('書き取り', 'Kakitori', 'dj_anki_kaki'),
        # ('漢字', 'Japanese Kanji', 'dj_anki_kanji'),
        ('読み', 'Yomi', 'dj_anki_yomi'),
        # ('諺', 'Kotowaza', 'dj_anki_kotowaza'),
    ]]

    profiles = {
        'Fred': {'syncKey': r'5cewjKL7Ji0bxmEI', 'hostNum': '3', 'decks': deck_list},
        # 'Ayumi': {'syncKey': r'AKkTW8E20gyPnhXB', 'hostNum': '3', 'decks': deck_list},
        'Test2': {'syncKey': r'B41alyqIHCZPnWsO', 'hostNum': '2', 'decks': deck_list},
    }

    def __init__(self, profile):
        self.name = profile
        self.profile = self.profiles[profile]
        self.col = Collection(os.path.join(settings.TOP_DIR,
                                           r'.local/share/Anki2',
                                           self.name,
                                           r'collection.anki2'))

    @classmethod
    def profile_list(cls):
        return cls.profiles.keys()

    @property
    def kind_list(self):
        return [d.file_name[3:-4] for d in self.profile['decks']]

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
            print(ti.log[0])
            m = re.match(r'(\d+) notes? added, (\d+) notes? updated, (\d+) notes? unchanged.', ti.log[0])
            if m:
                res = (m[1], m[2], m[3])
        return res

    def delete_missing_notes(self, deck, file_name):
        lst_db_notes = pd.DataFrame(list(self.col.db.execute(
            "select id, flds from notes where id in " + ids2str(self.col.findNotes("deck:" + deck.name)))))
        lst_db_notes.iloc[:, 1] = lst_db_notes.iloc[:, 1].str.split('\x1f').str.get(0)
        lst_db_notes.columns = ['db_key', 'anki_key']
        lst_db_notes = lst_db_notes.set_index('anki_key').sort_index()
        # print(lst_db_notes)

        lst_new_keys = pd.read_csv(file_name, sep='\t', header=None, usecols=[0], dtype=str)
        lst_new_keys['csv'] = 'csv'
        lst_new_keys = lst_new_keys.set_index(0).sort_index()
        # print(lst_new_keys)

        lst_db_notes['csv'] = lst_new_keys['csv']
        ids_to_del = lst_db_notes[lst_db_notes['csv'] != 'csv']['db_key'].tolist()
        # print(len(ids_to_del))
        len_del = len(ids_to_del)
        if len_del == 0:
            print('No card to delete')
        elif len_del > 5:
            len_del = 'Too many cards to delete ({})'.format(len_del)
            print('Too many cards to delete ({})'.format(len_del))
        else:
            print('Delete {} card(s)'.format(len_del))
            self.col.remNotes(ids_to_del)
        return len_del

    def sync_server(self):
        server = RemoteServer(self.profile['syncKey'], self.profile['hostNum'])
        client = Syncer(self.col, server)
        res = client.sync()
        print('Sync result: ', res)
        if res in ['success', 'noChanges']:
            pass
        elif res == 'fullSync':
            print('FULL SYNC')
            client = FullSyncer(self.col, self.profile['syncKey'], server.client, self.profile['hostNum'])
            client.download()

    def sync(self):
        print('*** Sync profile {} ***'.format(self.name))

        res_df = pd.DataFrame('-',
                              [p.name for p in self.profile['decks']],
                              ['added', 'updated', 'deleted', 'unchanged'])
        try:
            # Sync from the server
            self.sync_server()

            # Apply the changes
            for deck in self.profile['decks']:
                file_name = os.path.join(settings.ANKI_IMPORT_DIR, deck.file_name)
                if os.path.exists(file_name) and deck.name in self.col.decks.allNames():
                    print('Imp', deck.name)
                    res_df.loc[deck.name, ['added', 'updated', 'unchanged']] = self.import_file(deck, file_name)
                    res_df.loc[deck.name, 'deleted'] = self.delete_missing_notes(deck, file_name)
            print(res_df.to_html())

            # Sync the change back
            self.sync_server()

        finally:
            self.col.close()

        return res_df
