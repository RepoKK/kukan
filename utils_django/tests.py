import datetime
import glob
import logging
import os
import sys
import unittest
from contextlib import contextmanager
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings, TestCase
from freezegun import freeze_time
from pyfakefs.fake_filesystem_unittest import TestCaseMixin

from utils_django.apps import UtilsDjangoConfig
from utils_django.decorators import OrderFromAttr
from utils_django.logging_ext import PerRunFileHandler
from utils_django.management_command import FBaseCommand
from utils_django.models import ManagementCommandRun


class TestUtilsDjangoApps(TestCase):
    def test_apps(self):
        self.assertEqual(UtilsDjangoConfig.name, 'utils_django')


class OrderFromAttrDecorator(TestCase):

    @OrderFromAttr('value')
    class TestClass:
        def __init__(self, name, value):
            self.value = value
            self.name = name

        def __repr__(self):
            return self.name

    def assertListStrictlyIdentical(self, first, second):
        self.assertCountEqual(first, second)
        for a, b in zip(first, second):
            self.assertIs(a, b)

    def test_all(self):
        test_a = self.TestClass('A', 5)
        test_b = self.TestClass('B', 3)
        test_c = self.TestClass('C', 5)

        self.assertIs(test_a, test_a)
        self.assertIsNot(test_a, test_c)

        self.assertEqual(test_a, test_c)
        self.assertGreaterEqual(test_a, test_c)
        self.assertLessEqual(test_a, test_c)
        self.assertNotEqual(test_a, test_b)
        self.assertGreaterEqual(test_a, test_b)
        self.assertGreater(test_a, test_b)
        self.assertLessEqual(test_b, test_c)
        self.assertLess(test_b, test_c)

        self.assertListStrictlyIdentical([test_b, test_c, test_a], sorted([test_c, test_a, test_b]))
        with self.assertRaises(AssertionError):
            self.assertListStrictlyIdentical([test_b, test_a, test_c], sorted([test_c, test_a, test_b]))
        self.assertEqual([test_b, test_a, test_c], sorted([test_c, test_a, test_b]))

    def test_ComparisonAgainstOtherTypes(self):
        test_a = self.TestClass('A', 5)
        with self.assertRaises(AssertionError):
            self.assertEqual(test_a, 5)


class TestPerRunFileHandler(SimpleTestCase, TestCaseMixin):
    def setUp(self):
        self.setUpPyfakefs()
        self.log_dir = os.path.join(settings.BASE_DIR, 'logs')
        self.base_name = 'test_base_name'
        self.fs.create_dir(self.log_dir)

    @contextmanager
    def get_handler(self, base_name='', log_backup_dir='prev_logs', backup_count=20):
        if not base_name:
            base_name = self.base_name
        handler = PerRunFileHandler(self.log_dir, base_name, log_backup_dir, backup_count)
        yield handler
        handler.close()

    @freeze_time("2012-01-14 03:21:34")
    def test_log_name(self):
        with self.get_handler() as handler:
            self.assertEqual('test_base_name_20120114-032134.log', handler.log_file_name)

    def test_log_contents(self):
        with self.get_handler() as handler:
            logger = logging.getLogger('test')
            logger.propagate = False
            logger.setLevel(logging.DEBUG)
            handler.setLevel(logging.DEBUG)
            # add the handlers to the logger
            logger.addHandler(handler)
            test_text = 'TEST TEXT'
            logger.info(test_text)
            with open(os.path.join(self.log_dir, handler.log_file_name)) as f:
                self.assertEqual(test_text + '\n', str(f.read()))

    @patch('utils_django.logging_ext.PerRunFileHandler.logs_house_cleaning')
    def test_is_relevant_file(self, mock):
        with self.get_handler() as handler:
            pass
        for file_name in [
            'test_base_name_20190117-211451.log',
            'test_base_name_20190117-211451_1.log',
            'test_base_name_20190117-211451_12.log'
        ]:
            with self.subTest('relevant', file_name=file_name):
                self.assertTrue(handler.is_relevant_file(file_name))
                self.assertTrue(handler.is_relevant_file(file_name + '.bz2'))

        for file_name in [
            'test_base_name__20190117-211451.log',
            'test_base_name__20190117-21151.log',
            'a_test_base_name_20190117-211451.log',
            'test_base_name_20190117-211451.log_a',
            'tet_base_name_20190117-211451.log',
            'test_base_name_20190117-211451_1.lo',
            'test_base_name_20190117-211451_1.log.x'
        ]:
            with self.subTest('not relevant', file_name=file_name):
                self.assertFalse(handler.is_relevant_file(file_name))
                self.assertFalse(handler.is_relevant_file(file_name + '.bz2'))

        mock.assert_called()

    @patch('utils_django.logging_ext.PerRunFileHandler.logs_house_cleaning')
    def test_repr(self, mock):
        with self.get_handler('test_base_name') as handler:
            handler.setLevel(logging.DEBUG)

        self.assertEqual(r'<PerRunFileHandler {} {} (DEBUG)>'.format(
            self.log_dir, handler.log_file_name), repr(handler))
        mock.assert_called()

    def test_logs_house_cleaning(self):
        prev_logs = 'prev_logs'
        logs_dir = self.log_dir
        list_existing_log_file = ['{}_20180130-12000{}.log'.format(self.base_name, idx) for idx in range(10)]
        list_extra_file = ['dummy', 'dummy2']

        for file_path in [os.path.join(logs_dir, f) for f in list_existing_log_file + list_extra_file]:
            self.fs.create_file(file_path, contents=file_path)

        with self.get_handler(backup_count=10) as handler:
            file1 = handler.log_file_name
            self.assertCountEqual(os.listdir(logs_dir), ['dummy', 'dummy2', file1, prev_logs])
            self.assertCountEqual(os.listdir(os.path.join(logs_dir, prev_logs)),
                                  [f + '.bz2' for f in list_existing_log_file])

        with self.get_handler(backup_count=10) as handler:
            self.assertCountEqual(os.listdir(logs_dir), ['dummy', 'dummy2', handler.log_file_name, prev_logs])
            self.assertCountEqual(os.listdir(os.path.join(logs_dir, prev_logs)),
                                  [f + '.bz2' for f in list_existing_log_file[1:]] + [file1 + '.bz2'])

        # Case a new file has same timestamp as a backed up one
        os.remove(os.path.join(logs_dir, handler.log_file_name))
        file2 = '{}_20180130-120005.log'.format(self.base_name)
        self.fs.create_file(os.path.join(logs_dir, file2), contents=file2)

        with self.get_handler(backup_count=10) as handler:
            self.assertCountEqual(os.listdir(logs_dir), ['dummy', 'dummy2', handler.log_file_name, prev_logs])
            self.assertCountEqual(os.listdir(os.path.join(logs_dir, prev_logs)),
                                  [f + '.bz2' for f in list_existing_log_file[2:] + [file1, file2[:-4] + '_1.log']])


class TestFBaseCommand(TestCase, TestCaseMixin):
    def setUp(self):
        self.setUpPyfakefs()
        self.log_dir = os.path.join(settings.BASE_DIR, 'logs')
        os.makedirs(self.log_dir)
        self.info_log_path = os.path.join(self.log_dir, 'info.log')

        self.logger = logging.getLogger(__name__.split('.')[0])
        self.logger.setLevel(logging.DEBUG)
        self.handler = logging.FileHandler(self.info_log_path)
        self.handler.set_name('default_file_test')
        self.handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('TTT %(message)s')
        self.handler.setFormatter(formatter)
        self.logger.addHandler(self.handler)

        ManagementCommandRun.objects.all().delete()

    def tearDown(self):
        super().tearDown()
        self.logger.removeHandler(self.handler)
        self.handler.close()
        self.handler = None

    class MakeTestCmd(object):
        def __call__(self, decorated):
            decorated.cmd_name = 'test_f_base_cmd'
            decorated.default_handler_name = 'default_file_test'
            decorated.__module__ = '{}.{}'.format(__name__, decorated.cmd_name)
            return decorated

    @MakeTestCmd()
    class DummyCommand(FBaseCommand):
        def handle_cmd(self, *args, **options):
            pass

    # noinspection PyAbstractClass
    def test_command_implement(self):
        class NotImplementedCommand(FBaseCommand):
            pass

        with self.assertRaises(NotImplementedError):
            call_command(NotImplementedCommand())

    @freeze_time("2019-01-14 03:21:34")
    def test_command_log(self):

        test_text = 'Test'

        # Dynamically create a Management command module for testing purpose
        @TestFBaseCommand.MakeTestCmd()
        class Command(FBaseCommand):
            def handle_cmd(self, *args, **options):
                self.logger.info(test_text)

        # The call_command does accept a Command object as well as a string
        call_command(Command())

        cmd_log_name = '{}_{}.log'.format(Command.cmd_name, "20190114-032134")

        with open(os.path.join(self.log_dir, cmd_log_name), 'r') as f:
            self.assertEqual((
                'TTT Start execution of command test_f_base_cmd\n'
                "TTT Options: {'verbosity': 1, 'settings': None, 'pythonpath': None, "
                "'traceback': False, 'no_color': False, "
                "'force_color': False, 'skip_checks': True}\n"
                'TTT Test\n'
                'TTT End execution, took 0 minutes\n'
            ), str(f.read()))

        with open(os.path.join(self.info_log_path)) as f:
            self.assertEqual('', str(f.read()))

    def test_warning_time(self):
        with freeze_time(datetime.datetime.now()) as frozen_datetime:
            @TestFBaseCommand.MakeTestCmd()
            class Command(FBaseCommand):
                warning_time = 10

                def handle_cmd(self, *args, **options):
                    frozen_datetime.tick(delta=datetime.timedelta(minutes=self.warning_time + 1))

            call_command(Command())

            with open(glob.glob(os.path.join(self.log_dir, Command.cmd_name + '*'))[0]) as f:
                self.assertIn('Execution of command {} took more than {} minutes'.format(
                    Command.cmd_name, Command.warning_time), str(f.read()))

    @freeze_time("2019-01-14 03:21:34")
    def test_lock_model_repr(self):
        rec = ManagementCommandRun.objects.create(cmd_name='test_cmd', cmd_pid=1234)
        self.assertEqual('Command test_cmd (1234), start time: 2019-01-14 03:21:34+00:00', repr(rec))

    def test_lock_removal(self):
        self.assertFalse(ManagementCommandRun.objects.exists())
        call_command(TestFBaseCommand.DummyCommand())
        self.assertFalse(ManagementCommandRun.objects.exists())

    @freeze_time("2019-01-14 03:21:34")
    def test_lock_block_second(self):
        ManagementCommandRun.objects.create(cmd_name='test_cmd', cmd_pid=1234)
        rec_expected_repr = 'Command test_cmd (1234), start time: 2019-01-14 03:21:34+00:00'
        with self.assertRaises(FBaseCommand.CommandInProgress):
            call_command(TestFBaseCommand.DummyCommand())
        with open(self.info_log_path, 'r') as f:
            self.assertEqual(
                'TTT Failed to run test_f_base_cmd, already running command: {}\n'.format(rec_expected_repr),
                str(f.read()))

        try:
            call_command(TestFBaseCommand.DummyCommand())
        except FBaseCommand.CommandInProgress as e:
            self.assertEqual(rec_expected_repr, repr(e.rec))

    def test_lock_exception(self):
        @TestFBaseCommand.MakeTestCmd()
        class Command(FBaseCommand):
            def handle_cmd(self, *args, **options):
                raise AssertionError('problem')

        self.assertFalse(ManagementCommandRun.objects.exists())
        with self.assertRaises(AssertionError):
            call_command(Command())
        self.assertFalse(ManagementCommandRun.objects.exists())


class TestVacuum(unittest.TestCase, TestCaseMixin):
    def setUp(self):
        self.setUpPyfakefs()

    def test_vacuum(self):
        call_command('vacuum_sqlite')


@override_settings(BASE_DIR='base')
class TestSetCron(TestCase):
    def setUp(self):
        self.virtual_env = os.path.join(sys.exec_prefix, 'bin', 'activate')

    def test_get_cron_stings(self):
        test_setting = [
            {'schedule': '05 12 * * 1-5',
             'command': 'test_cmd',
             'arguments': {'arg_a': 'U', 'arg_b': 1}},
            {'schedule': '01 12 * * 1-5',
             'command': 'cmd2',
             'arguments': {'arg_a': 'V', 'arg_flag': None}}
        ]
        with override_settings(CRON_CFG=test_setting):
            out = StringIO()
            call_command('set_cron', stdout=out)

            self.assertEqual(
                ('Generated cron:\n' +
                 '05 12 * * 1-5 source {v}; python base/manage.py test_cmd --arg_a U --arg_b 1\n' +
                 '01 12 * * 1-5 source {v}; python base/manage.py cmd2 --arg_a V --arg_flag\n\n' +
                 'Use the --exec flag to replace existing cron\n').format(v=self.virtual_env),
                out.getvalue()
            )

    def test_get_cron_stings_no_args(self):
        test_setting = [
            {'schedule': '05 12 * * 1-5',
             'command': 'test_cmd'}
        ]

        with override_settings(CRON_CFG=test_setting):
            out = StringIO()
            call_command('set_cron', stdout=out)

            self.assertEqual(
                ('Generated cron:\n' +
                 '05 12 * * 1-5 source {}; python base/manage.py test_cmd\n\n' +
                 'Use the --exec flag to replace existing cron\n').format(self.virtual_env),
                out.getvalue()
            )

    def test_missing_key(self):
        with override_settings(CRON_CFG=[{'command': 'test_cmd'}]):
            out = StringIO()
            call_command('set_cron', stdout=out)

            self.assertEqual(
                "Key 'schedule' not found in config: {'command': 'test_cmd'}\n",
                out.getvalue()
            )

    def test_non_django(self):
        with override_settings(CRON_CFG=[{'schedule': '05 12 * * 1-5',
                                          'command': 'my_own_cmd',
                                          'non_django': True,
                                          'arguments': {'A': 1}}]):
            out = StringIO()
            call_command('set_cron', stdout=out)
            self.assertEqual(
                ('Generated cron:\n' +
                 '05 12 * * 1-5 my_own_cmd --A 1\n\n' +
                 'Use the --exec flag to replace existing cron\n').format(self.virtual_env),
                out.getvalue()
            )

    def test_exec(self):
        with override_settings(CRON_CFG=[{'schedule': '05 12 * * 1-5', 'command': 'test_cmd'}]):
            out = StringIO()
            with patch('utils_django.management.commands.set_cron.subprocess') as mock_sp:
                call_command('set_cron', '--exec', stdout=out)
                self.assertEqual(
                    ('05 12 * * 1-5 source {}; '
                     'python base/manage.py test_cmd\n'.format(self.virtual_env)),
                    mock_sp.Popen.mock_calls[1][1][0].decode()
                )

            self.assertEqual(
                ('Set cron as:\n' +
                 '05 12 * * 1-5 source {}; python base/manage.py test_cmd\n').format(self.virtual_env),
                out.getvalue()
            )


class TestClearCmdLock(TestCase):
    def setUp(self):
        ManagementCommandRun.objects.create(cmd_name='test_cmd', cmd_pid=1234)

    def test_command(self):
        self.assertTrue(ManagementCommandRun.objects.exists())
        call_command('clear_cmd_lock')
        self.assertFalse(ManagementCommandRun.objects.exists())
