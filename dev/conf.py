# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
from datetime import datetime
import os

project = 'DEV'
copyright = f'{datetime.now().year}'
try: 
    author = os.getlogin()
except OSError:
    author = "UNKNOWN"
# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# Setup sphinx extensions
extensions = [
    'sphinx.ext.autodoc',        # Auto generation
    'sphinxcontrib.matlab',      # Parse matlab docstrings https://github.com/sphinx-contrib/matlabdomain
    'sphinxcontrib.mermaid',     
    'sphinx.ext.napoleon',       # For use of NumPy style docstrings https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html
    "sphinx.ext.mathjax",
    "sphinx.ext.todo",
    'sphinx.ext.todo',
    'sphinx_copybutton',
    'sphinx_design',
    'myst_parser',
]

templates_path = ['_templates']
exclude_patterns = ['.do_not_publish']
highlight_language = 'matlab'
todo_include_todos = True
# pygments_dark_style = "github-dark"
# pygments_style = "vs"

# -- Options for HTML output -------------------------------------------------

html_theme = 'furo'
# html_theme = 'alabaster'
# html_static_path = ['_static']

# -- Options for MATLAB parsing ----------------------------------------------
# https://github.com/sphinx-contrib/matlabdomain

primary_domain = 'mat'
matlab_keep_package_prefix = True
matlab_direct_search = True
matlab_relative_src_path = True
matlab_argument_docstrings = True

# -- Options for Napoleon ---------------------------------------------------- 
# https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html

napoleon_numpy_docstring = True

# -- Options for Autodoc ---------------------------------------------------- 
# https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html

autoclass_content = 'class'
autodoc_member_order = 'bysource'
add_module_names = False

autodoc_default_options = {
    'members': True,
    'show-inheritance': True
}