venv\Scripts\coverage-3.7.exe run --source='kukan' manage.py test kukan
venv\Scripts\coverage-3.7.exe report -m
venv\Scripts\coverage-3.7.exe html
"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" %1\htmlcov\index.html