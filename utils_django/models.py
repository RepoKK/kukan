from django.db import models


class ManagementCommandRun(models.Model):
    """
    Lock for the FBaseCommand: if a record is present in that table a new command is prevented from running
    """
    cmd_pid = models.IntegerField('Command PID')
    cmd_name = models.CharField('Command name', max_length=20)
    updated_time = models.DateTimeField('Timestamp', auto_now=True)

    def __repr__(self):
        return 'Command {} ({}), start time: {}'.format(self.cmd_name, self.cmd_pid, self.updated_time)

    def __str__(self):
        return repr(self)
