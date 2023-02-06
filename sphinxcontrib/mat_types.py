# -*- coding: utf-8 -*-
"""
    sphinxcontrib.mat_types
    ~~~~~~~~~~~~~~~~~~~~~~~

    Types for MATLAB.

    :copyright: Copyright 2014 Mark Mikofski
    :license: BSD, see LICENSE for details.
"""
from io import open  # for opening files with encoding in Python 2
import os
import sphinx.util
from copy import copy
from zipfile import ZipFile
from pygments.token import Token
from pygments.lexers.matlab import MatlabLexer as MatlabLexer
# from .mat_lexer import MatlabLexer as MatlabLexer
from .regex import code_preprocess
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Tuple, Generator


logger = sphinx.util.logging.getLogger('matlab-domain')

modules = {}
packages = {}

MAT_DOM = 'sphinxcontrib-matlabdomain'
__all__ = ['MatObject', 'MatModule', 'MatFunction', 'MatClass',  \
           'MatProperty', 'MatMethod', 'MatScript', 'MatException', \
           'MatModuleAnalyzer', 'MatApplication', 'MAT_DOM']

# XXX: Don't use `type()` or metaclasses. Not trivial to create metafunctions.
# XXX: Some special attributes **are** required even though `getter()` methods
# are also used.

# create some MATLAB objects
# TODO: +packages & @class folders
# TODO: subfunctions (not nested) and private folders/functions/classes
# TODO: script files

class MatObject(object):
    """
    Base MATLAB object to which all others are subclassed.

    :param name: Name of MATLAB object.
    :type name: str

    MATLAB objects can be :class:`MatModule`, :class:`MatFunction`,
    :class:`MatApplication` or :class:`MatClass`.
    :class:`MatModule` are just folders that define a psuedo
    namespace for :class:`MatFunction`, :class:`MatApplication`
    and :class:`MatClass` in that folder.
    :class:`MatFunction` and :class:`MatClass` must begin with either
    ``function`` or ``classdef`` keywords.
    :class:`MatApplication` must be a ``.mlapp`` file.
    """
    basedir = None
    encoding = None
    sphinx_env = None
    sphinx_app = None

    def __init__(self, name):
        #: name of MATLAB object
        self.name = name

    @property
    def __name__(self):
        return self.name

    def __repr__(self):
        # __str__() method not required, if not given, then __repr__() used
        return '<%s: "%s">' % (self.__class__.__name__, self.name)

    def getter(self, name, *defargs):
        if name == '__name__':
            return self.__name__
        elif len(defargs) == 0:
            warn_msg = '[%s] WARNING Attribute "%s" was not found in %s.'
            logger.debug(warn_msg, MAT_DOM, name, self)
            return None
        elif len(defargs) == 1:
            return defargs[0]
        else:
            return defargs

    @staticmethod
    def matlabify(objname):
        """
        Makes a MatObject.

        :param objname: Name of object to matlabify without file extension.
        :type objname: str

        Assumes that object is contained in a folder described by a namespace
        composed of modules and packages connected by dots, and that the top-
        level module or package is in the Sphinx config value
        ``matlab_src_dir`` which is stored locally as
        :attr:`MatObject.basedir`. For example:
        ``my_project.my_package.sub_pkg.MyClass`` represents either a folder
        ``basedir/my_project/my_package/sub_pkg/MyClass`` or an mfile
        ``basedir/my_project/my_package/sub_pkg/ClassExample.m``. If there is both a
        folder and an mfile with the same name, the folder takes precedence
        over the mfile.
        """
        # no object name given
        if not objname:
            return None
        # matlab modules are really packages
        package = objname  # for packages it's namespace of __init__.py
        # convert namespace to path
        objname = objname.replace('.', os.sep)  # objname may have dots
        # separate path from file/folder name
        path, name = os.path.split(objname)
        # make a full path out of basedir and objname
        fullpath = os.path.join(MatObject.basedir, objname)  # objname fullpath
        # package folders imported over mfile with same name
        if os.path.isdir(fullpath):
            mod = modules.get(package)
            if mod:
                msg = '[%s] mod %s already loaded.'
                logger.debug(msg, MAT_DOM, package)
                return mod
            else:
                msg = '[%s] matlabify %s from\n\t%s.'
                logger.debug(msg, MAT_DOM, package, fullpath)
                return MatModule(name, fullpath, package)  # import package
        elif os.path.isfile(fullpath + '.m'):
            mfile = fullpath + '.m'
            msg = '[%s] matlabify %s from\n\t%s.'
            logger.debug(msg, MAT_DOM, package, mfile)
            return MatObject.parse_mfile(mfile, name, path, MatObject.encoding)  # parse mfile
        elif os.path.isfile(fullpath + '.mlapp'):
            mlappfile = fullpath + '.mlapp'
            msg = '[%s] matlabify %s from\n\t%s.'
            logger.debug(msg, MAT_DOM, package, mlappfile)
            return MatObject.parse_mlappfile(mlappfile, name, path)
        return None

    @staticmethod
    def parse_mfile(mfile, name, path, encoding=None):
        """
        Use Pygments to parse mfile to determine type: function or class.

        :param mfile: Full path of mfile.
        :type mfile: str
        :param name: Name of :class:`MatObject`.
        :type name: str
        :param path: Path of module containing :class:`MatObject`.
        :type path: str
        :param encoding: Encoding of the Matlab file to load (default = utf-8)
        :type encoding: str
        :returns: :class:`MatObject` that represents the type of mfile.

        Assumes that the first token in the file is either one of the keywords:
        "classdef" or "function" otherwise it is assumed to be a script.

        File encoding can be set using sphinx config ``matlab_src_encoding``
        Default behaviour : replaces parsing errors with ? chars
        """
        # use Pygments to parse mfile to determine type: function/classdef
        # read mfile code
        if encoding is None:
            encoding = 'utf-8'

        modname = path.replace(os.sep, '.')  # module name

        with open(mfile, 'r', encoding=encoding, errors='replace') as file:
            full_code = file.read().replace('\r\n', '\n')

        # Preprocessing the codestring
        code = code_preprocess(full_code)
        tks = MatlabLexer().get_tokens(code)
        token = next(tks)

        if token == (Token.Keyword, 'classdef') :
            logger.debug('[%s] parsing classdef %s from %s.', MAT_DOM, name, modname)
            return MatClass(name, modname, tks)
        elif token == (Token.Keyword, 'function'):
            logger.debug('[%s] parsing function %s from %s.', MAT_DOM, name, modname)
            return MatFunction(name, modname, tks)
        else:
            # it's a script file retoken with header comment
            tks = MatlabLexer().get_tokens(full_code)
            return MatScript(name, modname, tks)


    @staticmethod
    def parse_mlappfile(mlappfile, name, path):
        """
        Uses ZipFile to read the metadata/appMetadata.xml file and
        the metadata/coreProperties.xml file description tags.
        Parses XML content using ElementTree.

        :param mlappfile: Full path of ``.mlapp`` file.
        :type mlappfile: str
        :param name: Name of :class:`MatApplication`.
        :type name: str
        :param path: Path of module containing :class:`MatApplication`.
        :type path: str
        :returns: :class:`MatApplication` representing the application.
        """

        # TODO: We could use this method to parse other matlab binaries

        # Read contents of meta-data file
        # This might change in different Matlab versions
        with ZipFile(mlappfile, 'r') as mlapp:
            meta = ET.fromstring(mlapp.read('metadata/appMetadata.xml'))
            core = ET.fromstring(mlapp.read('metadata/coreProperties.xml'))

        metaNs = { 'ns' : "http://schemas.mathworks.com/appDesigner/app/2017/appMetadata" }
        coreNs = {
                'cp': "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                'dc': "http://purl.org/dc/elements/1.1/",
                'dcmitype': "http://purl.org/dc/dcmitype/",
                'dcterms': "http://purl.org/dc/terms/",
                'xsi': "http://www.w3.org/2001/XMLSchema-instance"
                }

        coreDesc = core.find('dc:description', coreNs)
        metaDesc = meta.find('ns:description', metaNs)

        doc = []
        if coreDesc is not None:
            doc.append(coreDesc.text)
        if metaDesc is not None:
            doc.append(metaDesc.text)
        docstring = '\n\n'.join(doc)

        modname = path.replace(os.sep, '.')  # module name

        return MatApplication(name, modname, docstring)


# TODO: get docstring and __all__ from contents.m if exists
class MatModule(MatObject):
    """
    All MATLAB modules are packages. A package is a folder that serves as the
    namespace for any :class:`MatObjects` in the package folder. Sphinx will
    treats objects without a namespace as builtins, so all MATLAB projects
    should be packaged in a folder so that they will have a namespace. This
    can also be accomplished by using the MATLAB +folder package scheme.

    :param name: Name of :class:`MatObject`.
    :type name: str
    :param path: Path of folder containing :class:`MatObject`.
    :type path: str
    """
    def __init__(self, name, path, package):
        super(MatModule, self).__init__(name)
        #: Path to module on disk, path to package's __init__.py
        self.path = path
        #: name of package (full path from basedir to module)
        self.package = package
        # add module to system dictionary
        modules[package] = self

    def safe_getmembers(self):
        results = []
        for key in os.listdir(self.path):
            # make full path
            path = os.path.join(self.path, key)
            # don't visit vcs directories
            if os.path.isdir(path) and key in ['.git', '.hg', '.svn', '.bzr']:
                continue
            # only visit mfiles
            if os.path.isfile(path) and not key.endswith('.m'):
                continue
            # trim file extension
            if os.path.isfile(path):
                key, _ = os.path.splitext(key)
            if not results or key not in list(zip(*results))[0]:
                value = self.getter(key, None)
                if value:
                    results.append((key, value))
        results.sort()
        return results

    @property
    def __doc__(self):
        return None

    @property
    def __all__(self):
        results = self.safe_getmembers()
        if results:
            results = list(zip(*self.safe_getmembers()))[0]
        return results

    @property
    def __path__(self):
        return [self.path]

    @property
    def __file__(self):
        return self.path

    @property
    def __package__(self):
        return self.package

    def getter(self, name, *defargs):
        """
        :class:`MatModule` ``getter`` method to get attributes.
        """
        if name == '__name__':
            return self.__name__
        elif name == '__doc__':
            return self.__doc__
        elif name == '__all__':
            return self.__all__
        elif name == '__file__':
            return self.__file__
        elif name == '__path__':
            return self.__path__
        elif name == '__package__':
            return self.__package__
        elif name == '__module__':
            msg = '[%s] mod %s is a package does not have __module__.'
            logger.debug(msg, MAT_DOM, self)
            return None
        else:
            if hasattr(self, name):
                msg = '[%s] mod %s already has attr %s.'
                logger.debug(msg, MAT_DOM, self, name)
                return getattr(self, name)
            attr = MatObject.matlabify('.'.join([self.package, name]))
            if attr:
                setattr(self, name, attr)
                msg = '[%s] attr %s imported from mod %s.'
                logger.debug(msg, MAT_DOM, name, self)
                return attr
            else:
                super().getter(name, *defargs)


def tks_next(tks: Generator, skip_newline: bool = False, skip_semicolon: bool = True, skip_comment: bool = True):
    """Iterator for the next token. Returns None if the iterator is empty."""
    token = next(tks, None)
    while token:
        if any(
            [
                (token[0] is Token.Text.Whitespace and (skip_newline or '\n' not in token[1])),
                (token == (Token.Punctuation, ';') and skip_semicolon), 
                (token[0] is Token.Comment and skip_comment)
            ]
        ):
            token = next(tks, None)
        else:
            break
    return token


def tks_code_literal(tks: Generator, token: tuple = None):
    """ 
    Returns a literal codestring until 
    1) the literal ends with ','
    2) there is a newline character '\n'
    3) there is a comment
    """
    closing_punctionations = {'(': ')', '[': ']', '{': '}'}
    expected_close = []
    literal = ''

    if token is None:
        token = tks_next(tks, skip_semicolon=False, skip_comment=False)

    statement_endings = [','] + list(closing_punctionations.values())
    while expected_close or not any(
        [
            token[0] is Token.Punctuation and token[1] in statement_endings, token[0] is Token.Text.Whitespace and
            '\n' in token[1], token[0] is Token.Comment
        ]
    ):
        if token[0] is Token.Punctuation and token[1] in closing_punctionations.keys():
            # literal has a backet opener, thus a corresponding close is expected
            expected_close.append(closing_punctionations[token[1]])
        elif token[0] is Token.Punctuation and token[1] in closing_punctionations.values():
            # All closing brackets must follow the expected order.
            if token[1] != expected_close.pop():
                raise IndexError

        # Add to literal, which can have most types
        literal += token[1]

        token = tks_next(tks, skip_semicolon=False, skip_comment=False)

    return literal, token


def tks_docstring(tks: Generator, token: tuple, header: str = ''):
    """
    The token parser for docstrings.

    A docstring is considered consecutive lines of comments that start at the same location on line. 
    Any consistent leading spaces after the comment marker % is removed. 
    """
    indent = None
    doc_lines = []
    while token and token[0] is Token.Comment:
        comment = token[1].lstrip('%').rstrip()
        doc_lines.append(comment)
        token = tks_next(tks, skip_comment=False)
        if token[0] is Token.Text.Whitespace and '\n' in token[1]:
            line_indent = token[1].split('\n')[-1]
            if indent is not None and indent != line_indent:
                token = tks_next(tks, skip_newline=True, skip_comment=True)
                break
            indent = token[1].split('\n')[-1]
            token = tks_next(tks, skip_comment=False)

    # Join string and remove leading spaces
    if doc_lines:
        num_leading_space = 0
        while True:
            if not all([line[num_leading_space] == ' ' for line in doc_lines if line]):
                break
            num_leading_space += 1
        docstring = '\n'.join(
            [line[num_leading_space:] if len(line) > num_leading_space + 1 else '' for line in doc_lines]
        )
        if header:
            docstring = f"{header} {docstring}"
        return docstring, token


class propertyLine(object):
    """
    The token parser for properties.

        Prop (1,1) propType {Validators} = default_value() # Description

    The 'Prop' token is already removed from the token list and used for the constructor. 
    """
    def __init__(self, name: str, attrs: dict = {}) -> None:
        self.name = name
        self.attrs = attrs

    def parse_tokens(self, tks: Generator):
        """
        Parses a list of tokens starting from after the property name. 
        """
        token = tks_next(tks, skip_comment=False)

        # Property size
        if token == (Token.Punctuation, '('):
            self.size = []
            token = tks_next(tks)
            while token and token != (Token.Punctuation, ')'):
                if token[0] is Token.Literal.Number.Integer:
                    self.size.append(int(token[1]))
                token = tks_next(tks)
        else:
            self.size = None

        token = tks_next(tks, skip_comment=False)

        # property type
        if token[0] is Token.Name.Builtin or token[0] is Token.Name:
            self.type = token[1]
            token = tks_next(tks, skip_comment=False)
        else:
            self.type = None

        # validators
        if token == (Token.Punctuation, '{'):
            self.vldtrs = []
            while token and token != (Token.Punctuation, '}'):
                try:
                    validator, token = tks_code_literal(tks)
                    self.vldtrs.append(validator)
                except IndexError:
                    msg = f'[{MAT_DOM}] Parsing failed in {self.__class__.__name__} {self.name}.'
                    msg += ' Are you sure the validator statement is correct?'
                    logger.warning(msg)
                    raise IndexError
            else:
                token = tks_next(tks, skip_comment=False)
        else:
            self.vldtrs = None

        # Default value
        if token == (Token.Punctuation, '='):
            self.default, token = tks_code_literal(tks)
        else:
            self.default = None

        # Direct docstring
        self.docstring = token[1].strip('% ') if token[0] is Token.Comment else ''
        token = tks_next(tks, skip_newline=True, skip_comment=False)

        # Newline docstring
        if token[0] is Token.Comment:
            docstring, token = tks_docstring(tks, token, self.docstring)
            self.docstring = ' '.join(docstring.split('\n'))

        return token

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} of {self.name}>'

    def to_dict(self):
        return {
            'name': self.name,
            'size': self.size,
            'type': self.type,
            'vldtrs': self.vldtrs,
            'default': self.default,
            'docstring': self.docstring,
            'attrs': self.attrs
        }


class argumentLine(propertyLine):
    pass


class attributeBlock(ABC):
    '''
    Abstract type for block objects that has (MATLAB) attribute descriptions. 

    Extensions to the abstract type must define all possible attributes for the block in the (python) class
    attribute `attribute_types`, a dictionary containing key-value pairs for the (MATLAB) attribute names 
    and their value types. 
    '''
    attribute_types = {}

    def __init__(self, tks: Generator):

        self.attributes = {}

        token = tks_next(tks)

        # Get attributes
        if token == (Token.Punctuation, '('):
            token = tks_next(tks)
            while token and token != (Token.Punctuation, ')'):
                if token[0] is Token.Name:
                    if token[1] in self.attribute_types.keys():
                        if self.attribute_types[token[1]] is bool:
                            self.attributes[token[1]] = True
                        elif self.attribute_types[token[1]] is list:
                            pass
                    else:
                        msg = f'[{MAT_DOM}] Unsupported attribute {token[0]} for {self.__class__.__name__}.'
                        logger.warning(msg)
                token = tks_next(tks)


class functionArgumentsBlock(attributeBlock):
    '''
    Arguments block for functions.

    Loops over the items in a arguments block in a function and parses each argument 
    with an argumentLine object. 
    '''
    attribute_types = {"Input": bool, "Output": bool, "Repeating": bool}

    def __init__(self, tks: Generator, args: list, retv: list):
        super().__init__(tks)
        if self.attributes.get('Input', False) or not self.attributes.get('Output', False):
            self.arg_list, self.type = args, 'Input'
        else:
            self.arg_list, self.type = retv, 'Output'
        self.repeating = self.attributes.get('Repeating', False)

        # Get arguments
        self.arguments = []
        self.parse_tokens(tks)

    def parse_tokens(self, tks: Generator):
        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            if token[0] is Token.Name:
                if token[1] in self.arg_list:
                    argument = argumentLine(token[1], self.attributes)
                    token = argument.parse_tokens(tks)
                    self.arguments.append(argument)
                else:
                    msg = f'[{MAT_DOM}] Parsing failed in {self}.'
                    msg += f' {self.type} argument "{token[1]}" is unknown.'
                    logger.warning(msg)
                    raise IndexError
            else:
                token = tks_next(tks, skip_newline=True)

    def __repr__(self) -> str:
        return f'<argumentsBlock [{", ".join([arg.name for arg in self.arguments])}]>'


class methodArgumentsBlock(functionArgumentsBlock):
    '''
    Arguments block for class method.

    Inherits from functionArgumentsBlock, but now skips the first argument as it is the class
    object itself.
    '''
    def parse_tokens(self, tks: Generator):
        first_obj_arg = True
        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            if token[0] is Token.Name:
                if first_obj_arg:
                    first_obj_arg = False
                    continue
                if token[1] in self.arg_list:
                    arg = token[1]
                    argument = argumentLine(token[1], self.attributes)
                    token = argument.parse_tokens(tks)
                    self.arguments.append(argument)
                else:
                    msg = f'[{MAT_DOM}] Parsing failed in {self}.'
                    msg += f' {self.type} argument "{token[1]}" is unknown.'
                    logger.warning(msg)
                    raise IndexError
            else:
                token = tks_next(tks, skip_newline=True)


class MatFunction(MatObject):
    """
    A MATLAB function.

    :param name: Name of :class:`MatObject`.
    :type name: str
    :param modname: Name of folder containing :class:`MatObject`.
    :type modname: str
    :param tokens: List of tokens parsed from mfile by Pygments.
    :type tokens: list
    """

    # parse function signature
    # =====================================================================
    # function [output] = name(inputs)
    # % docstring
    # arguments (attributes)
    #   argument (size) type {validators} = default # description
    # end
    # =====================================================================

    # MATLAB keywords that increment keyword-end pair count
    mat_kws = list(zip((Token.Keyword, ) * 7, ('arguments', 'for', 'if', 'switch', 'try', 'while', 'parfor')))

    def warning_msg(self, message: str = ''):
        msg = f'[{MAT_DOM}] Parsing failed in {self.module}.{self.name}. {message}'
        logger.warning(msg)

    def __init__(self, name: str, modname: str, tks: Generator):
        super().__init__(name)

        self.module = modname  #: Path of folder containing :class:`MatObject`.
        self.tokens = tks  #: List of tokens parsed from mfile by Pygments.
        self.docstring = ''  #: docstring
        self.retv = []  #: output args
        self.retv_va = []
        self.args = []  #: input args
        self.args_va = []

        # =====================================================================

        token = tks_next(tks)

        # =====================================================================
        # Return values and function name

        if token[0] is Token.Text:
            # Single return value
            self.retv = [token[1].strip('[ ]')]
            token = tks_next(tks)

            if token != (Token.Punctuation, '='):
                self.warning('Expected "=".')
                return

            token = tks_next(tks)
            if token[0] is Token.Name.Function:
                func_name = token[1]
            else:
                self.warning()
                return

        elif token[0] is Token.Name.Function:
            # Multiple return values or no return values
            ret_func = token[1].split('=')
            if len(ret_func) == 1:
                # No return values
                func_name = ret_func[0].strip()
            else:
                # Multiple return values
                self.retv = [ret.strip() for ret in ret_func[0].strip('[ ]').split(',')]
                func_name = ret_func[1].strip()
        else:
            self.warning()
            return

        if func_name != self.name:
            if isinstance(self, MatMethod):  # QUESTION what does this mean?
                self.name = func_name
            else:
                self.warning(f'Expected "{name}" in module "{modname}", found "{func_name}".')

        # =====================================================================
        # input args
        token = tks_next(tks)

        if token == (Token.Punctuation, '('):
            token = tks_next(tks)
            if token[0] is Token.Text:
                self.args = [arg.strip() for arg in token[1].split(',')]
                token = tks_next(tks)
            else:
                self.warning()
                return

            if token == (Token.Punctuation, ')'):
                token = tks_next(tks)
            else:
                self.warning('Expected ")".')
                return

        # =====================================================================
        # docstring
        token = tks_next(tks, skip_newline=True, skip_comment=False)
        self.docstring, token = tks_docstring(tks, token)

        # =====================================================================
        # argument validation
        while token and token == (Token.Name.Builtin, 'arguments'):  
            # TODO check if argument blocks must be concatenating

            argblock = functionArgumentsBlock(tks, self.args, self.retv)
            if argblock.type == 'Input':
                self.args_va += argblock.arguments
            else:
                self.retv_va += argblock.arguments

            token = tks_next(tks, skip_newline=True)

        if self.args_va and (
            len(self.args) != len(self.args_va) or set(self.args) != set([arg.name for arg in self.args_va])
        ):
            msg = f'[{MAT_DOM}] Parsing failed in input arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)
        if self.retv_va and (
            len(self.retv) != len(self.retv_va) or set(self.retv) != set([arg.name for arg in self.retv_va])
        ):
            msg = f'[{MAT_DOM}] Parsing failed in output arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)

        # =====================================================================
        # Remainder of function is not checked, nothing of interest

        self.rem_tks = list(tks)  # save extra tokens # TODO remove this altogether?

    @property
    def __doc__(self):
        return self.docstring

    @property
    def __module__(self):
        return self.module

    def getter(self, name, *defargs):
        if name == '__name__':
            return self.__name__
        elif name == '__doc__':
            return self.__doc__
        elif name == '__module__':
            return self.__module__
        else:
            super().getter(name, *defargs)


class MatMixin(object):
    """
    Methods to comparing and manipulating tokens in :class:`MatFunction` and
    :class:`MatClass`.
    """
    def _tk_eq(self, idx, token):
        """
        Returns ``True`` if token keys are the same and values are equal.
        :param idx: Index of token in :class:`MatObject`.
        :type idx: int
        :param token: Comparison token.
        :type token: tuple
        """
        return (self.tokens[idx][0] is token[0] and
                self.tokens[idx][1] == token[1])

    def _tk_ne(self, idx, token):
        """
        Returns ``True`` if token keys are not the same or values are not
        equal.
        :param idx: Index of token in :class:`MatObject`.
        :type idx: int
        :param token: Comparison token.
        :type token: tuple
        """
        return (self.tokens[idx][0] is not token[0] or
                self.tokens[idx][1] != token[1])

    def _eotk(self, idx):
        """
        Returns ``True`` if end of tokens is reached.
        """
        return idx >= len(self.tokens)

    def _blanks(self, idx):
        """
        Returns number of blank text tokens.
        :param idx: Token index.
        :type idx: int
        """
        # idx0 = idx  # original index
        # while self._tk_eq(idx, (Token.Text, ' ')): idx += 1
        # return idx - idx0  # blanks
        return self._indent(idx)

    def _whitespace(self, idx):
        """
        Returns number of whitespaces text tokens, including blanks, newline
        and tabs.
        :param idx: Token index.
        :type idx: int
        """
        idx0 = idx  # original index
        while ((self.tokens[idx][0] is Token.Text or
                self.tokens[idx][0] is Token.Text.Whitespace) and
               self.tokens[idx][1] in [' ', '\n', '\t']):
            idx += 1
        return idx - idx0  # whitespace

    def _indent(self, idx):
        """
        Returns indentation tabs or spaces. No indentation is zero.
        :param idx: Token index.
        :type idx: int
        """
        idx0 = idx  # original index
        while (self.tokens[idx][0] is Token.Text and
               self.tokens[idx][1] in [' ', '\t']):
            idx += 1
        return idx - idx0  # indentation

    def _is_newline(self, idx):
        """ Returns true if the token at index is a newline """
        return self.tokens[idx][0] in (Token.Text, Token.Text.Whitespace) and self.tokens[idx][1]=='\n'


class MatClass(MatMixin, MatObject):
    """
    A MATLAB class definition.

    :param name: Name of :class:`MatObject`.
    :type name: str
    :param path: Path of folder containing :class:`MatObject`.
    :type path: str
    :param tokens: List of tokens parsed from mfile by Pygments.
    :type tokens: list
    """
    #: dictionary of MATLAB class "attributes"
    # http://www.mathworks.com/help/matlab/matlab_oop/class-attributes.html
    # https://mathworks.com/help/matlab/matlab_oop/property-attributes.html
    # https://se.mathworks.com/help/matlab/ref/matlab.unittest.testcase-class.html
    cls_attr_types = {'Abstract': bool, 'AllowedSubclasses': list,
                      'ConstructOnLoad': bool, 'HandleCompatible': bool,
                      'Hidden': bool, 'InferiorClasses': list, 'Sealed': bool}

    prop_attr_types = {'AbortSet': bool, 'Abstract': bool, 'Access': list,
                       'Constant': bool, 'Dependent': bool, 'GetAccess': list,
                       'GetObservable': bool, 'Hidden': bool,
                       'NonCopyable': bool, 'SetAccess': list,
                       'SetObservable': bool, 'Transient': bool,
                       'ClassSetupParameter': bool,
                       'MethodSetupParameter': bool, 'TestParameter': bool}
    meth_attr_types = {'Abstract': bool, 'Access': list, 'Hidden': bool,
                       'Sealed': list, 'Static': bool, 'Test': bool,
                       'TestClassSetup': bool, 'TestMethodSetup': bool,
                       'TestClassTeardown': bool, 'TestMethodTeardown': bool,
                       'ParameterCombination': bool}

    def __init__(self, name, modname, tokens):
        super().__init__(name)
        #: Path of folder containing :class:`MatObject`.
        self.module = modname
        #: List of tokens parsed from mfile by Pygments.
        self.tokens = tokens
        #: dictionary of class attributes
        self.attrs = {}
        #: list of class superclasses
        self.bases = []
        #: docstring
        self.docstring = ''
        #: dictionary of class properties
        self.properties = {}
        #: dictionary of class methods
        self.methods = {}
        #: remaining tokens after main class definition is parsed
        self.rem_tks = None
        # =====================================================================
        # parse tokens
        # TODO: use generator and next() instead of stepping index!
        try:
            # Skip classdef token - already checked in MatObject.parse_mfile
            idx = 1  # token index

            # class "attributes"
            self.attrs, idx = self.attributes(idx, MatClass.cls_attr_types)
            # =====================================================================
            # classname
            idx += self._blanks(idx)  # skip blanks
            if self._tk_ne(idx, (Token.Name, self.name)):
                msg = '[sphinxcontrib-matlabdomain] Unexpected class name: "%s".' % self.tokens[idx][1]
                msg += ' Expected "{0}" in "{1}.{0}".'.format(name, modname)
                logger.warning(msg)
            idx += 1
            idx += self._blanks(idx)  # skip blanks
            # =====================================================================
            # super classes
            if self._tk_eq(idx, (Token.Operator, '<')):
                idx += 1
                # newline terminates superclasses
                while not self._is_newline(idx):
                    idx += self._blanks(idx)  # skip blanks
                    # concatenate base name
                    base_name = ''
                    while not self._whitespace(idx):
                        base_name += self.tokens[idx][1]
                        idx += 1
                    # If it's a newline, we are done parsing.
                    if not self._is_newline(idx):
                        idx += 1
                    if base_name:
                        self.bases.append(base_name)
                    idx += self._blanks(idx)  # skip blanks
                    # continue to next super class separated by &
                    if self._tk_eq(idx, (Token.Operator, '&')):
                        idx += 1
                idx += 1  # end of super classes
            # newline terminates classdef signature
            elif self._is_newline(idx):
                idx += 1  # end of classdef signature
            # =====================================================================
            # docstring
            idx += self._indent(idx)  # calculation indentation
            # concatenate docstring
            while self.tokens[idx][0] is Token.Comment:
                self.docstring += self.tokens[idx][1].lstrip('%')
                idx += 1
                # append newline to docstring
                if self._is_newline(idx):
                    self.docstring += self.tokens[idx][1]
                    idx += 1
                # skip tab
                indent = self._indent(idx)  # calculation indentation
                idx += indent
        # =====================================================================
        # properties & methods blocks
        # loop over code body searching for blocks until end of class
            while self._tk_ne(idx, (Token.Keyword, 'end')):
                # skip comments and whitespace
                while (self._whitespace(idx) or
                       self.tokens[idx][0] is Token.Comment):
                    whitespace = self._whitespace(idx)
                    if whitespace:
                        idx += whitespace
                    else:
                        idx += 1
                # =================================================================
                # properties blocks
                if self._tk_eq(idx, (Token.Keyword, 'properties')):
                    prop_name = ''
                    idx += 1
                    # property "attributes"
                    attr_dict, idx = self.attributes(idx, MatClass.prop_attr_types)
                    # Token.Keyword: "end" terminates properties & methods block
                    while self._tk_ne(idx, (Token.Keyword, 'end')):
                        # skip whitespace
                        while self._whitespace(idx):
                            whitespace = self._whitespace(idx)
                            if whitespace:
                                idx += whitespace
                            else:
                                idx += 1

                        # =========================================================
                        # long docstring before property
                        if self.tokens[idx][0] is Token.Comment:
                            # docstring
                            docstring = ''

                            # Collect comment lines
                            while self.tokens[idx][0] is Token.Comment:
                                docstring += self.tokens[idx][1].lstrip('%')
                                idx += 1
                                idx += self._blanks(idx)

                                try:
                                    # Check if end of line was reached
                                    if self._is_newline(idx):
                                        docstring += '\n'
                                        idx += 1
                                        idx += self._blanks(idx)

                                    # Check if variable name is next
                                    if self.tokens[idx][0] is Token.Name:
                                        prop_name = self.tokens[idx][1]
                                        self.properties[prop_name] = {'attrs': attr_dict}
                                        self.properties[prop_name]['docstring'] = docstring
                                        break

                                    # If there is an empty line at the end of
                                    # the comment: discard it
                                    elif self._is_newline(idx):
                                        docstring = ''
                                        idx += self._whitespace(idx)
                                        break

                                except IndexError:
                                    # EOF reached, quit gracefully
                                    break

                        # with "%:" directive trumps docstring after property
                        if self.tokens[idx][0] is Token.Name:
                            prop_name = self.tokens[idx][1]
                            idx += 1
                            # Initialize property if it was not already done
                            if not prop_name in self.properties.keys():
                                self.properties[prop_name] = {'attrs': attr_dict}

                            # skip size, class and functions specifiers
                            # TODO: Parse old and new style property extras
                            while self._tk_eq(idx, (Token.Punctuation, '@')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '(')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ')')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ',')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ':')) or \
                                  self.tokens[idx][0] == Token.Literal.Number.Integer or \
                                  self._tk_eq(idx, (Token.Punctuation, '{')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '}')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '.')) or \
                                  self.tokens[idx][0] == Token.Literal.String or \
                                  self.tokens[idx][0] == Token.Name or \
                                  self.tokens[idx][0] == Token.Text:
                                idx += 1

                            if self._tk_eq(idx, (Token.Punctuation, ';')):
                                continue

                        # subtype of Name EG Name.Builtin used as Name
                        elif self.tokens[idx][0] in Token.Name.subtypes:  # @UndefinedVariable

                            prop_name = self.tokens[idx][1]
                            warn_msg = ' '.join(['[%s] WARNING %s.%s.%s is',
                                                 'a Builtin Name'])
                            logger.debug(warn_msg, MAT_DOM, self.module, self.name, prop_name)
                            self.properties[prop_name] = {'attrs': attr_dict}
                            idx += 1

                            # skip size, class and functions specifiers
                            # TODO: Parse old and new style property extras
                            while self._tk_eq(idx, (Token.Punctuation, '@')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '(')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ')')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ',')) or \
                                  self._tk_eq(idx, (Token.Punctuation, ':')) or \
                                  self.tokens[idx][0] == Token.Literal.Number.Integer or \
                                  self._tk_eq(idx, (Token.Punctuation, '{')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '}')) or \
                                  self._tk_eq(idx, (Token.Punctuation, '.')) or \
                                  self.tokens[idx][0] == Token.Literal.String or \
                                  self.tokens[idx][0] == Token.Name or \
                                  self.tokens[idx][0] == Token.Text:
                                idx += 1

                            if self._tk_eq(idx, (Token.Punctuation, ';')):
                                continue

                        elif self._tk_eq(idx, (Token.Keyword, 'end')):
                            idx += 1
                            break
                        # skip semicolon after property name, but no default
                        elif self._tk_eq(idx, (Token.Punctuation, ';')):
                            idx += 1
                            # A comment might come after semi-colon
                            idx += self._blanks(idx)
                            if self._is_newline(idx):
                                idx += 1
                                # Property definition is finished; add missing values
                                if 'default' not in self.properties[prop_name].keys():
                                    self.properties[prop_name]['default'] = None
                                if 'docstring' not in self.properties[prop_name].keys():
                                    self.properties[prop_name]['docstring'] = None

                                continue
                            elif self.tokens[idx][0] is Token.Comment:
                                docstring = self.tokens[idx][1].lstrip('%')
                                docstring += '\n'
                                self.properties[prop_name]['docstring'] = docstring
                                idx += 1
                        else:
                            msg = '[sphinxcontrib-matlabdomain] Expected property in %s.%s - got %s'
                            logger.warning(msg, self.module, self.name, str(self.tokens[idx]))
                            return
                        idx += self._blanks(idx)  # skip blanks
                        # =========================================================
                        # defaults
                        default = {'default': None}
                        if self._tk_eq(idx, (Token.Punctuation, '=')):
                            idx += 1
                            idx += self._blanks(idx)  # skip blanks
                            # concatenate default value until newline or comment
                            default = ''
                            punc_ctr = 0  # punctuation placeholder
                            # keep reading until newline or comment
                            # only if all punctuation pairs are closed
                            # and comment is **not** continuation ellipsis
                            while ((not self._is_newline(idx) and
                                    self.tokens[idx][0] is not Token.Comment) or
                                   punc_ctr > 0 or
                                   (self.tokens[idx][0] is Token.Comment and
                                    self.tokens[idx][1].startswith('...'))):
                                token = self.tokens[idx]
                                # default has an array spanning multiple lines
                                if (token in list(zip((Token.Punctuation,) * 3,
                                    ('(', '{', '[')))):
                                    punc_ctr += 1  # increment punctuation counter
                                # look for end of array
                                elif (token in list(zip((Token.Punctuation,) * 3,
                                           (')', '}', ']')))):
                                    punc_ctr -= 1  # decrement punctuation counter
                                # Pygments treats continuation ellipsis as comments
                                # text from ellipsis until newline is in token
                                elif (token[0] is Token.Comment and
                                      token[1].startswith('...')):
                                    idx += 1  # skip ellipsis comments
                                    # include newline which should follow comment
                                    if self._is_newline(idx):
                                        default += '\n'
                                        idx += 1
                                    continue
                                elif self._is_newline(idx - 1):
                                    idx += self._blanks(idx)
                                    continue
                                default += token[1]
                                idx += 1
                            if self.tokens[idx][0] is not Token.Comment:
                                idx += 1
                            if default:
                                default = {'default': default.rstrip('; ')}
                        self.properties[prop_name].update(default)
                        # =========================================================
                        # docstring
                        if 'docstring' not in self.properties[prop_name].keys():
                            docstring = {'docstring': None}
                            if self.tokens[idx][0] is Token.Comment:
                                docstring['docstring'] = \
                                    self.tokens[idx][1].lstrip('%')
                                idx += 1
                            self.properties[prop_name].update(docstring)
                        elif self.tokens[idx][0] is Token.Comment:
                            # skip this comment
                            idx += 1

                        idx += self._whitespace(idx)
                    idx += 1
                # =================================================================
                # method blocks
                if self._tk_eq(idx, (Token.Keyword, 'methods')):
                    idx += 1
                    # method "attributes"
                    attr_dict, idx = self.attributes(idx, MatClass.meth_attr_types)
                    # Token.Keyword: "end" terminates properties & methods block
                    while self._tk_ne(idx, (Token.Keyword, 'end')):
                        # skip comments and whitespace
                        while (self._whitespace(idx) or
                               self.tokens[idx][0] is Token.Comment):
                            whitespace = self._whitespace(idx)
                            if whitespace:
                                idx += whitespace
                            else:
                                idx += 1
                        # skip methods defined in other files
                        meth_tk = self.tokens[idx]
                        if (meth_tk[0] is Token.Name or
                            meth_tk[0] is Token.Name.Function or
                            (meth_tk[0] is Token.Keyword and
                             meth_tk[1].strip() == 'function'
                             and self.tokens[idx+1][0] is Token.Name.Function) or
                            self._tk_eq(idx, (Token.Punctuation, '[')) or
                            self._tk_eq(idx, (Token.Punctuation, ']')) or
                            self._tk_eq(idx, (Token.Punctuation, '=')) or
                            self._tk_eq(idx, (Token.Punctuation, '(')) or
                            self._tk_eq(idx, (Token.Punctuation, ')')) or
                            self._tk_eq(idx, (Token.Punctuation, ';')) or
                            self._tk_eq(idx, (Token.Punctuation, ','))):
                            msg = '[%s] Skipping tokens for methods defined in separate files.\ntoken #%d: %r'
                            logger.debug(msg, MAT_DOM, idx, self.tokens[idx])
                            idx += 1 + self._whitespace(idx + 1)
                        elif self._tk_eq(idx, (Token.Keyword, 'end')):
                            idx += 1
                            break
                        else:
                            # find methods
                            meth = MatMethod(self.module, self.tokens[idx:],
                                             self, attr_dict)
                            # Detect getter/setter methods - these are not documented
                            if not meth.name.split('.')[0] in ['get', 'set']:
                                self.methods[meth.name] = meth  # update methods
                            idx += meth.reset_tokens()  # reset method tokens and index

                            idx += self._whitespace(idx)
                    idx += 1
                if self._tk_eq(idx, (Token.Keyword, 'events')):
                    msg = '[%s] ignoring ''events'' in ''classdef %s.'''
                    logger.debug(msg, MAT_DOM, self.name)
                    idx += 1
                    # Token.Keyword: "end" terminates events block
                    while self._tk_ne(idx, (Token.Keyword, 'end')):
                        idx += 1
                    idx += 1
                if self._tk_eq(idx, (Token.Name, 'enumeration')):
                    msg = '[%s] ignoring ''enumeration'' in ''classdef %s.'''
                    logger.debug(msg, MAT_DOM, self.name)
                    idx += 1
                    # Token.Keyword: "end" terminates events block
                    while self._tk_ne(idx, (Token.Keyword, 'end')):
                        idx += 1
                    idx += 1
        except IndexError:
            msg = '[sphinxcontrib-matlabdomain] Parsing failed in {}.{}. Check if valid MATLAB code.'.format(
                modname, name)
            logger.warning(msg)

        self.rem_tks = idx  # index of last token

    def attributes(self, idx, attr_types):
        """
        Retrieve MATLAB class, property and method attributes.
        """
        attr_dict = {}
        idx += self._blanks(idx)  # skip blanks
        # class, property & method "attributes" start with parenthesis
        if self._tk_eq(idx, (Token.Punctuation, '(')):
            idx += 1
            # closing parenthesis terminates attributes
            while self._tk_ne(idx, (Token.Punctuation, ')')):
                idx += self._blanks(idx)  # skip blanks

                k, attr_name = self.tokens[idx]  # split token key, value
                if k is Token.Name and attr_name in attr_types:
                    attr_dict[attr_name] = True  # add attibute to dictionary
                    idx += 1
                elif k is Token.Name:
                    msg = '[sphinxcontrib-matlabdomain] Unexpected class attribute: "%s".' % str(self.tokens[idx][1])
                    msg += ' In "{0}.{1}".'.format(self.module, self.name)
                    logger.warning(msg)
                    idx += 1

                idx += self._blanks(idx)  # skip blanks

                # Continue if attribute is assigned a boolean value
                if self.tokens[idx][0] == Token.Name.Builtin:
                    idx += 1
                    continue

                # continue to next attribute separated by commas
                if self._tk_eq(idx, (Token.Punctuation, ',')):
                    idx += 1
                    continue
                # attribute values
                elif self._tk_eq(idx, (Token.Punctuation, '=')):
                    idx += 1
                    idx += self._blanks(idx)  # skip blanks
                    k, attr_val = self.tokens[idx]  # split token key, value
                    if (k is Token.Name and attr_val in ['true', 'false']):
                        # logical value
                        if attr_val == 'false':
                            attr_dict[attr_name] = False
                        idx += 1
                    elif k is Token.Name or \
                        self._tk_eq(idx, (Token.Text, '?')):
                        # concatenate enumeration or meta class
                        enum_or_meta = self.tokens[idx][1]
                        idx += 1
                        while (self._tk_ne(idx, (Token.Text, ' ')) and
                               self._tk_ne(idx, (Token.Text, '\t')) and
                               self._tk_ne(idx, (Token.Punctuation, ',')) and
                               self._tk_ne(idx, (Token.Punctuation, ')'))):
                            enum_or_meta += self.tokens[idx][1]
                            idx += 1
                        if self._tk_ne(idx, (Token.Punctuation, ')')):
                            idx += 1
                        attr_dict[attr_name] = enum_or_meta
                    # cell array of values
                    elif self._tk_eq(idx, (Token.Punctuation, '{')):
                        idx += 1
                        # closing curly braces terminate cell array
                        attr_dict[attr_name] = []
                        while self._tk_ne(idx, (Token.Punctuation, '}')):
                            idx += self._blanks(idx)  # skip blanks
                            # concatenate attr value string
                            attr_val = ''
                            # TODO: use _blanks or _indent instead
                            while self._tk_ne(idx, (Token.Punctuation, ',')) and self._tk_ne(idx, (Token.Punctuation, '}')):
                                attr_val += self.tokens[idx][1]
                                idx += 1
                            if self._tk_eq(idx, (Token.Punctuation, ',')):
                                idx += 1
                            if attr_val:
                                attr_dict[attr_name].append(attr_val)
                        idx += 1
                    elif self.tokens[idx][0] == Token.Literal.String and \
                        self.tokens[idx+1][0] == Token.Literal.String:
                        # String
                        attr_val += self.tokens[idx][1] + self.tokens[idx+1][1]
                        idx += 2
                        attr_dict[attr_name] = attr_val.strip("'")


                    idx += self._blanks(idx)  # skip blanks
                    # continue to next attribute separated by commas
                    if self._tk_eq(idx, (Token.Punctuation, ',')):
                        idx += 1
            idx += 1  # end of class attributes
        return attr_dict, idx

    @property
    def __module__(self):
        return self.module

    @property
    def __doc__(self):
        return self.docstring

    @property
    def __bases__(self):
        bases_ = dict.fromkeys(self.bases)  # make copy of bases
        num_pths = len(MatObject.basedir.split(os.sep))
        # walk tree to find bases
        for root, dirs, files in os.walk(MatObject.basedir):
            # namespace defined by root, doesn't include basedir
            root_mod = '.'.join(root.split(os.sep)[num_pths:])
            # don't visit vcs directories
            for vcs in ['.git', '.hg', '.svn', '.bzr']:
                if vcs in dirs:
                    dirs.remove(vcs)
            # only visit mfiles
            for f in tuple(files):
                if not f.endswith('.m'):
                    files.remove(f)
            # search folders
            for b in self.bases:
                # search folders
                for m in dirs:
                    # check if module has been matlabified already
                    mod_name = '.'.join([root_mod, m]).lstrip('.')
                    mod = modules.get(mod_name)
                    if not mod:
                        continue
                    # check if base class is attr of module
                    b_ = mod.getter(b, None)
                    if not b_:
                        b_ = mod.getter(b.lstrip(m.lstrip('+')), None)
                    if b_:
                        bases_[b] = b_
                        break
                if bases_[b]:
                    continue
                if b + '.m' in files:
                    mfile = os.path.join(root, b) + '.m'
                    bases_[b] = MatObject.parse_mfile(mfile, b, root)
            # keep walking tree
        # no matching folders or mfiles
        return bases_

    def getter(self, name, *defargs):
        """
        :class:`MatClass` ``getter`` method to get attributes.
        """
        if name == '__name__':
            return self.__name__
        elif name == '__doc__':
            return self.__doc__
        elif name == '__module__':
            return self.__module__
        elif name == '__bases__':
            return self.__bases__
        elif name in self.properties:
            return MatProperty(name, self, self.properties[name])
        elif name in self.methods:
            return self.methods[name]
        elif name == '__dict__':
            objdict = dict([(pn, self.getter(pn)) for pn in
                            self.properties.keys()])
            objdict.update(self.methods)
            return objdict
        else:
            super().getter(name, *defargs)


class MatProperty(MatObject):
    def __init__(self, name, cls, attrs):
        super().__init__(name)
        self.cls = cls
        self.attrs = attrs['attrs']
        self.default = attrs['default']
        self.docstring = attrs['docstring']
        # self.class = attrs['class']


    @property
    def __doc__(self):
        return self.docstring


def skip_whitespace(tks):
    """ Eats whitespace from list of tokens """
    while tks and (tks[-1][0] == Token.Text.Whitespace or
                   tks[-1][0] == Token.Text and tks[-1][1] in [' ', '\t']):
        tks.pop()


class MatFunctionOld(MatObject):
    """
    A MATLAB function.
    :param name: Name of :class:`MatObject`.
    :type name: str
    :param modname: Name of folder containing :class:`MatObject`.
    :type modname: str
    :param tokens: List of tokens parsed from mfile by Pygments.
    :type tokens: list
    """
    # MATLAB keywords that increment keyword-end pair count
    mat_kws = list(zip((Token.Keyword,) * 7,
                  ('arguments', 'for', 'if', 'switch', 'try', 'while', 'parfor')))

    def __init__(self, name, modname, tokens):
        super(MatFunctionOld, self).__init__(name)
        #: Path of folder containing :class:`MatObject`.
        self.module = modname
        #: List of tokens parsed from mfile by Pygments.
        self.tokens = tokens
        #: docstring
        self.docstring = ''
        #: output args
        self.retv = None
        #: input args
        self.args = None
        #: remaining tokens after main function is parsed
        self.rem_tks = None
        # =====================================================================
        # parse tokens
        # XXX: Pygments always reads MATLAB function signature as:
        # [(Token.Keyword, 'function'),  # any whitespace is stripped
        #  (Token.Text.Whitesapce, ' '),  # spaces and tabs are concatenated
        #  (Token.Text, '[o1, o2]'),  # if there are outputs, they're all
        #                               concatenated w/ or w/o brackets and any
        #                               trailing whitespace
        #  (Token.Punctuation, '='),  # possibly an equal sign
        #  (Token.Text.Whitesapce, ' '),  # spaces and tabs are concatenated
        #  (Token.Name.Function, 'myfun'),  # the name of the function
        #  (Token.Punctuation, '('),  # opening parenthesis
        #  (Token.Text, 'a1, a2',  # if there are args, they're concatenated
        #  (Token.Punctuation, ')'),  # closing parenthesis
        #  (Token.Text.Whitesapce, '\n')]  # all whitespace after args
        # XXX: Pygments does not tolerate MATLAB continuation ellipsis!
        tks = copy(self.tokens)  # make a copy of tokens
        tks.reverse()  # reverse in place for faster popping, stacks are LiLo
        try:
            # =====================================================================
            # parse function signature
            # function [output] = name(inputs)
            # % docstring
            # =====================================================================
            # Skip function token - already checked in MatObject.parse_mfile
            tks.pop()
            skip_whitespace(tks)

            #  Check for return values
            retv = tks.pop()
            if retv[0] is Token.Text:
                self.retv = [rv.strip() for rv in retv[1].strip('[ ]').split(',')]
                if len(self.retv) == 1:
                    # check if return is empty
                    if not self.retv[0]:
                        self.retv = None
                    # check if return delimited by whitespace
                    elif ' ' in self.retv[0] or '\t' in self.retv[0]:
                        self.retv = [rv for rv_tab in self.retv[0].split('\t')
                                     for rv in rv_tab.split(' ')]
                if tks.pop() != (Token.Punctuation, '='):
                    # Unlikely to end here. But never-the-less warn!
                    msg = '[sphinxcontrib-matlabdomain] Parsing failed in {}.{}. Expected "=".'.format(modname, name)
                    logger.warning(msg)
                    return

                skip_whitespace(tks)
            elif retv[0] is Token.Name.Function:
                tks.append(retv)
            # =====================================================================
            # function name
            func_name = tks.pop()
            func_name = (func_name[0], func_name[1].strip(' ()'))  # Strip () in case of dummy arg
            if func_name != (Token.Name.Function, self.name):  # @UndefinedVariable
                if isinstance(self, MatMethod):
                    self.name = func_name[1]
                else:
                    msg = '[sphinxcontrib-matlabdomain] Unexpected function name: "%s".' % func_name[1]
                    msg += ' Expected "{}" in module "{}".'.format(name, modname)
                    logger.warning(msg)

            # =====================================================================
            # input args
            if tks.pop() == (Token.Punctuation, '('):
                args = tks.pop()
                if args[0] is Token.Text:
                    self.args = [arg.strip() for arg in args[1].split(',')]\
                # no arguments given




                elif args == (Token.Punctuation, ')'):
                    # put closing parenthesis back in stack
                    tks.append(args)
                # check if function args parsed correctly
                if tks.pop() != (Token.Punctuation, ')'):
                    # Unlikely to end here. But never-the-less warn!
                    msg = '[sphinxcontrib-matlabdomain] Parsing failed in {}.{}. Expected ")".'.format(modname, name)
                    logger.warning(msg)
                    return

            skip_whitespace(tks)
            # =====================================================================
            # docstring
            try:
                docstring = tks.pop()
            except IndexError:
                docstring = None
            while docstring and docstring[0] is Token.Comment:
                self.docstring += docstring[1].lstrip('%')
                # Get newline if it exists and append to docstring
                try:
                    wht = tks.pop()  # We expect a newline
                except IndexError:
                    break
                if wht[0] in (Token.Text, Token.Text.Whitespace) and wht[1] == '\n':
                    self.docstring += '\n'
                # Skip whitespace
                try:
                    wht = tks.pop()  # We expect a newline
                except IndexError:
                    break
                while wht in list(zip((Token.Text,) * 3, (' ', '\t'))):
                    try:
                        wht = tks.pop()
                    except IndexError:
                        break
                docstring = wht  # check if Token is Comment
            # =====================================================================
            # Is this code even used?
            # main body
            # find Keywords - "end" pairs
            if docstring is None:
                return
            kw = docstring  # last token
            lastkw = 0  # set last keyword placeholder
            kw_end = 1  # count function keyword
            while kw_end > 0:
                # increment keyword-end pairs count
                if kw in MatFunction.mat_kws:
                    kw_end += 1
                # nested function definition
                elif kw[0] is Token.Keyword and kw[1].strip() == 'function':
                    kw_end += 1
                # decrement keyword-end pairs count but
                # don't decrement `end` if used as index
                elif kw == (Token.Keyword, 'end') and not lastkw:
                    kw_end -= 1
                # save last punctuation
                elif kw in list(zip((Token.Punctuation,) * 2, ('(', '{'))):
                    lastkw += 1
                elif kw in list(zip((Token.Punctuation,) * 2, (')', '}'))):
                    lastkw -= 1
                try:
                    kw = tks.pop()
                except IndexError:
                    break
            tks.append(kw)  # put last token back in list
        except IndexError:
            msg = '[sphinxcontrib-matlabdomain] Parsing failed in {}.{}. Check if valid MATLAB code.'.format(
                modname, name)
            logger.warning(msg)
        # if there are any tokens left save them
        if len(tks) > 0:
            self.rem_tks = tks  # save extra tokens

    @property
    def __doc__(self):
        return self.docstring

    @property
    def __module__(self):
        return self.module

    def getter(self, name, *defargs):
        if name == '__name__':
            return self.__name__
        elif name == '__doc__':
            return self.__doc__
        elif name == '__module__':
            return self.__module__
        else:
            super(MatFunctionOld, self).getter(name, *defargs)



class MatMethod(MatFunctionOld):
    def __init__(self, modname, tks, cls, attrs):
        # set name to None
        super().__init__(None, modname, tks)
        self.cls = cls
        self.attrs = attrs

    def reset_tokens(self):
        num_rem_tks = len(self.rem_tks)
        len_meth = len(self.tokens) - num_rem_tks
        self.tokens = self.tokens[:-num_rem_tks]
        self.rem_tks = None
        return len_meth

    @property
    def __module__(self):
        return self.module

    @property
    def __doc__(self):
        return self.docstring


class MatScript(MatObject):
    def __init__(self, name, modname, tks):
        super().__init__(name)
        #: Path of folder containing :class:`MatScript`.
        self.module = modname
        #: List of tokens parsed from mfile by Pygments.
        self.tokens = tks
        #: docstring
        self.docstring = ''
        #: remaining tokens after main function is parsed
        self.rem_tks = None

        tks = copy(self.tokens)  # make a copy of tokens
        tks.reverse()  # reverse in place for faster popping, stacks are LiLo
        tks_next(tks)
        # =====================================================================
        # docstring
        try:
            docstring = tks.pop()
            # Skip any statements before first documentation header
            while docstring and docstring[0] is not Token.Comment:
                docstring = tks.pop()
        except IndexError:
            docstring = None
        while docstring and docstring[0] is Token.Comment:
            self.docstring += docstring[1].lstrip('%')
            # Get newline if it exists and append to docstring
            try:
                wht = tks.pop()  # We expect a newline
            except IndexError:
                break
            if wht[0] in (Token.Text, Token.Text.Whitespace) and wht[1] == '\n':
                self.docstring += '\n'
            # Skip whitespace
            try:
                wht = tks.pop()  # We expect a newline
            except IndexError:
                break
            while wht in list(zip((Token.Text,) * 3, (' ', '\t'))):
                try:
                    wht = tks.pop()
                except IndexError:
                    break
            docstring = wht  # check if Token is Comment

    @property
    def __doc__(self):
        return self.docstring

    @property
    def __module__(self):
        return self.module


class MatApplication(MatObject):
    """
    Representation of the documentation in a Matlab Application.

    :param name: Name of :class:`MatObject`.
    :type name: str
    :param modname: Name of folder containing :class:`MatObject`.
    :type modname: str
    :param desc: Summary and description string.
    :type desc: str
    """

    def __init__(self, name, modname, desc):
        super().__init__(name)
        #: Path of folder containing :class:`MatApplication`.
        self.module = modname
        #: docstring
        self.docstring = desc

    @property
    def __doc__(self):
        return self.docstring

    @property
    def __module__(self):
        return self.module


class MatException(MatObject):
    def __init__(self, name, path, tks):
        super().__init__(name)
        self.path = path
        self.tks = tks
        self.docstring = ''

    @property
    def __doc__(self):
        return self.docstring


class MatcodeError(Exception):
    def __str__(self):
        res = self.args[0]
        if len(self.args) > 1:
            res += ' (exception was: %r)' % self.args[1]
        return res


class MatModuleAnalyzer(object):
    # cache for analyzer objects -- caches both by module and file name
    cache = {}

    @classmethod
    def for_folder(cls, dirname, modname):
        if ('folder', dirname) in cls.cache:
            return cls.cache['folder', dirname]
        obj = cls(None, modname, dirname, True)
        cls.cache['folder', dirname] = obj
        return obj

    @classmethod
    def for_module(cls, modname):
        if ('module', modname) in cls.cache:
            entry = cls.cache['module', modname]
            if isinstance(entry, MatcodeError):
                raise entry
            return entry
        mod = modules.get(modname)
        if mod:
            obj = cls.for_folder(mod.path, modname)
        else:
            err = MatcodeError('error importing %r' % modname)
            cls.cache['module', modname] = err
            raise err
        cls.cache['module', modname] = obj
        return obj

    def __init__(self, source, modname, srcname, decoded=False):
        # name of the module
        self.modname = modname
        # name of the source file
        self.srcname = srcname
        # file-like object yielding source lines
        self.source = source
        # cache the source code as well
        self.encoding = None
        self.code = None
        # will be filled by tokenize()
        self.tokens = None
        # will be filled by parse()
        self.parsetree = None
        # will be filled by find_attr_docs()
        self.attr_docs = None
        self.tagorder = None
        # will be filled by find_tags()
        self.tags = None

    def find_attr_docs(self, scope=''):
        """Find class and module-level attributes and their documentation."""
        if self.attr_docs is not None:
            return self.attr_docs
        attr_visitor_collected = {}
        attr_visitor_tagorder = {}
        tagnumber = 0
        mod = modules[self.modname]
        # walk package tree
        for k, v in mod.safe_getmembers():
            if hasattr(v, 'docstring'):
                attr_visitor_collected[mod.package, k] = v.docstring
                attr_visitor_tagorder[k] = tagnumber
                tagnumber += 1
            if isinstance(v, MatClass):
                for mk, mv in v.getter('__dict__').items():
                    namespace = '.'.join([mod.package, k])
                    tagname = '%s.%s' % (k, mk)
                    attr_visitor_collected[namespace, mk] = mv.docstring
                    attr_visitor_tagorder[tagname] = tagnumber
                    tagnumber += 1
        self.attr_docs = attr_visitor_collected
        self.tagorder = attr_visitor_tagorder
        return attr_visitor_collected
