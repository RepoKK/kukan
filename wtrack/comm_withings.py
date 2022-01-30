import logging
import os
import pickle
from os import path
from typing import cast, Tuple

import arrow
from django.conf import settings
from django.core.mail import mail_admins
from django.utils.html import strip_tags
from oauthlib.oauth2 import MissingTokenError
from withings_api import WithingsAuth, WithingsApi, CredentialsType,\
    AuthScope, MeasureType, MeasureGetMeasGroupCategory
from withings_api.common import AuthFailedException, \
    query_measure_groups

from wtrack.models import Measurement, Settings

logger = logging.getLogger(__name__)


class CommWithings:
    CREDENTIALS_FILE = path.abspath(
        path.join(path.dirname(path.abspath(__file__)), "../.credentials")
    )

    class NotAuthorized(Exception):
        pass

    def __init__(self):
        self.api = None
        self.scale = Settings.objects.first().default_scale

        self.auth = WithingsAuth(
            client_id=settings.WITHINGS_API_CLIENT_ID,
            consumer_secret=settings.WITHINGS_API_CONSUMER_SECRET,
            callback_uri=settings.WITHINGS_API_CALLBACK_URI,
            scope=(
                AuthScope.USER_ACTIVITY,
                AuthScope.USER_METRICS,
                AuthScope.USER_INFO,
                AuthScope.USER_SLEEP_EVENTS,
            ),
        )

    def connect(self) -> bool:
        if Settings.objects.first().token:
            logger.info(f'Attempting to load credentials from database:')
            self.api = WithingsApi(self._load_credentials(),
                                   refresh_cb=self._save_credentials)
            try:
                self.api.user_get_device()

                orig_access_token = self.api.get_credentials().access_token
                logger.info('Refreshing token...')
                self.api.refresh_token()
                assert orig_access_token \
                       != self.api.get_credentials().access_token
            except (MissingTokenError, AuthFailedException):
                os.remove(self.CREDENTIALS_FILE)
                self.api = None
                logger.info('Credentials in file are expired.')
                raise CommWithings.NotAuthorized
        else:
            logger.info('No credentials file found.')
            raise CommWithings.NotAuthorized

        return self.api is not None

    def authorize_request(self):
        logger.info('Attempting to get credentials...')

        authorize_url = self.get_authorize_url()
        subject = 'Withings API authorization request'
        html_message = (
            f'<html><body><div>'
            f'The application needs to be authorized with Withings API.</div>'
            f'<div>Go to this <a href="{authorize_url}">link</a>'
            f' and authorize.</div>'
            f'</body></html>'
        )
        plain_message = strip_tags(html_message)
        mail_admins(subject, plain_message, html_message=html_message)

    def get_authorize_url(self):
        return self.auth.get_authorize_url()

    def save_credentials(self, auth_code):
        self._save_credentials(self.auth.get_credentials(auth_code))

    @classmethod
    def _save_credentials(cls, credentials: CredentialsType) -> None:
        """Save credentials to a file."""
        logger.info(f'Saving credentials in database')
        withings_settings = Settings.objects.first()
        withings_settings.token = pickle.dumps(credentials)
        withings_settings.save()

    @classmethod
    def _load_credentials(cls) -> CredentialsType:
        """Load credentials from a file."""
        logger.info(f'Using credentials from database')

        return cast(CredentialsType,
                    pickle.loads(Settings.objects.first().token))

    def import_data(self, date_from, date_to):
        assert self.api is not None
        assert self.api.user_get_device() is not None

        meas_result = self.api.measure_get_meas(
            startdate=date_from,
            enddate=date_to,
            # lastupdate=1601478000,
            lastupdate=None,
            category=MeasureGetMeasGroupCategory.REAL)

        api_to_django = {
            MeasureType.WEIGHT: 'weight',
            MeasureType.FAT_RATIO: 'fat_pct',
        }

        dict_meas = [
            {
                **{
                    api_to_django[measure.type]: float(
                        measure.value * pow(10, measure.unit))
                    for measure in grp.measures
                },
                'measure_date': grp.date.datetime
            }
            for grp in query_measure_groups(
                    meas_result,
                    with_measure_type=cast(Tuple, api_to_django.keys())
            )
        ]
        logger.debug(f'Values from Withings API: {dict_meas}')

        db_values = list(Measurement.objects.filter(
            scale=self.scale,
            measure_date__gte=date_from.datetime
        ).values('measure_date', *api_to_django.values()))
        logger.debug(f'Values from Django DB: {db_values}')

        results = {'add': 0, 'del': 0}
        for i in dict_meas + db_values:
            if i not in db_values:
                logger.info(f'Add to DB: {i}')
                Measurement.objects.create(
                    scale=self.scale,
                    **i
                )
                results['add'] += 1
            if i not in dict_meas:
                logger.info(f'Delete from DB: {i}')
                Measurement.objects.get(scale=self.scale, **i).delete()
                results['del'] += 1

        logger.info(f'Import results: {results["add"]} addition,'
                    f' {results["del"]} deletion')
