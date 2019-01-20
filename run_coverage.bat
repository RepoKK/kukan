venv\Scripts\coverage-3.7.exe run --source=utils_django,kukan manage.py test
venv\Scripts\coverage-3.7.exe report -m
venv\Scripts\coverage-3.7.exe html
"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" %1\htmlcov\index.html