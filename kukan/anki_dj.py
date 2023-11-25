import logging
import os
import weakref
from collections import namedtuple

import pandas as pd
from anki.collection import Collection
from anki.collection import ImportCsvRequest
from anki.sync_pb2 import SyncStatusResponse
from django.conf import settings

Deck = namedtuple('Deck', ['name', 'model', 'file_name'])
logger = logging.getLogger(__name__)


class AnkiProfile:
    def __init__(self, profile, max_delete_count=0):
        self.name = profile
        self.profile = settings.ANKI_ACCOUNTS[profile]
        self.profile['decks'] = [
            Deck(x, m, y + '.csv') for x, m, y in [
                ('四字熟語', 'Cloze Yoji', 'dj_anki_yoji'),
                ('書き取り', 'Kakitori', 'dj_anki_kaki'),
                # ('漢字', 'Japanese Kanji', 'dj_anki_kanji'),
                ('読み', 'Yomi', 'dj_anki_yomi'),
                ('諺', 'Kotowaza', 'dj_anki_kotowaza'),
            ]]
        self.max_delete_count = max_delete_count
        self.col = None
        self._finalizer = weakref.finalize(self, self.close_collection)

    def open_collection(self):
        self.col = Collection(os.path.join(settings.ANKI_DB_DIR,
                                           self.name,
                                           r'collection.anki2'))

    def close_collection(self):
        if self.col:
            self.col.close()

    @classmethod
    def profile_list(cls):
        return settings.ANKI_ACCOUNTS.keys()

    @property
    def kind_list(self):
        return [d.file_name[3:-4] for d in self.profile['decks']]

    @staticmethod
    def get_deck_import_file(deck):
        file_name = os.path.join(settings.ANKI_IMPORT_DIR, deck.file_name)
        assert os.path.exists(file_name)
        return file_name

    def import_file(self, deck):
        file_name = self.get_deck_import_file(deck)
        metadata = self.col.get_csv_metadata(path=file_name, delimiter=None)
        request = ImportCsvRequest(path=file_name, metadata=metadata)
        response = self.col.import_csv(request)

        return (len(response.log.new),
                len(response.log.first_field_match),
                len(response.log.duplicate))

    def delete_missing_notes(self, deck, df_anki_export_all):
        file_name = self.get_deck_import_file(deck)
        df_anki_export = df_anki_export_all[
            df_anki_export_all.iloc[:, 2] == deck.name]

        df_web_side = self.read_anki_csv(file_name)
        df_web_side[2] = df_web_side[2].astype(str)
        df_web_side.columns = [1, 2, 3]
        assert not df_web_side.duplicated().any()

        df_merge = pd.merge(df_anki_export.set_index([1, 2, 3]),
                            df_web_side.set_index([1, 2, 3]),
                            left_index=True, right_index=True, how='outer',
                            indicator=True)
        df_merge.columns = ['GUID', '_merge']
        assert df_merge[df_merge['_merge'] == 'right_only'].empty

        # DF of GUID, ID
        df_ids = pd.DataFrame(self.col.db.all("select guid, id from notes"),
                              columns=['GUID', 'ID'])

        list_to_delete = pd.merge(
            df_ids,
            df_merge[df_merge['_merge'] == 'left_only']
        )['ID'].to_list()

        if (len_del := len(list_to_delete)) == 0:
            pass
        if len_del > self.max_delete_count:
            print(f'Too many cards to delete ({len_del})')
            logger.error(f'{self.name}: Too many cards to delete '
                         f'({len_del}, max: {self.max_delete_count})')
        elif len_del > 0:
            print(f'Delete {len_del} card(s)')
            logger.info(f'{self.name}: Delete {len_del} cards')
            self.col.remove_notes(list_to_delete)

        return len_del

    @staticmethod
    def read_anki_csv(file_name, with_guid=False):
        comments = [
               '#separator:tab',
               '#html:true'
                   ] + ([f'#guid column:1'] if with_guid else []) + [
                f'#notetype column:{with_guid+1}',
                f'#deck column:{with_guid+2}'
        ]
        with open(file_name, encoding='utf-8') as input_file:
            head = [next(input_file).strip() for _ in range(len(comments))]
            assert head == comments, 'Expected comments not found'
        return pd.read_csv(file_name, usecols=list(range(3 + with_guid)),
                           skiprows=len(comments), header=None,
                           delimiter='\t')

    def apply_to_anki(self):
        decks = [d.name for d in self.profile['decks']]
        assert not len(set(decks) -
                       set(e.name for e in self.col.decks.all_names_and_ids()))

        res_df = pd.DataFrame('-', decks,
                              ['added', 'updated', 'deleted', 'unchanged'])

        for deck in self.profile['decks']:
            file_name = os.path.join(settings.ANKI_IMPORT_DIR, deck.file_name)
            assert os.path.exists(file_name)

            # Import the additions/changes
            res_df.loc[deck.name, ['added', 'updated', 'unchanged']] = \
                self.import_file(deck)

        # Export the current Anki note in file with below format
        # CC[7j9a$Y`<tab>Japanese Kanji<tab>漢字<tab>一<tab>one...
        anki_export_file = os.path.join(settings.ANKI_IMPORT_DIR,
                                        'anki_export.csv')
        self.col.export_note_csv(
            out_path=anki_export_file, limit=100000,
            with_html=True, with_notetype=True, with_deck=True,
            with_tags=False, with_guid=True)
        df_anki_export_all = self.read_anki_csv(anki_export_file, True)
        assert not df_anki_export_all.duplicated().any()

        for deck in self.profile['decks']:
            # Remove notes deleted from the web
            res_df.loc[deck.name, 'deleted'] = self.delete_missing_notes(
                deck, df_anki_export_all)

        return res_df

    def sync_server(self, *, initial_sync):
        logger.info(f'{"Initial" if initial_sync else "Final"} sync')
        auth = self.col.sync_login(self.profile['user'],
                                   self.profile['password'], None)

        full_sync = False

        if (sync_status := self.col.sync_status(auth).required) == \
                SyncStatusResponse.NORMAL_SYNC:
            logger.info('Sync with server: Need normal sync')
            sync_res = self.col.sync_collection(auth, False)
            logger.info(sync_res)
            full_sync = (sync_res.required == SyncStatusResponse.FULL_SYNC)
        elif sync_status == SyncStatusResponse.NO_CHANGES:
            logger.info('Sync with server: No change')
        elif sync_status == SyncStatusResponse.FULL_SYNC:
            full_sync = True
        else:
            raise Exception('Return value not expected')

        if full_sync:
            logger.info('Sync from server: Need Full sync')
            if initial_sync:
                logger.info(self.col.full_upload_or_download(
                    auth=auth, server_usn=None, upload=False))
            else:
                raise Exception('Full sync not allowed on final sync')

    def sync(self):
        self.open_collection()
        self.sync_server(initial_sync=True)
        res_df = self.apply_to_anki()
        self.sync_server(initial_sync=False)
        logger.info(res_df.to_string())

        return res_df
