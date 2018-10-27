from multiprocessing.connection import Listener
from janome.tokenizer import Tokenizer
import sys
sys.path.extend([r'/home/fred/kukan/kukansite'])

import settings_prod as settings

tokenizer = Tokenizer()


with Listener(('localhost', settings.JANOME_PORT), authkey=settings.JANOME_KEY) as listener:
    # Looping here so that the clients / party goers can
    # always come back for more than a single request
    while True:
        with listener.accept() as conn:
            args = conn.recv()

            if args == b'stop server':
                print('Goodnight')
                break
            elif isinstance(args, list):
                # Very basic check, must be more secure in production
                conn.send(tokenizer.tokenize(args[0]))
            else:
                conn.send(b'Error')
