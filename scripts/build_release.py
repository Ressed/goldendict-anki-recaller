"""Build allowlisted archives without local settings, dependencies or study data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'


def build():
    DIST.mkdir(exist_ok=True)
    addon = DIST / 'goldendict-anki-recaller.ankiaddon'
    with zipfile.ZipFile(addon, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('__init__.py', 'matching.py', 'priority_queue.py', 'manifest.json'):
            archive.write(ROOT / 'addon' / name, name)
    paths = [ROOT / name for name in ('anki_lookup.py', 'config.example.json',
             'requirements.txt', 'README.md', 'CONTRIBUTING.md', '.gitignore')]
    for directory in ('goldendict_anki', 'addon', 'tests', 'scripts', 'docs'):
        paths.extend(path for path in (ROOT / directory).rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and 'user_files' not in path.parts
                     and path.suffix in ('.py', '.js', '.css', '.html', '.md', '.json', '.png'))
    paths.extend(ROOT / '.test-tools' / name for name in ('package.json', 'package-lock.json'))
    source = DIST / 'goldendict-anki-recaller-source.zip'
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, 'goldendict-anki-recaller/' + path.relative_to(ROOT).as_posix())
        archive.write(addon, 'goldendict-anki-recaller/dist/' + addon.name)
    print(addon)
    print(source)


if __name__ == '__main__':
    build()
