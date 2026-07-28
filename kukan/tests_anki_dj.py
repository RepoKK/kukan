"""Tests for the Anki sync pipeline.

`kukan/anki_dj.py` drives the nightly `sync_anki` job: it pulls the user's
collection from AnkiWeb, imports CSVs exported from this site, deletes notes
that no longer exist on the web side, and pushes the result back. It sat at 32%
coverage while being the only code in the project that can destroy data the
site does not own — the user's own Anki collection, including review history.

The safety valve is `max_delete_count`. `delete_missing_notes` computes the
notes to remove and refuses if there are more than the caller allowed, logging
instead. Its default is 0, meaning "never delete unless asked". Those branches
get the most attention below.

`anki` is pinned at 23.10.1 and cannot move past 24.11 on this host: 25.02+
ships manylinux_2_35 wheels and CentOS Stream 9 has glibc 2.34. Everything here
mocks `Collection`, so the tests describe the API surface that pin protects —
`import_csv`, `export_note_csv`, `sync_login`, `sync_status`,
`sync_collection`, `full_upload_or_download`, `remove_notes` and the raw
`col.db.all` query.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
from anki.sync_pb2 import SyncStatusResponse
from django.test import TestCase, override_settings

from kukan.anki_dj import AnkiProfile

ANKI_ACCOUNTS = {
    'Fred': {'user': 'fred@example.com', 'password': 'pwd', 'backup': True},
    'Ayumi': {'user': 'ayumi@example.com', 'password': 'pwd', 'backup': True},
}

WEB_HEADER = ['#separator:tab', '#html:true',
              '#notetype column:1', '#deck column:2']
EXPORT_HEADER = ['#separator:tab', '#html:true', '#guid column:1',
                 '#notetype column:2', '#deck column:3']


def write_csv(path, header, rows):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(header) + '\n')
        for row in rows:
            f.write('\t'.join(str(c) for c in row) + '\n')


@override_settings(ANKI_ACCOUNTS=dict(ANKI_ACCOUNTS))
class AnkiProfileBasicsTest(TestCase):
    def test_profile_list_comes_from_settings(self):
        self.assertEqual(list(AnkiProfile.profile_list()),
                         ['Fred', 'Ayumi'])

    def test_decks_are_attached_to_the_profile(self):
        profile = AnkiProfile('Fred')
        self.assertEqual([d.name for d in profile.profile['decks']],
                         ['四字熟語', '書き取り', '読み', '諺'])

    def test_deck_carries_its_notetype_and_csv_name(self):
        deck = AnkiProfile('Fred').profile['decks'][0]
        self.assertEqual(deck.model, 'Cloze Yoji')
        self.assertEqual(deck.file_name, 'dj_anki_yoji.csv')

    def test_kind_list_strips_the_prefix_and_extension(self):
        """'dj_anki_yoji.csv' -> 'anki_yoji', which is the export choice key."""
        self.assertEqual(AnkiProfile('Fred').kind_list,
                         ['anki_yoji', 'anki_kaki', 'anki_yomi',
                          'anki_kotowaza'])

    def test_max_delete_count_defaults_to_zero(self):
        """Deleting nothing unless explicitly permitted is the safe default."""
        self.assertEqual(AnkiProfile('Fred').max_delete_count, 0)

    def test_close_collection_is_safe_when_never_opened(self):
        AnkiProfile('Fred').close_collection()

    def test_close_collection_closes_an_open_collection(self):
        profile = AnkiProfile('Fred')
        profile.col = MagicMock()
        profile.close_collection()
        profile.col.close.assert_called_once_with()

    @patch('kukan.anki_dj.Collection')
    def test_open_collection_points_at_the_profile_directory(self,
                                                             collection_cls):
        with override_settings(ANKI_DB_DIR='/anki'):
            AnkiProfile('Fred').open_collection()
        collection_cls.assert_called_once_with(
            os.path.join('/anki', 'Fred', 'collection.anki2'))


class ReadAnkiCsvTest(TestCase):
    """The CSV reader asserts the Anki header comments before parsing."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, 'deck.csv')

    def test_reads_three_columns_without_guid(self):
        write_csv(self.path, WEB_HEADER,
                  [['Kakitori', '書き取り', 'word1'],
                   ['Kakitori', '書き取り', 'word2']])
        df = AnkiProfile.read_anki_csv(self.path)
        self.assertEqual(df.shape, (2, 3))
        self.assertEqual(df.iloc[0].tolist(),
                         ['Kakitori', '書き取り', 'word1'])

    def test_reads_four_columns_with_guid(self):
        write_csv(self.path, EXPORT_HEADER,
                  [['guid1', 'Kakitori', '書き取り', 'word1']])
        df = AnkiProfile.read_anki_csv(self.path, with_guid=True)
        self.assertEqual(df.shape, (1, 4))
        self.assertEqual(df.iloc[0, 0], 'guid1')

    def test_extra_columns_beyond_the_key_are_ignored(self):
        """Notes carry more fields; only the identifying ones are read."""
        write_csv(self.path, WEB_HEADER,
                  [['Kakitori', '書き取り', 'word1', 'extra', 'more']])
        self.assertEqual(AnkiProfile.read_anki_csv(self.path).shape, (1, 3))

    def test_wrong_header_is_rejected(self):
        """Guards against importing a file written in a different format."""
        write_csv(self.path, ['#separator:comma', '#html:true',
                              '#notetype column:1', '#deck column:2'],
                  [['Kakitori', '書き取り', 'word1']])
        with self.assertRaisesMessage(AssertionError,
                                      'Expected comments not found'):
            AnkiProfile.read_anki_csv(self.path)

    def test_guid_header_is_required_when_guid_is_expected(self):
        write_csv(self.path, WEB_HEADER, [['Kakitori', '書き取り', 'w']])
        with self.assertRaises(AssertionError):
            AnkiProfile.read_anki_csv(self.path, with_guid=True)


@override_settings(ANKI_ACCOUNTS=dict(ANKI_ACCOUNTS))
class DeleteMissingNotesTest(TestCase):
    """The destructive path, and the guard that limits it."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

        self.deck = None
        self.profile = AnkiProfile('Fred')
        self.deck = self.profile.profile['decks'][1]  # 書き取り / Kakitori
        self.profile.col = MagicMock()

    def write_web_side(self, words):
        """The CSV this site exports: what *should* exist in Anki."""
        path = os.path.join(self.tmpdir.name, self.deck.file_name)
        write_csv(path, WEB_HEADER,
                  [[self.deck.model, self.deck.name, w] for w in words])
        return path

    def anki_side(self, words_with_guid):
        """What Anki currently holds, as the parsed export dataframe."""
        rows = [[guid, self.deck.model, self.deck.name, w]
                for guid, w in words_with_guid]
        return pd.DataFrame(rows, columns=[0, 1, 2, 3])

    def run_delete(self, web_words, anki_words, max_delete_count=0):
        self.profile.max_delete_count = max_delete_count
        self.write_web_side(web_words)
        self.profile.col.db.all.return_value = [
            [guid, idx] for idx, (guid, _) in enumerate(anki_words, start=100)]
        with override_settings(ANKI_IMPORT_DIR=self.tmpdir.name):
            return self.profile.delete_missing_notes(
                self.deck, self.anki_side(anki_words))

    def test_nothing_to_delete_when_both_sides_match(self):
        count = self.run_delete(['word1', 'word2'],
                                [('g1', 'word1'), ('g2', 'word2')])
        self.assertEqual(count, 0)
        self.profile.col.remove_notes.assert_not_called()

    def test_notes_missing_from_the_web_are_counted(self):
        count = self.run_delete(['word1'],
                                [('g1', 'word1'), ('g2', 'word2')])
        self.assertEqual(count, 1)

    def test_deletion_is_refused_when_over_the_limit(self):
        """The default limit of 0 blocks every deletion, and the notes stay."""
        count = self.run_delete(['word1'],
                                [('g1', 'word1'), ('g2', 'word2')],
                                max_delete_count=0)
        self.assertEqual(count, 1)
        self.profile.col.remove_notes.assert_not_called()

    def test_deletion_proceeds_when_within_the_limit(self):
        self.run_delete(['word1'], [('g1', 'word1'), ('g2', 'word2')],
                        max_delete_count=5)
        self.profile.col.remove_notes.assert_called_once_with([101])

    def test_limit_is_exclusive(self):
        """`len_del > max_delete_count` refuses, so exactly the limit passes."""
        self.run_delete(['word1'], [('g1', 'word1'), ('g2', 'word2')],
                        max_delete_count=1)
        self.profile.col.remove_notes.assert_called_once_with([101])

    def test_one_over_the_limit_refuses_the_whole_batch(self):
        """All-or-nothing: it does not delete up to the limit."""
        count = self.run_delete(
            ['w1'], [('g1', 'w1'), ('g2', 'w2'), ('g3', 'w3')],
            max_delete_count=1)
        self.assertEqual(count, 2)
        self.profile.col.remove_notes.assert_not_called()

    def test_note_present_on_the_web_but_not_in_anki_is_an_error(self):
        """Import runs first, so by this point every web note must exist in
        Anki. If not, the import silently failed and deleting would be wrong."""
        with self.assertRaises(AssertionError):
            self.run_delete(['word1', 'word2'], [('g1', 'word1')],
                            max_delete_count=5)

    def test_duplicate_rows_on_the_web_side_are_rejected(self):
        with self.assertRaises(AssertionError):
            self.run_delete(['word1', 'word1'], [('g1', 'word1')],
                            max_delete_count=5)

    def test_only_the_requested_deck_is_considered(self):
        """Other decks appear in the same export and must be left alone."""
        self.profile.max_delete_count = 5
        self.write_web_side(['word1'])
        other = pd.DataFrame(
            [['g1', self.deck.model, self.deck.name, 'word1'],
             ['g9', 'Yomi', '読み', 'other-deck-word']],
            columns=[0, 1, 2, 3])
        self.profile.col.db.all.return_value = [['g1', 100], ['g9', 109]]
        with override_settings(ANKI_IMPORT_DIR=self.tmpdir.name):
            count = self.profile.delete_missing_notes(self.deck, other)
        self.assertEqual(count, 0)
        self.profile.col.remove_notes.assert_not_called()

    def test_missing_import_file_is_an_error(self):
        self.profile.max_delete_count = 5
        with override_settings(ANKI_IMPORT_DIR=self.tmpdir.name), \
                self.assertRaises(AssertionError):
            self.profile.delete_missing_notes(
                self.deck, self.anki_side([('g1', 'word1')]))


@override_settings(ANKI_ACCOUNTS=dict(ANKI_ACCOUNTS))
class ImportFileTest(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.profile = AnkiProfile('Fred')
        self.deck = self.profile.profile['decks'][1]
        self.profile.col = MagicMock()
        open(os.path.join(self.tmpdir.name, self.deck.file_name), 'w').close()
        # ImportCsvRequest is a protobuf message and rejects a MagicMock, so
        # get_csv_metadata has to hand back the real type.
        from anki.import_export_pb2 import CsvMetadata
        self.profile.col.get_csv_metadata.return_value = CsvMetadata()

    def test_returns_counts_of_new_matched_and_duplicate(self):
        response = self.profile.col.import_csv.return_value
        response.log.new = ['a', 'b']
        response.log.first_field_match = ['c']
        response.log.duplicate = []
        with override_settings(ANKI_IMPORT_DIR=self.tmpdir.name):
            self.assertEqual(self.profile.import_file(self.deck), (2, 1, 0))

    def test_missing_file_is_an_error_before_touching_the_collection(self):
        with override_settings(ANKI_IMPORT_DIR='/nonexistent'), \
                self.assertRaises(AssertionError):
            self.profile.import_file(self.deck)
        self.profile.col.import_csv.assert_not_called()


@override_settings(ANKI_ACCOUNTS=dict(ANKI_ACCOUNTS))
class SyncServerTest(TestCase):
    """The sync state machine, over AnkiWeb's status responses."""

    def setUp(self):
        self.profile = AnkiProfile('Fred')
        self.profile.col = MagicMock()
        self.auth = self.profile.col.sync_login.return_value

    def set_status(self, status):
        self.profile.col.sync_status.return_value.required = status

    def test_logs_in_with_the_configured_credentials(self):
        self.set_status(SyncStatusResponse.NO_CHANGES)
        self.profile.sync_server(initial_sync=True)
        self.profile.col.sync_login.assert_called_once_with(
            'fred@example.com', 'pwd', None)

    def test_no_changes_does_nothing_further(self):
        self.set_status(SyncStatusResponse.NO_CHANGES)
        self.profile.sync_server(initial_sync=True)
        self.profile.col.sync_collection.assert_not_called()
        self.profile.col.full_upload_or_download.assert_not_called()

    def test_normal_sync_syncs_the_collection(self):
        self.set_status(SyncStatusResponse.NORMAL_SYNC)
        self.profile.col.sync_collection.return_value.required = \
            SyncStatusResponse.NO_CHANGES
        self.profile.sync_server(initial_sync=True)
        self.profile.col.sync_collection.assert_called_once_with(
            self.auth, False)
        self.profile.col.full_upload_or_download.assert_not_called()

    def test_full_sync_downloads_on_the_initial_sync(self):
        """Download, never upload: the server copy wins on the way in."""
        self.set_status(SyncStatusResponse.FULL_SYNC)
        self.profile.sync_server(initial_sync=True)
        self.profile.col.full_upload_or_download.assert_called_once_with(
            auth=self.auth, server_usn=None, upload=False)

    def test_normal_sync_escalating_to_full_sync_is_honoured(self):
        self.set_status(SyncStatusResponse.NORMAL_SYNC)
        self.profile.col.sync_collection.return_value.required = \
            SyncStatusResponse.FULL_SYNC
        self.profile.sync_server(initial_sync=True)
        self.profile.col.full_upload_or_download.assert_called_once()

    def test_full_sync_on_the_final_sync_is_refused(self):
        """A full sync after local edits would discard them, so it raises
        rather than silently overwriting the night's work."""
        self.set_status(SyncStatusResponse.FULL_SYNC)
        with self.assertRaisesMessage(Exception,
                                      'Full sync not allowed on final sync'):
            self.profile.sync_server(initial_sync=False)
        self.profile.col.full_upload_or_download.assert_not_called()

    def test_unexpected_status_raises(self):
        self.set_status(999)
        with self.assertRaisesMessage(Exception, 'Return value not expected'):
            self.profile.sync_server(initial_sync=True)


@override_settings(ANKI_ACCOUNTS=dict(ANKI_ACCOUNTS))
class SyncOrchestrationTest(TestCase):
    """`sync` is open, pull, apply, push — in that order."""

    def test_sync_runs_the_full_cycle_in_order(self):
        profile = AnkiProfile('Fred')
        calls = []
        with patch.object(AnkiProfile, 'open_collection',
                          side_effect=lambda: calls.append('open')), \
                patch.object(AnkiProfile, 'sync_server',
                             side_effect=lambda *, initial_sync: calls.append(
                                 f'sync:{initial_sync}')), \
                patch.object(AnkiProfile, 'apply_to_anki',
                             side_effect=lambda: calls.append('apply')
                             or pd.DataFrame()):
            profile.sync()

        self.assertEqual(calls,
                         ['open', 'sync:True', 'apply', 'sync:False'])
