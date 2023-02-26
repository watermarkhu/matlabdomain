

from sphinx.application import Sphinx
from pathlib import Path
import sys

cwd = Path(__file__).resolve().parent

app = Sphinx(
    srcdir = str(cwd),
    confdir = str(cwd),
    outdir = str(cwd / 'build'),
    doctreedir = str(cwd / '.doctrees'),
    buildername = 'html',
    confoverrides = dict(
        root_doc='index',
        matlab_src_dir=str(cwd.parent / 'tests' / 'test_data'),
    ),
    status = sys.stdout,
    warning = sys.stderr,
    freshenv = False,
    warningiserror = False,
    tags = None,
    verbosity = 1, 
    parallel = 0, 
    keep_going = False,
    pdb = False
)

app.build(force_all=True, filenames=[])
