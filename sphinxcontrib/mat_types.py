"""optional
    sphinxcontrib.mat_types
    ~~~~~~~~~~~~~~~~~~~~~~~

    Types for MATLAB.

    :copyright: Copyright 2014 Mark Mikofski
    :license: BSD, see LICENSE for details.
"""
import os
import re
import sphinx.util
import charset_normalizer
import xml.etree.ElementTree as ET
from abc import ABC
from pathlib import Path
from zipfile import ZipFile
from collections import defaultdict
from typing import Tuple, Generator, Optional, List, Union
from pygments.token import Token, _TokenType
from pygments.lexers.matlab import MatlabLexer


MAT_DOM = 'sphinxcontrib-matlabdomain'
logger = sphinx.util.logging.getLogger('matlab-domain')
TokenType = Tuple[_TokenType, str]
TksType = Generator[TokenType, None, None]


######################################################################################
#                               .m file pre-processing
######################################################################################

def code_tokenize(mfile: Union[str, Path], remove_comment_header: bool = True):

    # Read file with correct encoding via charset_normalizer
    code = str(charset_normalizer.from_path(mfile).best()).replace('\r\n', '\n') # module name

    if remove_comment_header:
        code = code_remove_comment_header(code)
    
    # Preprocessing the codestring
    code = code_fix_function_signatures(
        code_remove_line_continuations(code)
    )
    return MatlabLexer().get_tokens(code)


def code_remove_comment_header(code: str) -> str:
    """
    Removes the comment header (if there is one) and empty lines from the
    top of the current read code.
    :param code: Current code string.
    :type code: str
    :returns: Code string without comments above a function, class or
                procedure/script.
    """
    # get the line number when the comment header ends (incl. empty lines)
    ln_pos = 0
    for line in code.splitlines(True):
        if re.match(r"[ \t]*(%|\n)", line):
            ln_pos += 1
        else:
            break

    if ln_pos > 0:
        # remove the header block and empty lines from the top of the code
        try:
            code = code.split('\n', ln_pos)[ln_pos:][0]
        except IndexError:
            # only header and empty lines.
            code = ''

    return code


def code_remove_line_continuations(code: str) -> str:
    """
    Removes line continuations (...) from code as functions must be on a
    single line
    :param code:
    :type code: str
    :return:
    """
    pat = r"('.*)(\.\.\.)(.*')"
    code = re.sub(pat, r'\g<1>\g<3>', code, flags=re.MULTILINE)

    pat = r"^([^%'\"\n]*)(\.\.\..*\n)"
    code = re.sub(pat, r'\g<1>', code, flags=re.MULTILINE)
    return code


re_function_signatures = re.compile(
    r"""^
    [ \t]*function[ \t.\n]*         # keyword (function)
    (\[?[\w, \t.\n]*\]?)[ \t.\n]*   # outputs: group(1)
    =[ \t.\n]*                      # punctuation (eq)
    (\w+)[ \t.\n]*                  # name: group(2)
    \(?([\w, \t.\n]*)\)?            # args: group(3)
    """,
    re.VERBOSE | re.MULTILINE  # search start of every line
)


def code_fix_function_signatures(code: str) -> str:
    """
    Transforms function signatures with line continuations to a function
    on a single line with () appended. Required because pygments cannot
    handle this situation correctly.

    :param code:
    :type code: str
    :return: Code string with functions on single line
    """

    # replacement function
    def repl(m):
        retv = m.group(0)
        # if no args and doesn't end with parentheses, append "()"
        if not (m.group(3) or m.group(0).endswith('()')):
            retv = retv.replace(m.group(2), m.group(2) + "()")
        return retv

    code = re_function_signatures.sub(repl, code)  # search for functions and apply replacement
    msg = '[%s] replaced ellipsis & appended parentheses in function signatures'
    logger.debug(msg, MAT_DOM)
    return code


######################################################################################
#                               Shared token parsers
######################################################################################


def tks_next(
    tks: TksType,
    skip_newline: bool = False,
    skip_semicolon: bool = True,
    skip_comment: bool = True
) -> TokenType:
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


def tks_code_literal(tks: Generator, token: Optional[TokenType] = None) -> Tuple[str, TokenType]:
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
            token[1] in statement_endings,
            token[0] is Token.Text.Whitespace and '\n' in token[1], token[0] is Token.Comment
        ]
    ):
        if token[1] in closing_punctionations.keys():
            # literal has a backet opener, thus a corresponding close is expected
            expected_close.append(closing_punctionations[token[1]])
        elif token[1] in closing_punctionations.values():
            # All closing brackets must follow the expected order.
            if token[1] != expected_close.pop():
                raise IndexError

        # Add to literal, which can have most types
        literal += token[1]

        token = tks_next(tks, skip_semicolon=False, skip_comment=False)

    # Convert to number of that is the case
    if literal.replace('.', '', 1).isdigit():
        if literal.isdigit():
            literal = int(literal)
        else:
            literal = float(literal)
    return literal, token


def tks_docstring(tks: TksType, token: TokenType, header: str = '') -> Tuple[str, TokenType]:
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
            [
                line[num_leading_space:] if len(line) > num_leading_space + 1 else ''
                for line in doc_lines
            ]
        )
        if header:
            docstring = f"{header} {docstring}"
        return docstring, token


######################################################################################
#                             Common Matlab objects
######################################################################################


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


class MatProperty(MatObject):
    """
    The token parser for properties.

        Prop (1,1) propType {Validators} = default_value() # Description

    The 'Prop' token is already removed from the token list and used for the constructor. 
    """
    def __init__(self, cls: 'MatClass', name: str, attrs: dict = {}, index: int = 0) -> None:
        self.cls = cls
        self.name = name
        self.attrs = attrs
        self.index = index

    def parse_tokens(self, tks: TksType, token: TokenType):
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

    def __init__(self, name: str, attrs: dict = {}, index: int = 0) -> None:
        self.name = name
        self.attrs = attrs
        self.index = index

    def parse_tokens(self, tks: TksType, token: TokenType):
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

    def __init__(self, tks: TksType):

        self.attrs = {}

        token = tks_next(tks)

        # Get attributes
        if token == (Token.Punctuation, '('):
            token = tks_next(tks)
            text_attribute = ''
            while token and token != (Token.Punctuation, ')'):
                if token[0] is Token.Name or token[0] is Token.Name.Builtin:
                    token = self.parse_attribute(token[1], tks)
                elif token[0] is Token.Text and token[1] != '=':
                    text_attribute += token[1]
                    token = tks_next(tks)
                elif token == (Token.Punctuation, ',') or token == (Token.Text, '='):
                    if text_attribute:
                        if token == (Token.Text, '='):
                            token = self.parse_attribute(text_attribute, tks, token)
                        else:
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

    def parse_attribute(self, attribute: str, tks: TksType, token: Optional[TokenType] = None) -> TokenType:
        '''
        Parses a single attribute.

        The attribute must exist in the dictionary ``attrs_types``. Each attribute can be either a boolean or a list. If the type if boolean, the value will default to True if the attribute is present. Otherwise the parser will look for the ``=`` sign and the value after. 
        '''

        if not token:
            token = tks_next(tks)

        if attribute in self.attr_types.keys():

            if self.attr_types[attribute] is bool:
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
                value, token = tks_code_literal(tks)

                # If value is a MATLAB cell, put it in a list
                if value[0] == '{' and value[-1] == '}':
                    self.attrs[attribute] = [v.strip() for v in value.strip('{}').split(',')]
                else:
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

    def __init__(self, tks: TksType, args: list, retv: list):
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


######################################################################################
#                                       Modules
######################################################################################


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

    # TODO: get docstring and __all__ from contents.m if exists

    def __init__(self, name, path, package, basedir):
        super().__init__(name)
        #: Path to module on disk, path to package's __init__.py
        self.path = path
        #: name of package (full path from basedir to module)
        self.package = package
        self.basedir = basedir
        # add module to system dictionary
        modules[package] = self

    def safe_getmembers(self) -> List[tuple]:
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
            attr = import_matlab_object('.'.join([self.package, name]), self.basedir)
            if attr:
                setattr(self, name, attr)
                msg = '[%s] attr %s imported from mod %s.'
                logger.debug(msg, MAT_DOM, name, self)
                return attr
            else:
                super().getter(name, *defargs)


######################################################################################
#                                       Functions
######################################################################################


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
    matlab_end_keywords = {'function', 'for', 'if', 'switch', 'try', 'while', 'parfor'}

    def __init__(self, name: str, module: str, file: str, tks: Optional[TksType] = None):
        
        self.name = name
        self.module = module  #: Path of folder containing :class:`MatObject`.
        self.file = file
        self.docstring = ''  #: docstring
        self.retv = []  #: output args
        self.retv_block = {}
        self.args = []  #: input args
        self.args_block = {}
        self.rem_tks = []

        if not tks:
            tks = code_tokenize(Path(module) / (name + '.m'))
            token = next(tks)
            if token != (Token.Keyword, 'function'):
                logger.warning(f'{MAT_DOM} could not import function {name}. Use a different autodirective.')
                raise ImportError

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
                self.args_block.update(argblock.arguments)
            else:
                self.retv_block.update(argblock.arguments)

            token = tks_next(tks, skip_newline=True)

        if self.args_block and (len(self.args) != len(self.args_block)):
            msg = f'[{MAT_DOM}] Parsing failed in input arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)

        if self.retv_block and (len(self.retv) != len(self.retv_block)):
            msg = f'[{MAT_DOM}] Parsing failed in output arguments block of {self.name}.'
            msg += ' Are you sure the number of arguments match the function signature?'
            logger.warning(msg)

        # =====================================================================
        # Remainder of function is not checked, nothing of interest

        nest_level = 0
        while token and (token != (Token.Keyword, 'end') or nest_level != 0):
            if token[0] is Token.Keyword:
                if token[1] in self.matlab_end_keywords:
                    nest_level += 1
                elif token[1] == 'end':
                    nest_level -= 1
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

    def __init__(self, tks: TksType, cls: 'MatClass'):
        super().__init__(tks)
        self.properties = {}

        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            if token[0] is Token.Name:
                prop = token[1]
                property = MatProperty(cls, prop, attrs=self.attrs, index=cls.item_index)
                token = tks_next(tks, skip_comment=False)
                token = property.parse_tokens(tks, token)
                self.properties[prop] = property
                cls.item_index += 1
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

    def __init__(self, tks: TksType, cls: 'MatClass'):
        super().__init__(tks)
        self.methods = {}

        token = tks_next(tks, skip_newline=True)
        while token and token != (Token.Keyword, 'end'):
            method = MatMethod(cls, attrs=self.attrs, tks=tks, index=cls.item_index)

            # Set to constructor
            if method.name == cls.name:
                method.attrs['Constructor'] = True

            # Remove object self from arguments
            if not method.name == cls.name and not self.attrs.get('Static', False):
                obj = method.args.pop(0)
                if method.args_block:
                    method.args_block.pop(obj)

            self.methods[method.name] = method
            cls.item_index += 1
            token = tks_next(tks, skip_newline=True)



class MatMethod(MatFunction):
    '''
    A MATLAB method
    '''
    def __init__(self, cls: 'MatClass', attrs: dict, tks: TksType, index: int = 0):
        super().__init__(name=None, module=cls.module, file=cls.file, tks=tks)
        self.cls = cls
        self.attrs = attrs
        self.index = index


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

    def __init__(self, name: str, module: str, file: str, tks: Optional[TksType] = None):

        self.name = name
        self.module = module  #: Path of folder containing :class:`MatObject`.
        self.file = file
        self.bases = []  #: list of class superclasses
        self.docstring = ''  #: docstring
        self.constructor = None
        self.properties = {}  #: dictionary of class properties
        self.methods = {}  #: dictionary of class methods
        self.item_index = 0

        if not tks:
            tks = code_tokenize(Path(module) / (name + '.m'))
            token = next(tks)
            if token != (Token.Keyword, 'classdef'):
                logger.warning(f'{MAT_DOM} could not import class {name}. Use a different autodirective.')
                raise ImportError

        # Get class attributes
        super().__init__(tks) 
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
                self.properties.update(PropertiesBlock(tks, cls=self).properties)
            elif token == (Token.Keyword, 'methods'):
                self.methods.update(MethodsBlock(tks=tks, cls=self).methods)
            else:
                self.warning()

            token = tks_next(tks, skip_newline=True)
        
        # Get constructor
        for methodname, method in self.methods.items():
            if method.attrs.get("Constructor"):
                self.constructor = self.methods.pop(methodname)
                break

    @property
    def __module__(self):
        return self.module

    @property
    def __doc__(self):
        return self.docstring

    @property
    def members(self):
        return {**self.properties, **self.methods}


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
            return self.bases
        elif name in self.properties:
            return self.properties[name]
        elif name in self.methods:
            return self.methods[name]
        elif name == '__dict__':
            return {**self.properties, **self.methods}
        else:
            super().getter(name, *defargs)


######################################################################################
#                                       Others
######################################################################################


class MatScript(MatObject):
    def __init__(self, name: str, module: str, file: str, tks: Optional[TksType] = None):
        self.name = name
        self.module = module
        self.file = file

        if not tks:
            tks = code_tokenize(Path(module) / (name + '.m'), remove_comment_header=False)
            
        token = next(tks)
        self.docstring, token = tks_docstring(tks, token)

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