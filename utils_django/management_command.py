import logging
import os
import time

from decorator import contextmanager
from django.conf import settings
from django.core.management import BaseCommand

from utils_django.logging_ext import PerRunFileHandler
from utils_django.models import ManagementCommandRun


class FBaseCommand(BaseCommand):

    # The time, in minute, before a warning is raised (note: currently the warning is raised once the task finishes)
    warning_time = 5
    backup_count = 20
    default_handler_name = 'default_file'
    log_dir = os.path.join(settings.BASE_DIR, 'logs')

    def __init__(self, stdout=None, stderr=None, no_color=False):
        self.cmd_name = self.__class__.__module__.split('.')[-1]
        self.app = self.__class__.__module__.split('.')[0]
        self.default_file_handler = None
        self.command_log_handler = None
        self.logger = logging.getLogger(self.app)

        super().__init__(stdout, stderr, no_color)

    def handle_cmd(self, *args, **options):
        """
        The actual logic of the command. Subclasses must implement this method.
        """
        raise NotImplementedError('subclasses of FidBaseCommand must provide a handle_cmd() method')

    class CommandInProgress(Exception):
        def __init__(self, rec):
            self.rec = rec

    def set_command_logger(self):
        self.command_log_handler = PerRunFileHandler(self.log_dir, self.cmd_name, backup_count=self.backup_count)
        self.command_log_handler.set_name('command_log_file')
        self.command_log_handler.setLevel(logging.DEBUG)

        self.logger.addHandler(self.command_log_handler)

        for handler in self.logger.handlers:
            if handler.get_name() == self.default_handler_name:
                self.default_file_handler = handler
                self.command_log_handler.setFormatter(handler.formatter)
                self.logger.removeHandler(self.default_file_handler)

    def remove_command_logger(self):
        if self.default_file_handler:
            self.logger.addHandler(self.default_file_handler)
            self.default_file_handler = None
        if self.command_log_handler:
            self.command_log_handler.close()
            self.logger.removeHandler(self.command_log_handler)
            self.command_log_handler = None

    @contextmanager
    def command_lock(self):
        rec = ManagementCommandRun.objects.first()
        if rec:
            self.logger.error('Failed to run {}, already running command: {}'.format(self.cmd_name, rec))
            raise self.CommandInProgress(rec)
        ManagementCommandRun.objects.get_or_create(cmd_name=self.cmd_name, cmd_pid=os.getpid())
        try:
            self.set_command_logger()
            yield None
        finally:
            ManagementCommandRun.objects.all().delete()
            self.remove_command_logger()

    def handle(self, *args, **options):
        start_time = time.time()
        with self.command_lock():
            self.logger.info("Start execution of command %s", self.cmd_name)
            self.logger.info("Options: %s", options)
            self.handle_cmd(self, *args, **options)
            time_spent = (time.time() - start_time) / 60
            if time_spent > self.warning_time:
                self.logger.warning("Execution of command %s took more than %d minutes (took %d)",
                                    self.cmd_name, self.warning_time, time_spent)

            self.logger.info("End execution, took %d minutes", time_spent)
