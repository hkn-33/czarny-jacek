# Building Czarny Jacek

How to turn the code into `CzarnyJacek.exe` and publish it. Windows only.

## 1. One-time setup

Install [Python 3.14](https://www.python.org/downloads/) (tick "Add python.exe to PATH"), then in the project folder:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pyinstaller
```

## 2. Check that it works

```
.venv\Scripts\python -m czarny_jacek.strategy
.venv\Scripts\python -m czarny_jacek.shoe
.venv\Scripts\python -m czarny_jacek.main
```

The first two print `strategy ok` and `shoe ok`. The last one opens the app.
`.venv\Scripts\python -m tests.test_samples` also works if you have the private `samples/` folder.

## 3. Build the .exe

```
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name CzarnyJacek --paths . --add-data "templates;templates" czarny_jacek/main.py
```

- Result: `dist\CzarnyJacek.exe` (~105 MB). It runs on any Windows PC without Python.
- `--add-data` packs `templates/` into the exe. Without it the app cannot read cards.
- `build\` and `CzarnyJacek.spec` are temporary; you can delete them.
- When run, the exe creates `captures\` next to itself (log and screenshots of each session).

## 4. Publish a new version

The exe is over GitHub's 100 MB file limit, so it goes to a Release, not into the repo.

```
git add -A
git commit -m "Describe the change"
git push
gh release create v0.2 dist\CzarnyJacek.exe --title "v0.2" --notes "What changed"
```

Bump the version number each time. Download link for others: the repo's **Releases** page.
