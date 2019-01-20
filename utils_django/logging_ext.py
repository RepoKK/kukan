import bz2
import datetime
import logging
import os
import re


class PerRunFileHandler(logging.FileHandler):
    """
    A handler class which writes formatted logging records to disk files.
    The file name will have the creation timestamp appended to the filename.
    When a new file is created, the old files will be zipped and moved to the log_backup_dir
    """

    def __init__(self, log_dir, log_name_base, log_backup_dir='prev_logs', backup_count=20,
                 encoding='utf-8', delay=False):
        self.log_dir = log_dir
        self.log_name_base = log_name_base
        self.log_backup_dir = log_backup_dir
        self.backup_count = backup_count

        self.logs_house_cleaning()

        now = datetime.datetime.strftime(datetime.datetime.now(), '%Y%m%d-%H%M%S')
        self.log_file_name = '{}_{}.log'.format(self.log_name_base, now)

        super().__init__(os.path.join(self.log_dir, self.log_file_name), 'a', encoding, delay)

    def is_relevant_file(self, filename):
        """
        Check if a filename is relevant to the handler - that is to say, start with the log_name_base string and match
        the file naming pattern
        Note that compressed files will pass the test

        :param filename: the filename to check
        :rtype: bool, True if the file is a log created by this handler.
        """
        correct_base_name = filename[:len(self.log_name_base)] == self.log_name_base
        match_pattern = re.match(r'^{}_\d{{8}}-\d{{6}}(_\d+)?.log(.bz2)?$'.format(self.log_name_base),
                                 filename)
        return all([correct_base_name, match_pattern])

    def logs_house_cleaning(self):
        """
        Move the old files to the log_backup_dir directory and compress them.
        """
        # Create all log folders
        log_backup_dir_path = os.path.join(self.log_dir, self.log_backup_dir)
        os.makedirs(log_backup_dir_path, exist_ok=True)

        for file_name in filter(self.is_relevant_file, os.listdir(self.log_dir)):
            source_file_name = os.path.join(self.log_dir, file_name)
            target_file_name = os.path.join(log_backup_dir_path, file_name + '.bz2')

            idx = 0
            while os.path.exists(target_file_name):
                idx = idx + 1
                target_file_name = os.path.join(log_backup_dir_path, '{}_{}.log.bz2'.format(file_name[:-4], idx))

            with open(source_file_name, 'rb') as source_file, open(target_file_name, 'wb') as target_file:
                target_file.write(bz2.compress(source_file.read(), 9))
            os.remove(source_file_name)

        for file_name in sorted(filter(self.is_relevant_file, os.listdir(log_backup_dir_path)))[:-self.backup_count]:
            os.remove(os.path.join(log_backup_dir_path, file_name))

    def __repr__(self):
        level = logging.getLevelName(self.level)
        return '<%s %s %s (%s)>' % (self.__class__.__name__, self.log_dir, self.log_file_name, level)
