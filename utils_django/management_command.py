import logging
import os
import time
from contextlib import contextmanager

from django.conf import settings
from django.core.management import BaseCommand, CommandError

from utils_django.logging_ext import PerRunFileHandler
from utils_django.models import ManagementCommandRun

logger = logging.getLogger(__name__)


class FBaseCommand(BaseCommand):
    # The time, in minute, before a warning is raised (note: currently the
    # warning is raised once the task finishes)
    warning_time = 5
    backup_count = 20
    use_lock = True

    default_handler_name = 'default_file'
    try:
        log_dir = settings.LOGGING_BASE_DIR
    except AttributeError:
        log_dir = os.path.join(settings.BASE_DIR, 'logs')

    def __init__(self, stdout=None, stderr=None, no_color=False):
        self.cmd_name = self.__class__.__module__.split('.')[-1]
        self.app = self.__class__.__module__.split('.')[0]
        self.default_file_handler = None
        self.command_log_handler = None
        self.root_logger = logging.getLogger()

        super().__init__(stdout, stderr, no_color)

    def handle_cmd(self, *args, **options):
        """
        The actual logic of the command. Subclasses must implement this method.
        """
        raise NotImplementedError('subclasses of FidBaseCommand must provide a handle_cmd() method')

    class CommandInProgress(Exception):
        def __init__(self, rec):
            self.rec = rec

    def raise_error(self):
        """
        Raise a CommandError with a simple text pointing to the log file
        Example:
            CommandError: sod_autochecks failure
            Log: /data/uranai/run/runtime/logs/sod_autochecks_20190605-193520.log
        """
        raise CommandError(f'{self.cmd_name} failure\n'
                           f'Log: {self.command_log_handler.baseFilename}')

    @staticmethod
    def default_handler_filter(rec):
        """
        Filter the log record to allow only logging from this module,
        which allow to log 'start'/'end' of command logs in the main log file.
        """
        return rec.name == __name__

    def set_command_logger(self, verbosity):
        self.command_log_handler = PerRunFileHandler(self.log_dir, self.cmd_name, backup_count=self.backup_count)
        self.command_log_handler.set_name('command_log_file')
        self.command_log_handler.setLevel(logging.DEBUG)

        self.root_logger.addHandler(self.command_log_handler)

        if verbosity > 1:
            self.root_logger.level = logging.DEBUG

        found = False
        for handler in self.root_logger.handlers:
            if handler.get_name() == self.default_handler_name:
                self.default_file_handler = handler
                self.default_file_handler.addFilter(self.default_handler_filter)
                self.command_log_handler.setFormatter(handler.formatter)
                found = True

        assert found, 'The "default_file" log handler is not found'

    def remove_command_logger(self):
        if self.default_file_handler:
            self.default_file_handler.removeFilter(self.default_handler_filter)
        if self.command_log_handler:
            self.command_log_handler.close()
            self.root_logger.removeHandler(self.command_log_handler)
            self.command_log_handler = None

    @contextmanager
    def command_lock(self, verbosity):
        rec = ManagementCommandRun.objects.first()
        if rec:
            logger.error(f'Failed to run {self.cmd_name}, '
                         f'already running command: {rec}')
            raise self.CommandInProgress(rec)
        try:
            ManagementCommandRun.objects.create(cmd_name=self.cmd_name,
                                                cmd_pid=os.getpid())
            self.set_command_logger(verbosity)
            yield None
        finally:
            ManagementCommandRun.objects.all().delete()
            self.remove_command_logger()

    @contextmanager
    def log_only(self, verbosity):
        self.set_command_logger(verbosity)
        yield None
        self.remove_command_logger()

    def handle(self, *args, **options):
        start_time = time.time()
        lock_function = self.command_lock if self.use_lock else self.log_only
        with lock_function(options['verbosity']):
            logger.info("Start execution of command %s", self.cmd_name)
            logger.info("Options: %s", options)

            try:
                self.handle_cmd(self, *args, **options)
            except Exception as e:
                logger.exception(e)
                logger.error(f'Failed to complete a command '
                             f'{self.cmd_name}: {str(e)}')
                raise e

            time_spent = (time.time() - start_time) / 60
            if time_spent > self.warning_time:
                logger.warning("Execution of command %s took more than "
                               "%d minutes (took %d)",
                               self.cmd_name, self.warning_time, time_spent)

            logger.info("End execution, took %d minutes", time_spent)

