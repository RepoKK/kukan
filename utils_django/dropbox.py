import logging
import dropbox
from dropbox.files import WriteMode
from dropbox.exceptions import ApiError, AuthError
from django.conf import settings

logger = logging.getLogger(__name__)


def dropbox_api(token=None):
    try:
        dbx_api = dropbox.Dropbox(token or settings.DROPBOX_TOKEN)
        # Check that the access token is valid
        dbx_api.users_get_current_account()
        return dbx_api
    except AuthError:
        logger.error('Invalid access token; try re-generating an '
                     'access token from the app console on the web.')
        raise


def upload(local_file, destination, token=None):
    dbx = dropbox_api(token)
    with open(local_file, 'rb') as f:
        logger.info(f'Uploading {local_file} to Dropbox as '
                    f'{destination}...')
        try:
            dbx.files_upload(f.read(), destination,
                             mode=WriteMode('overwrite'))
        except ApiError as err:
            # This checks for the specific error where a user doesn't have
            # enough Dropbox space quota to upload this file
            if (err.error.is_path() and
                    err.error.get_path().reason.is_insufficient_space()):
                logger.error('Cannot back up; insufficient space.')
            elif err.user_message_text:
                logger.error(err.user_message_text)
            else:
                logger.error(err)


def download(source, local_file, token=None):
    dbx = dropbox_api(token)
    dbx.files_download_to_file(local_file, source, None)
