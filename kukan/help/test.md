### From the Terminal window

#### Dump fixtures

    python manage.py dumpdata kukan -o kukan\fixtures\full_kukan.json

#### Run the test server

    python manage.py testserver full_kukan auth

#### Run the tests

    python manage.py test kukan
