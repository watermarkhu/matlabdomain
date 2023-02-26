"""
    sphinxcontrib.mat_documenters
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Extend autodoc directives to matlabdomain.

    :copyright: Copyright 2014 Mark Mikofski
    :license: BSD, see LICENSE for details.
"""

import os
import re
import sphinx.util

from pathlib import Path
from pygments.token import Token
from pygments.lexers.markup import RstLexer
from docutils.statemachine import ViewList, StringList
from sphinx.locale import _, __
from sphinx.ext.autodoc import (
    identity, Options, ALL, INSTANCEATTR, SUPPRESS,
    members_option, inherited_members_option, exclude_members_option,
    member_order_option, annotation_option, bool_option,
    Documenter as PyDocumenter,
    ModuleDocumenter as PyModuleDocumenter,
    FunctionDocumenter as PyFunctionDocumenter,
    ClassDocumenter as PyClassDocumenter,
    ExceptionDocumenter as PyExceptionDocumenter,
    DataDocumenter as PyDataDocumenter,
    MethodDocumenter as PyMethodDocumenter
)
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Type,
    TypeVar, Union
)
from .mat_types import (
    MatObject, MatModule, MatFunction, MatClass, MatProperty, MatMethod, MatScript, MatApplication,
)


MAT_DOM = 'sphinxcontrib-matlabdomain'
logger = sphinx.util.logging.getLogger('matlab-domain')
mat_ext_sig_re = re.compile(
    r'''^
        (
            (?:
                (?:\.\.[/\\])+|[/\\\.]+      # relative path up
            )?                              # ^optional
            (?:\w+[/\\])+                   # relative path down
        )?                              # path
        ((?:[@+]\w+[/\\\.])*)           # namespace
        ((?:\w+\.)*)                    # object path
        (\w+)                           # object name
        (?:\.\w+)?                      # extension
        $''', re.VERBOSE
)

def parse_matlab_path(fullpath: str):

    path, namespace_path, obj_path, base = mat_ext_sig_re.match(fullpath.strip()).groups()
    namespace = re.split(r'[/\\\.]+', namespace_path.strip(r'/\\\.')) if namespace_path else []
    objpath = obj_path.strip('.').split('.') if obj_path else []

    return (path, namespace, objpath, base)



class MatlabDocumenter(PyDocumenter):
    """
    Base class for documenters of MATLAB objects.
    """
    domain = 'mat'

    def __repr__(self) -> str:
        return '<Autodocumenter [%s] %s>' % (self.objtype, self.name)

    def generate(
        self,
        more_content: Optional[StringList] = None,
        all_members: bool = False
    ) -> None:
        """Generate reST for the object given by *self.name*, and possibly for
        its members.

        If *more_content* is given, include that content. If *real_modname* is
        given, use that module name to find attribute docs. If *check_module* is
        True, only generate if the object is defined in the module name it is
        imported from. If *all_members* is True, document all members.
        """
        if self.env.config.matlab_src_dir is None:
            # The module is the same folder as the source document
            self.src_path = str(Path(self.directive._reporter.source).parent)
        else:
            # Start looking for the module from the matlab source dir
            self.src_path = Path(self.env.config.matlab_src_dir)


        if not self.parse_name():
            # need a module to import
            if self.env.config.matlab_src_dir:
                path = self.env.config.matlab_src_dir
            else:
                path = str(Path(self.directive._reporter.source).parent)
            logger.warning(
                f'don\'t know which module to import for autodocumenting {self.name} when searching in matlab_src_dir: {path} (try placing a "module" or "currentmodule" directive in the document)'
            )
            return

        # now, import the module and get object to document
        if not self.import_object():
            return

        # make sure that the result starts with an empty line.  This is
        # necessary for some situations where another directive preprocesses
        # reST and no starting newline is present
        self.add_line('', '<autodoc>')

        # format the object's signature, if any
        sig = self.format_signature()

        # generate the directive header and options, if applicable
        self.add_directive_header(sig)
        self.add_line('', '<autodoc>')

        # e.g. the module directive doesn't have content
        self.indent += self.content_indent

        # add all content (from docstrings, attribute docs etc.)
        self.add_content(more_content)

        # document members, if possible
        self.document_members(all_members)

    def parse_name(self):
        """Determine what module to import and what attribute to document.

        Returns True and sets *self.modname*, *self.objpath*, *self.fullname*,
        *self.args* and *self.retann* if parsing and resolving was successful.
        """
        # first, parse the definition -- auto directives for classes and
        # functions can contain a signature which is then used instead of
        # an autogenerated one
        try:
            (path, self.namespace, objpath, base) = parse_matlab_path(self.name)

        except AttributeError:
            logger.warning(f'{MAT_DOM}: invalid signature for auto {self.objtype} ({self.name})')
            return False

        # In the reference object, the modname refers to the python module the documenter is
        # currently in, and the objpath contains a list from the main object to the child target.

        # The MATLAB equivalent of the modname is the path to the MATLAB file or to the main package
        # or class folder. In other words, if modname is in the MATLAB path, then the object
        # (function, class, script that may or may not be inside a package or class folder) is
        # callable. The objpath then contains the directory list of the package/class folder + the
        # final of the file.

        self.modname, self.objpath = self.resolve_name(path, self.namespace, objpath, base)

        if not self.modname:
            return False

        self.fullname = '.'.join(self.namespace + self.objpath) or ''

        return True

    def import_object(self):
        """Import the object given by *self.modname* and *self.objpath* and set
        it as *self.object*.

        Returns True if successful, False if an error occurred.
        """
        try:
            if self.objpath is None:
                msg = f'[{MAT_DOM}] import {self.modname}'
            else:
                msg = f'[{MAT_DOM}] from {self.modname} import {".".join(self.objpath)}'
            logger.debug(msg)

            if self.objtype in {'function', 'class', 'script'}:
                if len(self.objpath) != 1:
                    logger.warning(f'{MAT_DOM} cannot import {".".join(self.objpath)}, which is not a {self.objtype}.')
                    return None

                self.object = self.import_m_file(self.objpath[0], self.objtype, self.modname)
                return True if self.object else False

            elif self.objtype in {'property', 'method'}:
                if self.object:
                    return True
                else:
                    cls = self.import_m_file(self.objpath[0], 'class', self.modname)
                    if cls:
                        self.object = cls.members.get(self.objpath[1])
                        return True if self.object else False
                    else:
                        return False
            # TODO elif mlapp method property...
            else:
                logger.warning(f'{MAT_DOM} could not import {self.objtype} {self.objpath}.')
                return False

        # this used to only catch SyntaxError, ImportError and AttributeError,
        # but importing modules with side effects can raise all kinds of errors
        except Exception as exc:

            logger.warning(exc.args[0], type='autodoc', subtype='import_object')
            self.env.note_reread()
            return False

    def import_m_file(self, name: str, objtype: str, modname: str) -> MatObject:

        mfilepath = Path(modname) / (name + '.m')
        mfile = str(mfilepath)

        if not mfilepath.is_file():
            logger.warning(f'{MAT_DOM} cannot import {objtype} {name}. File does not exist.')
            return None

        if self.env.app.mat_objects.get(mfile):
            # Load MatObject if previously already imported
            logger.debug(f'[{MAT_DOM}] {objtype} {name} already loaded.')
            object =  self.env.app.mat_objects.get(mfile)

        else:
            # Import object and tokenize as MatObject
            logger.debug(f'[{MAT_DOM}] parsing {objtype} {name}.')
            mfilepath = Path(modname) / (name + '.m')
            mfile = str(mfilepath)

            # Handle not found in glob from matlab src dir. Save handle path/modname
            if str(mfilepath) not in self.env.app.mat_handles[name]:
                self.env.app.mat_handles[name].append(str(mfilepath))

            if not mfilepath.is_file():
                logger.warning(f'{MAT_DOM} cannot import {objtype} {name}. File does not exist.')
                return None

            if objtype == 'class':
                object = MatClass(name, module=modname, file=mfile)
                # Import bases
                for baseName in object.bases:
                    baseModname = str(Path(self.env.app.mat_handles[baseName][-1]).parent)
                    self.import_m_file(name=baseName, objtype='class', modname=baseModname)

            elif objtype == 'function':
                object = MatFunction(name, module=modname, file=mfile)
            elif objtype == 'script':
                object = MatScript(name, module=modname, file=mfile)
            else:
                return None
            self.env.app.mat_objects[mfile] = object

        return object

    def add_content(self, more_content, get_doc=True):
        """Add content from docstrings, attribute documentation and user."""

        sourcename = 'docstring of %s' % self.fullname

        # add content from docstrings
        if get_doc:
            docstrings = self.get_doc()
            # append at least a dummy docstring, so that the event autodoc-process-docstring
            # is fired and can add some content if desired
            if not docstrings:
                docstrings = [[]]

        if docstrings and docstrings != [[]]:
            processed_doc = list(self.process_doc(docstrings))
            for i, line in enumerate(self.alter_processed_doc(processed_doc)):
                self.add_line(line, sourcename, i)

        # add additional content (e.g. from document), if present
        if more_content:
            for line, src in zip(more_content.data, more_content.items):
                self.add_line(line, src[0], src[1])

    def alter_processed_doc(self, doc: list):
        """
        Can be used to alter the processed docstring per documenter.
        """
        return doc

    def document_members(self, *args, **kwargs):
        pass


#############################################


class MatModuleLevelDocumenter(MatlabDocumenter):
    """
    Specialized Documenter subclass for objects on module level (functions,
    classes, scripts, mlapps).
    """
    supported_file_extensions = ['', '.m', 'mlapp']

    def resolve_name(self, path: str, namespace: List[str], objpath: List[str], base: str):

        file_path = self.src_path.joinpath(path if path else '', *namespace)

        if file_path.is_dir():
            modname = str(file_path)
        else:
            # if documenting a toplevel object without explicit path,
            # it can be contained in another auto directive ...
            modname = self.env.temp_data.get('autodoc:module')
            if not modname:
                modname = self.env.temp_data.get('mat:module')

            if path or namespace:
                file_path = Path(modname).joinpath(path, *namespace)
                if file_path.is_dir():
                    modname = str(file_path)
                else:
                    modname = None

        return modname, objpath + [base]


class MatClassLevelDocumenter(MatlabDocumenter):
    """
    Specialized Documenter subclass for objects on class level (methods,
    attributes).
    """
    # def resolve_name(self, modname, parents, path, base):
    def resolve_name(self, path: str, namespace: List[str], objpath: List[str], base: str):

        if not objpath:

            try:
                clsname = self.object.cls.name
            except:
                 # if documenting a class-level object without path, there must be a current class, 
                 # either from a parent auto directive or from a class directive.
                clsname = self.env.temp_data.get('autodoc:class')
                if not clsname:
                    clsname = self.env.temp_data.get('mat:class')
                if not clsname:
                    return None, []
            objpath = [clsname]

        if path or namespace:
            modname, _ = MatModuleLevelDocumenter.resolve_name(self, path, namespace, [], '')

        else:
            try: 
                modname = self.object.cls.module
            except:
                # if the module name is still missing, get it like above
                # ... else, it stays None, which means invalid
                modname = self.env.temp_data.get('autodoc:module')
                if not modname:
                    modname = self.env.temp_data.get('mat:module')
                if not modname:
                    cls_path = self.env.app.mat_handles.get(objpath[0])[0]
                    if cls_path:
                        modname = str(Path(cls_path).parent)

        return modname, objpath + [base]


class MatMembersMixin:

    def document_members(self, all_members: bool= False):
        """Generate reST for member documentation.

        If *all_members* is True, do all members, else those given by
        *self.options.members*.
        """
        # set current namespace for finding members
        self.env.temp_data['autodoc:module'] = self.modname
        if self.objpath:
            self.env.temp_data['autodoc:class'] = self.objpath[0]

        want_all = all_members or self.options.inherited_members or self.options.members is ALL

        # find out which members are documentable
        members = self.get_object_members(want_all)
        filtered_members = self.filter_members(members, want_all)

        # document non-skipped members
        memberdocumenters = []

        for (membername, member) in filtered_members:

            # give explicitly separated module name, so that members of inner classes can be documented
            full_membername = '.'.join(self.objpath + [membername])

            documenter_cls = DOCUMENTER_MAP.get(type(member))
            if not documenter_cls:
                logger.warning('{%s} could not document %s.' % (MAT_DOM, full_membername))
                continue

            documenter = documenter_cls(self.directive, full_membername, self.indent)
            documenter.object = member
            memberdocumenters.append(documenter)

        #################################################################################
        # Sort members

        member_order = self.options.member_order or self.env.config.autodoc_member_order
        if member_order == 'alphabetical':
            memberdocumenters.sort(key=lambda e: e.object.name)

        if member_order == 'groupwise':
            # relies on stable sort to keep items in the same group sorted alphabetically
            memberdocumenters.sort(key=lambda e: e.member_order)

        elif member_order == 'bysource':
            # sort by source order, by virtue of the module analyzer
            
            self_memberdocumenters, inherited_memberdocumenters = [], []
            for documenter in memberdocumenters:
                if documenter.object.cls is self.object:
                    self_memberdocumenters.append(documenter)
                else:
                    inherited_memberdocumenters.append(documenter)
            
            # Show first the members of the class itself
            self_memberdocumenters.sort(key=lambda e: e.object.index)

            # Then show the inherited members, sorted alphabetically on the class name and then the index
            inherited_memberdocumenters.sort(key=lambda e: (e.object.cls.name, e.object.index))

            memberdocumenters = self_memberdocumenters + inherited_memberdocumenters

        else:
            logger.warning('{%s} cannot sort members by %s.' % (MAT_DOM, member_order))

        for documenter in memberdocumenters:
            documenter.generate(all_members=True)

        # reset current objects
        self.env.temp_data['autodoc:module'] = None
        self.env.temp_data['autodoc:class'] = None


    def get_object_members(self, *args, **kwargs):
        """Return `(members_check_module, members)` where `members` is a
        list of `(membername, member)` pairs of the members of *self.object*.
        """

        # Get members
        if self.options.members is ALL:
            members = [(key, value) for key, value in self.object.members.items()]
        else:
            members = []
            for membername in self.options.members:
                if membername in self.object.members:
                    members.append((membername, self.object.members[membername]))
                else:
                    logger.warning(
                        '{%s} missing member %s in object %s' % (MAT_DOM, membername, self.fullname)
                    )

        # Get inherited members
        if self.options.inherited_members:
            inherited_members, inherited_constructor = self.get_inherited_members(
                self.object.bases, recursive=True
            )
            if not self.object.constructor:
                self.object.constructor = inherited_constructor

            if self.options.inherited_members is ALL:
                members += [(key, value) for key, value in inherited_members.items()]
            else:
                for membername in self.options.inherited_members:
                    if membername in inherited_members:
                        members.append((membername, inherited_members[membername]))
                    else:
                        logger.warning(
                            '{%s} missing inherited member %s in object %s' %
                            (MAT_DOM, membername, self.fullname)
                        )

        # Add constructor to members list
        if self.object.constructor:
            members.append((self.object.constructor.name, self.object.constructor))

        # remove members given by exclude-members
        if self.options.exclude_members:
            members = [
                (membername, member)
                for (membername, member) in members if membername not in self.options.exclude_members
            ]

        return members


    def get_inherited_members(self, bases: List[str], recursive: bool = True) -> dict:
        """Returns the dict of members of a list of bases (superclasses). 
        If the recursive option is enabled, the search will occur recursivly on the bases of the bases. 
        """
        members, constructor = {}, None
        bases.reverse() # Reverse required for correct MRO
        for base in bases:
            if base in self.env.app.mat_handles:

                # Multiple handles found, guessing by taking the longest common path
                if len(self.env.app.mat_handles[base]) > 1:

                    logger.warning(
                        '{%s} multiple superclasses named {%s} found. Try to guess which one to use by longest common path'
                        % (MAT_DOM, base)
                    )

                    common_path_length = [
                        len(os.path.commonpath([self.modname, p]))
                        for p in self.env.app.mat_handles[base]
                    ]
                    path = self.env.app.mat_handles[common_path_length.index(
                        max(common_path_length)
                    )]
                else:
                    path = self.env.app.mat_handles[base][0]

                obj = self.env.app.mat_objects[path]

                # Get inherited members first, then update with new members according to MRO
                if recursive:
                    inherited_members, inherited_constructor = self.get_inherited_members(obj.bases)
                else:
                    inherited_members, inherited_constructor = {}, None
                members.update(inherited_members)
                members.update(obj.members)

                # Get constructor according to MRO
                if not obj.constructor:
                    obj.constuctor = inherited_constructor
                if obj.constructor:
                    constructor = obj.constructor

            else:
                logger.warning(
                    '{%s} cannot find superclass {%s}. Are you sure it is under the matlab_src_dir?'
                    % (MAT_DOM, base)
                )

        return members, constructor


    def filter_members(self, members, want_all):
        """Filter the given member list.

        Members are skipped if

        - they are special methods (except if given explicitly or the
          special-members option is set)
        - they are private (except if given explicitly or the private-members
          option is set)
        - they are protected (except if given explicitly or the protected-members
          option is set)
        - they are hidden (except if given explicitly or the hidden-members
          option is set)
        - they are friend (except if given explicitly or the friend-members
          option is set)

        - they are undocumented (except if the undoc-members option is set)

        The user can override the skipping decision by connecting to the
        ``autodoc-skip-member`` event.
        """

        def keep_member(membername, member_option, has_doc):
            if member_option is ALL or (isinstance(member_option, set) and membername in member_option):
                return has_doc or self.options.undoc_members
            else:
                return False

        filtered_members = []

        # process members and determine which to skip
        for (membername, member) in members:
            # if isattr is True, the member is documented as an attribute
            has_doc = bool(member.docstring)

            if want_all:
                if self.member_is_private(member):
                    keep = keep_member(membername, self.options.private_members, has_doc)
                elif self.member_is_protected(member):
                    keep = keep_member(membername, self.options.protected_members, has_doc)
                elif self.member_is_hidden(member):
                    keep = keep_member(membername, self.options.hidden_members, has_doc)
                elif self.member_is_special(member):
                    keep = keep_member(membername, self.options.special_members, has_doc)
                elif self.member_is_friend(member):
                    keep = keep_member(membername, self.options.friend_members, has_doc)
                else:
                    keep = has_doc or self.options.undoc_members
            else:
                keep = has_doc or self.options.undoc_members

            if keep:
                filtered_members.append((membername, member))

            # give the user a chance to decide whether this member should be skipped
            if self.env.app:
                # let extensions preprocess docstrings
                skip_user = self.env.app.emit_firstresult(
                    'autodoc-skip-member', self.objtype, membername, member, not keep, self.options)
                if skip_user is not None:
                    keep = not skip_user

        return filtered_members

    @staticmethod
    def member_is_special(member: Union[MatMethod, MatProperty]):
        '''Checks if a method is special (overwriting default behavior)
        See https://www.mathworks.com/help/matlab/matlab_oop/methods-that-modify-default-behavior.html
        '''
        if isinstance(member, MatMethod) and member.name in {
            'cat', 'horzcat', 'vertcat', 'empty', 'display', 'disp', 'double', 'char', 'loadobj',
            'saveobj', 'permute', 'transpose', 'ctranspose', 'reshape', 'repmat', 'isscalar',
            'isvector', 'ismatrix', 'isempty'
        }:
            return True
        else:
            return False

    @staticmethod
    def member_is_private(member: Union[MatMethod, MatProperty]):
        '''Checks if a method or property's Access or GetAccess is private.'''
        if member.attrs.get('Access') == 'private' or member.attrs.get('GetAccess') == 'private':
            return True
        else:
            return False

    @staticmethod
    def member_is_protected(member: Union[MatMethod, MatProperty]):
        '''Checks if a method or property's Access or GetAccess is protected.'''
        if member.attrs.get('Access') == 'protected' or member.attrs.get('GetAccess') == 'protected':
            return True
        else:
            return False

    @staticmethod
    def member_is_hidden(member: Union[MatMethod, MatProperty]):
        '''Checks if a method or property is hidden.'''
        return True if member.attrs.get('Hidden') else False

    @staticmethod
    def member_is_friend(member: Union[MatMethod, MatProperty], friends: Optional[list] = None):
        '''Checks if a method or property has an access list and that it a member of the "friend_members".
        See https://www.mathworks.com/help/matlab/matlab_oop/selective-access-to-class-methods.html
        '''
        access_list = []
        access = member.attrs.get('Access')
        getacces = member.attrs.get('GetAccess')
        access_list += access if isinstance(access, list) else []
        access_list += getacces if isinstance(getacces, list) else []

        if access_list:

            if friends is ALL:
                return True
            elif isinstance(friends, list):
                return True if any([cls[1:] in access_list for cls in friends]) else False
            else:
                return False
        else:
            return False


class MatArgumentMixin:
    """
    Mixin for FunctionDocumenter and MethodDocumenter to provide the
    feature of reading the signature from the docstring.
    """

    def format_signature(self):
        if self.env.config.autodoc_docstring_signature:
            sig = f'({", ".join(self.object.args)})' if self.object.args else ''
            if self.object.retv:
                sig += f' -> [{", ".join(self.object.retv)}]'
        else:
            sig = ''

        return sig

    def alter_processed_doc(self, doc: list):

        use_args = self.env.config.matlab_argument_docstrings
        if self.options.get('invert-conf-argument-docstring', False):
            use_args = not use_args
        if not use_args:
            return doc

        # Tokenize parsed RST document
        tks = RstLexer().get_tokens('\n'.join(doc)) if doc else None
        newDoc, line = [], ''

        # Add lines until first field is encountered
        token = next(tks, None)
        while token and token[0] is not Token.Name.Class:
            if token == (Token.Text.Whitespace, '\n') or token == (Token.Text, '\n'):
                newDoc.append(line)
                line = ''
            else:
                line += token[1]
            token = next(tks, None)

        fields_to_skip = []

        # Add documentation via argument (Input) block
        if self.object.args_block:
            if newDoc and newDoc[-1] != '':
                newDoc.append('')

            for iArg, (argName, args) in enumerate(self.object.args_block.items()):

                fields_to_skip.append(f':param {argName}:')
                fields_to_skip.append(f':type {argName}:')

                if len(args) > 1:
                    line = '          * ' if iArg else ':parameters: * '
                    line += f'{argName} (``struct``)'
                    newDoc.append(line)

                for arg in args:

                    if len(args) == 1:
                        line = '          * ' if iArg else ':parameters: * '
                    else:
                        line = '             * '
                        fields_to_skip.append(f':param {arg.name}.{arg.field}:')
                        fields_to_skip.append(f':type {arg.name}.{arg.field}:')

                    line += f'**{argName}.{arg.field}**' if arg.field else f'**{argName}**'

                    # Add typehint
                    repeating = arg.attrs.get('Repeating', False)
                    if arg.type or arg.default or repeating:
                        codeblock = []
                        if arg.type:
                            codeblock.append(arg.type)
                        if arg.default:
                            codeblock.append('optional')
                        if repeating:
                            codeblock.append('repeating')
                        line += f" (``{', '.join(codeblock)}``)"

                    # Add docstring
                    if arg.docstring:
                        line += f' -- {arg.docstring}'
                        if line[-1] not in ['.', '!']:
                            line += '.'

                    newDoc.append(line)
                newDoc.append('')
            newDoc.append('')

        # Add documentation via argument (Output) block
        if self.object.retv_block:
            if newDoc[-1] != '':
                newDoc.append('')

            for iArg, args in enumerate(self.object.retv_block.values()):
                arg = args[0]

                line = '          * ' if iArg else ':returns: * '
                line += f'**{arg.name}**'

                # Add typehint
                if arg.type:
                    line += f' (``{arg.type}``)'

                if arg.docstring:
                    line += f' -- {arg.docstring}'

                newDoc.append(line)
            newDoc.append('')
            fields_to_skip += [':returns:', ':rtype:']

        # Add back remaining tokens
        skip_to_next_field, line = False, ''
        while token:
            # Skip argument and return fields if added in argument blocks
            if token[0] is Token.Name.Class:
                skip_to_next_field = True if token[1] in fields_to_skip else False
            if skip_to_next_field:
                token = next(tks, None)
                continue

            if token[1] == '\n':
                newDoc.append(line)
                line = ''
            else:
                line += token[1]
            token = next(tks, None)

        return newDoc


class MatModuleDocumenter(MatMembersMixin, MatlabDocumenter, PyModuleDocumenter):

    def parse_name(self):

        if self.env.config.matlab_src_dir is None:
            # The module is the same folder as the source document
            src_path = Path(self.directive._reporter.source).parent
        else:
            # Start looking for the module from the matlab source dir
            src_path = Path(self.env.config.matlab_src_dir)

        mod_path = src_path / Path(self.name)

        if mod_path.is_dir():
            self.modname = str(mod_path)
            return True
        else:
            return False

    def add_directive_header(self, sig):
        super().add_directive_header(sig)

        # add some module-specific options
        if self.options.synopsis:
            self.add_line(
                '   :synopsis: ' + self.options.synopsis, '<autodoc>')
        if self.options.platform:
            self.add_line(
                '   :platform: ' + self.options.platform, '<autodoc>')
        if self.options.deprecated:
            self.add_line('   :deprecated:', '<autodoc>')

    def get_object_members(self, want_all):
        if want_all:
            if not hasattr(self.object, '__all__'):
                # for implicit module members, check __module__ to avoid
                # documenting imported objects
                return True, self.object.safe_getmembers()
            else:
                memberlist = self.object.__all__
        else:
            memberlist = self.options.members or []
        ret = []
        for membername in memberlist:
            try:
                attr = self.get_attr(self.object, membername, None)
                if attr:
                    ret.append((membername, attr))
                else:
                    raise AttributeError
            except AttributeError:
                logger.warning(
                    'missing attribute mentioned in :members: or __all__: '
                    'module %s, attribute %s' % (
                    sphinx.util.inspect.safe_getattr(self.object, '__name__', '???'), membername))
        return False, ret


class MatClassDocumenter(MatMembersMixin, MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for classes.
    """
    objtype = 'class'
    member_order = 20
    option_spec = {
        'members': members_option, 'undoc-members': bool_option,
        'noindex': bool_option, 'show-inheritance': bool_option,
        'member-order': member_order_option, 'inherited-members': members_option,
        'exclude-members': exclude_members_option, 'special-members': members_option,
        'private-members': members_option, 'protected-members': members_option,
        'hidden-members': members_option, 'friend-members': members_option,
    }

    def format_signature(self):

        # get constructor method signature from docstring
        constructor = self.object.methods.get(self.object.name)
        if self.env.config.autodoc_docstring_signature and constructor:
            sig = f'({", ".join(constructor.args)})'
        else:
            sig = ''

        return sig

    def add_directive_header(self, sig):

        super(MatlabDocumenter, self).add_directive_header(sig)

        # add inheritance info, if wanted
        if self.options.show_inheritance:
            self.add_line('', '<autodoc>')

            base_class_links = []
            if len(self.object.bases):

                for base in self.object.bases:
                    base_namespace = base.split('.')
                    if len(base_namespace) == 1:
                        base_directive = base
                    else:
                        base_directive = '.'.join(['+%s' % n for n in base_namespace[:-1]] + [base_namespace[-1]])
                    base_class_links.append(':class:`%s`' % base_directive)

            if base_class_links:
                self.add_line(_('   Bases: %s') % ', '.join(base_class_links), '<autodoc>')

    def get_doc(self):

        class_docstring = self.object.docstring

        if self.object.name in self.object.methods:
            constructor_docstring = self.object.methods[self.object.name].docstring
        else:
            constructor_docstring = None

        docstrings = []
        content = self.env.config.autoclass_content

        if content == 'class' and class_docstring:
            docstrings.append(class_docstring)
        elif content == "constructor" and constructor_docstring:
            docstrings.append(constructor_docstring)
        else: # if content == 'both'
            if class_docstring and constructor_docstring:
                docstrings.append(class_docstring)
                docstrings.append('Constructor\n-----------')
                docstrings.append(constructor_docstring)
            elif class_docstring:
                docstrings.append(class_docstring)
            elif constructor_docstring:
                docstrings.append(constructor_docstring)

        doc = []
        for docstring in docstrings:
            doc.append(sphinx.util.docstrings.prepare_docstring(docstring))
        return doc


class MatFunctionDocumenter(MatArgumentMixin, MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for functions.
    """
    objtype = 'function'
    member_order = 30
    option_spec = {'invert-conf-argument-docstring': bool_option}


class MatMethodDocumenter(MatArgumentMixin, MatClassLevelDocumenter):
    """
    Specialized Documenter subclass for methods (normal, static and class).
    """
    objtype = 'method'
    member_order = 50
    priority = 1  # must be more than FunctionDocumenter


    def import_object(self):
        ret = super().import_object()
        if self.object.attrs.get('Static'):
            self.directivetype = 'staticmethod'
            # document class and static members before ordinary ones
            self.member_order = self.member_order - 1
        else:
            self.directivetype = 'method'
        return ret

    def document_members(self, *args, **kwargs):
        pass


class MatPropertyDocumenter(MatClassLevelDocumenter):
    """
    Specialized Documenter subclass for properties.
    """
    objtype = 'property'
    member_order = 60
    option_spec = dict(MatModuleLevelDocumenter.option_spec)
    option_spec["annotation"] = annotation_option

    # must be higher than the MethodDocumenter, else it will recognize
    # some non-data descriptors as methods
    priority = 10

    def document_members(self, *args, **kwargs):
        pass

    def import_object(self):
        ret = super().import_object()
        # getset = self.object.name.split('_')

        if isinstance(self.object, MatMethod):
            self._datadescriptor = True
        else:
            # if it's not a data descriptor
            self._datadescriptor = False
        return ret

    def get_real_modname(self):
        return self.get_attr(self.parent or self.object, '__module__', None) \
               or self.modname

    def add_directive_header(self, sig):
        super().add_directive_header(sig)
        if not self.options.annotation:
            if not self._datadescriptor:
                try:
                    objrepr = sphinx.util.inspect.object_description(self.object.default)  # display default
                except ValueError:
                    pass
                else:
                    line = '   :annotation: = ' + objrepr
                    if self.object.attrs.get('Constant', False):
                        line += ', constant'
                    self.add_line(line, '<autodoc>')
        elif self.options.annotation is SUPPRESS:
            pass
        else:
            self.add_line('   :annotation: %s' % self.options.annotation,
                          '<autodoc>')


class MatScriptDocumenter(MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for scripts.
    """
    objtype = 'script'

    def document_members(self, *args, **kwargs):
        pass


class MatApplicationDocumenter(MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for Matlab Applications (.mlapp)
    """
    objtype = 'application'

    def document_members(self, *args, **kwargs):
        pass


DOCUMENTER_MAP = {
    MatModule: MatModuleDocumenter,
    MatClass: MatClassDocumenter,
    MatFunction: MatFunctionDocumenter,
    MatMethod: MatMethodDocumenter,
    MatProperty: MatPropertyDocumenter,
    MatScript: MatScriptDocumenter,
    MatApplication: MatApplicationDocumenter
}