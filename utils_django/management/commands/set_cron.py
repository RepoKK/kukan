import os
import subprocess
import sys

from django.conf import settings

from utils_django.management_command import FBaseCommand


class Command(FBaseCommand):
    """
    Settings format:
    CRON_CFG = [
        {
            'schedule': '10 12  * * 0-6',
            'command': 'django_management_command',
            'arguments': {
                'arg_1': 'value',
                'arg_2': 'value',
                'arg_flag': None,           # For flag-type arguments, without value
            }
        },
        ...
    ]
    """

    help = 'Set crontab for Django'

    def add_arguments(self, parser):
        parser.add_argument(
            '--exec',
            dest='exec',
            action='store_true',
            help='Replace the existing cron with generated one.'
        )

    def __init__(self):
        super().__init__()
        virtual_env = os.path.join(sys.exec_prefix, 'bin', 'activate')
        self.base_string = '{{}} source {}; python {{}}/manage.py {{}}'.format(virtual_env)
        self.cron_cfg = getattr(settings, 'CRON_CFG', [])

    def _cron_cmd(self, cfg):
        if cfg.get('non_django', False):
            base = '{} {}'.format(cfg['schedule'], cfg['command'])
        else:
            base = self.base_string.format(cfg['schedule'], settings.BASE_DIR, cfg['command'])

        return ' '.join([base] + [f'--{k}{" " + str(v) if v else ""}' for k, v in cfg.get('arguments', {}).items()])

    def get_all_configs(self):
        list_cfg_string = []
        for cfg in self.cron_cfg:
            try:
                list_cfg_string.append(self._cron_cmd(cfg))
            except KeyError as e:
                self.stdout.write('Key {} not found in config: {}'.format(e, cfg))
                return ''
        return '\n'.join(list_cfg_string) + '\n'

    def handle_cmd(self, *args, **options):
        cron_content = self.get_all_configs()
        if cron_content:
            if options['exec']:
                cron = subprocess.Popen("crontab", stdin=subprocess.PIPE)
                cron.communicate(cron_content.encode())

                self.stdout.write('Set cron as:\n{}'.format(cron_content))
            else:
                self.stdout.write(
                    'Generated cron:\n{}\nUse the --exec flag to replace existing cron'.format(
                        cron_content)
                )
