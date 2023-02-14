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
from collections import defaultdict


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

    def warning(self, message: str = ''):
        if hasattr(self, 'module'):
            msg = f'[{MAT_DOM}] Parsing failed in {self.module}.{self.name}.'
        else:
            msg = f'[{MAT_DOM}] Parsing failed in {self.name}.'
        if message:
            msg = f'{msg} {message}'
        logger.warning(msg)

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

    # Convert to number of that is the case
    if literal.replace('.','',1).isdigit():
        if literal.isdigit():
            literal = int(literal)
        else:
            literal = float(literal)
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


class MatProperty(MatObject):
    """
    The token parser for properties.

        Prop (1,1) propType {Validators} = default_value() # Description

    The 'Prop' token is already removed from the token list and used for the constructor. 
    """
    def __init__(self, name: str, attrs: dict = {}) -> None:
        self.name = name
        self.attrs = attrs

    def parse_tokens(self, tks: Generator, token: tuple):
        """
        Parses a list of tokens starting from after the property name. 
        """

        # Property size
        if token == (Token.Punctuation, '('):
            self.size = []
            token = tks_next(tks)
            while token and token != (Token.Punctuation, ')'):
                if token[0] is Token.Literal.Number.Integer:
                    self.size.append(int(token[1]))
                token = tks_next(tks)
            else:
                token = tks_next(tks, skip_comment=False)
        else:
            self.size = None

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

    @property
    def __doc__(self):
        return self.docstring

class MatArgument(MatProperty):
    def parse_tokens(self, tks: Generator, token: tuple):
        if token == (Token.Punctuation, '.'):
            self.field = next(tks)[1]
            token = tks_next(tks, skip_comment=False)
        else:
            self.field = None
        return super().parse_tokens(tks, token)

    def __repr__(self) -> str:
        if self.field:
            return f'<{self.__class__.__name__} of {self.name}.{self.field}>'
        else:
            return super().__repr__()


class AttributeBlock(ABC):
    '''
    Abstract type for block objects that has (MATLAB) attribute descriptions. 

    Extensions to the abstract type must define all possible attributes for the block in the (python) class
    attribute `attr_types`, a dictionary containing key-value pairs for the (MATLAB) attribute names 
    and their value types. 
    '''
    attr_types = {}

    def __init__(self, tks: Generator):

        self.attrs = {}

        token = tks_next(tks)

        # Get attributes
        if token == (Token.Punctuation, '('):
            token = tks_next(tks)
            text_attribute = ''
            while token and token != (Token.Punctuation, ')'):
                if token[0] is Token.Name or token[0] is Token.Name.Builtin:
                    token = self.parse_attribute(token[1], tks)
                elif token[0] is Token.Text:
                    text_attribute += token[1]
                    token = tks_next(tks)
                elif token == (Token.Punctuation, ','):
                    if text_attribute:
                        token = self.parse_attribute(text_attribute, tks)
                        text_attribute = ''
                    else:
                        token = tks_next(tks)
                else:
                    msg = f'[{MAT_DOM}] Error in attribute parsing of {self.__class__.__name__}.'
                    logger.warning(msg)
            else:
                if text_attribute:
                    token = self.parse_attribute(text_attribute, tks)

    def parse_attribute(self, attribute, tks):
        '''
        Parses a single attribute.

        The attribute must exist in the dictionary ``attrs_types``. Each attribute can be either a boolean or a list. If the type if boolean, the value will default to True if the attribute is present. Otherwise the parser will look for the ``=`` sign and the value after. 
        '''

        if attribute in self.attr_types.keys():

            if self.attr_types[attribute] is bool:
                token = tks_next(tks)
                if token == (Token.Punctuation, '='):
                    token = tks_next(tks)
                    if token[1] in ['true', 'True']:
                        self.attrs[attribute] = True
                        token = tks_next(tks)
                    elif token[1] in ['false', 'False']:
                        self.attrs[attribute] = False
                        token = tks_next(tks)
                    else:
                        # Expression https://nl.mathworks.com/help/matlab/matlab_oop/expressions-in-class-definitions.html#bsggxle
                        expression, token = tks_code_literal(tks, token)
                        self.attrs[attribute] = expression

                else:
                    self.attrs[attribute] = True

            elif self.attr_types[attribute] is list:
                tks_next(tks)
                value, token = tks_code_literal(tks)
                self.attrs[attribute] = value

        else:
            msg = f'[{MAT_DOM}] Unsupported attribute {attribute} for {self.__class__.__name__}.'
            logger.warning(msg)
        return token


class ArgumentsBlock(AttributeBlock):
    '''
    Arguments block for functions and methods.

    Loops over the items in a arguments block in a function and parses each argument 
    with an MatArgument object. 
    '''
    attr_types = {"Input": bool, "Output": bool, "Repeating": bool}

    def __init__(self, tks: Generator, args: list, retv: list):
        super().__init__(tks)
        if self.attrs.get('Input', False) or not self.attrs.get('Output', False):
            self.arg_list, self.type = args, 'Input'
        else:
            self.arg_list, self.type = retv, 'Output'
        self.repeating = self.attrs.get('Repeating', False)

        # Get arguments
        self.arguments = defaultdict(list)
        token = tks_next(tks, skip_newline=True)

        while token and token != (Token.Keyword, 'end'):
            if token[0] is Token.Name:
                arg = token[1]
                if arg in self.arg_list:
                    argument = MatArgument(arg, attrs=self.attrs)
                    token = tks_next(tks, skip_comment=False)
                    token = argument.parse_tokens(tks, token)
                    self.arguments[arg].append(argument)
                else:
                    msg = f'[{MAT_DOM}] Parsing failed in {self}.'
                    msg += f' {self.type} argument "{arg}" is unknown.'
                    logger.warning(msg)
                    raise IndexError
            else:
                token = tks_next(tks, skip_newline=True)

    def __repr__(self) -> str:
        return f'<ArgumentsBlock [{", ".join(self.arguments.keys())}]>'


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

    def __init__(self, name: str, modname: str, tks: Generator):
        super().__init__(name)

        self.module = modname  #: Path of folder containing :class:`MatObject`.
        self.tokens = tks  #: List of tokens parsed from mfile by Pygments.
        self.docstring = ''  #: docstring
        self.retv = []  #: output args
        self.retv_va = {}
        self.args = []  #: input args
        self.args_va = {}
        self.rem_tks = []

        # =====================================================================

        token = tks_next(tks)

        # =====================================================================
        # Return values and function name

        if token[0] is Token.Text:
            # No or single return value

            nxt_token = tks_next(tks)

            if nxt_token == (Token.Punctuation, '='):
                self.retv = [token[1].strip('[ ]')]
                token = tks_next(tks)
            else:
                token = nxt_token

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
            if isinstance(self, MatMethod):
                self.name = func_name  # Method name not known until now
            else:
                self.warning(f'Expected function "{name}", found "{func_name}".')

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

            argblock = ArgumentsBlock(tks, self.args, self.retv)
            if argblock.type == 'Input':
                self.args_va.update(argblock.arguments)
            else:
                self.retv_va.update(argblock.arguments)

            token = tks_next(tks, skip_newline=True)

        if self.args_va and (len(self.args) != len(self.args_va)):
            msg = f'[{MAT_DOM}] Parsing failed in input arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)

        if self.retv_va and (len(self.retv) != len(self.retv_va)):
            msg = f'[{MAT_DOM}] Parsing failed in output arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)

        # =====================================================================
        # Remainder of function is not checked, nothing of interest

        while token and token != (Token.Keyword, 'end'):
            self.rem_tks.append(token)  # save extra tokens # TODO remove this altogether?
            token = tks_next(tks, skip_newline=True)

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


######################################################################################
#                                       Classes
######################################################################################


class PropertiesBlock(AttributeBlock):
    '''
    Properties block for classes.

    Loops over the items in a properties block in a class and parses each property 
    with an MatProperty object. 
    '''
    attr_types = {
        'AbortSet': bool,
        'Abstract': bool,
        'Access': list,
        'Constant': bool,
        'Dependent': bool,
        'GetAccess': list,
        'GetObservable': bool,
        'Hidden': bool,
        'NonCopyable': bool,
        'SetAccess': list,
        'SetObservable': bool,
        'Transient': bool,
        'ClassSetupParameter': bool,
        'MethodSetupParameter': bool,
        'TestParameter': bool
    }

    def __init__(self, tks: Generator):
        super().__init__(tks)
        self.properties = {}

        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            if token[0] is Token.Name:
                prop = token[1]
                property = MatProperty(prop, attrs=self.attrs)
                token = tks_next(tks, skip_comment=False)
                token = property.parse_tokens(tks, token)
                self.properties[prop] = property
            else:
                self.warning("Expected a property here.")
                raise IndexError


class MethodsBlock(AttributeBlock):
    '''
    Method block for classes.

    Loops over the items in a method block in a class and parses each argument 
    with a MatMethod object. 
    '''
    attr_types = {
        'Abstract': bool,
        'Access': list,
        'Hidden': bool,
        'Sealed': list,
        'Static': bool,
        'Test': bool,
        'TestClassSetup': bool,
        'TestMethodSetup': bool,
        'TestClassTeardown': bool,
        'TestMethodTeardown': bool,
        'ParameterCombination': bool
    }

    def __init__(self, tks: Generator, cls: 'MatClass'):
        super().__init__(tks)
        self.methods = {}

        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            method = MatMethod(cls, self.attrs, tks)

            # Set to constructor
            if method.name == cls.name:
                method.attrs['Constructor'] = True

            # Remove object self from arguments
            if not method.name == cls.name and not self.attrs.get('Static', False):
                obj = method.args.pop(0)
                if method.args_va:
                    method.args_va.pop(obj)

            self.methods[method.name] = method
            token = tks_next(tks, skip_newline=True)


class MatMethod(MatFunction):
    '''
    A MATLAB method
    '''
    def __init__(self, cls: 'MatClass', attrs: dict, tks: Generator):
        super().__init__(name=None, modname=cls.module, tks=tks)
        self.cls = cls
        self.attrs = attrs


class MatClass(AttributeBlock, MatObject):

    attr_types = {
        'Abstract': bool,
        'AllowedSubclasses': list,
        'ConstructOnLoad': bool,
        'HandleCompatible': bool,
        'Hidden': bool,
        'InferiorClasses': list,
        'Sealed': bool
    }

    def __init__(self, name: str, modname: str, tks: Generator):

        super().__init__(tks)
        super(AttributeBlock, self).__init__(name)

        self.module = modname  #: Path of folder containing :class:`MatObject`.
        self.tokens = tks  #: List of tokens parsed from mfile by Pygments.
        self.bases = []  #: list of class superclasses
        self.docstring = ''  #: docstring
        self.properties = {}  #: dictionary of class properties
        self.methods = {}  #: dictionary of class methods

        # =====================================================================

        token = tks_next(tks)

        # =====================================================================
        # Class name and inheritance

        if self.name != token[1]:
            self.warning(f'Expected class "{name}", found "{token[1]}".')

        token = tks_next(tks)

        if token == (Token.Operator, '<'):
            token = tks_next(tks)
            base = ''
            while token and token[0] is not Token.Text.Whitespace:
                if token == (Token.Operator, '&'):
                    self.bases.append(base)
                    base = ''
                else:
                    base += token[1]
                token = tks_next(tks)
            else:
                self.bases.append(base)

        # =====================================================================
        # docstring
        token = tks_next(tks, skip_newline=True, skip_comment=False)
        self.docstring, token = tks_docstring(tks, token)

        # =====================================================================
        # Properties and methods

        while token and token != (Token.Keyword, 'end'):
            if token == (Token.Keyword, 'properties'):
                self.properties.update(PropertiesBlock(tks).properties)
            elif token == (Token.Keyword, 'methods'):
                self.methods.update(MethodsBlock(tks=tks, cls=self).methods)
            else:
                self.warning()

            token = tks_next(tks, skip_newline=True)

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
            return self.properties[name]
        elif name in self.methods:
            return self.methods[name]
        elif name == '__dict__':
            return {**self.properties, **self.methods}
        else:
            super().getter(name, *defargs)


######################################################################################
#                                       Old
######################################################################################

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
                    tagname = '%s.%s' % (k, mk)
                    attr_visitor_collected[k, mk] = mv.docstring
                    attr_visitor_tagorder[tagname] = tagnumber
                    tagnumber += 1
        self.attr_docs = attr_visitor_collected
        self.tagorder = attr_visitor_tagorder
        return attr_visitor_collected
