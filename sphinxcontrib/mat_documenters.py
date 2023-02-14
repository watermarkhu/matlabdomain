# -*- coding: utf-8 -*-
"""
    sphinxcontrib.mat_documenters
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Extend autodoc directives to matlabdomain.

    :copyright: Copyright 2014 Mark Mikofski
    :license: BSD, see LICENSE for details.
"""
from .mat_types import (
    MatModule, MatFunction, MatClass, MatProperty, MatMethod, MatScript, MatApplication, 
    modules, import_matlab_type
)

import os
import re
import traceback
import inspect

from docutils.statemachine import ViewList

import sphinx.util
from sphinx.locale import _
from sphinx.pycode import PycodeError
from sphinx.ext.autodoc import py_ext_sig_re as mat_ext_sig_re, \
    identity, Options, ALL, INSTANCEATTR, members_option, \
    SUPPRESS, annotation_option, bool_option, \
    Documenter as PyDocumenter, \
    ModuleDocumenter as PyModuleDocumenter, \
    FunctionDocumenter as PyFunctionDocumenter, \
    ClassDocumenter as PyClassDocumenter, \
    ExceptionDocumenter as PyExceptionDocumenter, \
    DataDocumenter as PyDataDocumenter, \
    MethodDocumenter as PyMethodDocumenter
from pygments.lexers.markup import RstLexer
from pygments.token import Token


mat_ext_sig_re = re.compile(            # QUESTION why is it required to have the explicit module name
    r'''^ ([+@]?[+@\w.]+::)?            # explicit module name 
          ([+@]?[+@\w.]+\.)?            # module and/or class name(s)
          ([+@]?\w+)  \s*               # thing name
          (?: \((.*)\)                  # optional: arguments
           (?:\s* -> \s* (.*))?         #           return annotation
          )? $                          # and nothing more
          ''', re.VERBOSE)              # QUESTION are the optional arguments and return annotation ever used? -> yes in

# TODO: check MRO's for all classes, attributes and methods!!!


logger = sphinx.util.logging.getLogger('matlab-domain')


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
        obj = cls(None, modname, dirname)
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

    def __init__(self, source, modname, srcname):
        
        self.modname = modname      # name of the module
        self.srcname = srcname      # name of the source file
        self.source = source        # file-like object yielding source lines

        # will be filled by find_attr_docs()
        self.attr_docs = None
        self.tagorder = None

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


class MatlabDocumenter(PyDocumenter):
    """
    Base class for documenters of MATLAB objects.
    """
    domain = 'mat'

    def parse_name(self):
        """Determine what module to import and what attribute to document.

        Returns True and sets *self.modname*, *self.objpath*, *self.fullname*,
        *self.args* and *self.retann* if parsing and resolving was successful.
        """
        # first, parse the definition -- auto directives for classes and
        # functions can contain a signature which is then used instead of
        # an autogenerated one
        try:
            explicit_modname, path, base, args, retann = \
                 mat_ext_sig_re.match(self.name).groups()
        except AttributeError:
            logger.warn('invalid signature for auto%s (%r)' %
                                (self.objtype, self.name))
            return False

        # support explicit module and class name separation via ::
        if explicit_modname is not None:
            modname = explicit_modname[:-2]
            parents = path and path.rstrip('.').split('.') or []
        else:
            modname = None
            parents = []

        self.modname, self.objpath = self.resolve_name(modname, parents, path, base)

        if not self.modname:
            return False

        self.args = args
        self.retann = retann
        self.fullname = (self.modname or '') + \
                        (self.objpath and '.' + '.'.join(self.objpath) or '')
        return True

    def import_object(self):
        """Import the object given by *self.modname* and *self.objpath* and set
        it as *self.object*.

        Returns True if successful, False if an error occurred.
        """

        if self.env.config.matlab_relative_src_path:
            # Get relative path with respect to reporting source file
            basedir = os.path.split(self.directive._reporter.source)[0]
        else:
            # get config_value with absolute path to MATLAB source files
            basedir = self.env.config.matlab_src_dir

        if self.modname == "*":
            # Direct search is enabled. Module is equal to src folder.
            (basedir, self.modname) = os.path.split(basedir)

        if self.objpath:
            logger.debug('[sphinxcontrib-matlabdomain] from %s import %s',
                         self.modname, '.'.join(self.objpath))
        try:
            logger.debug('[sphinxcontrib-matlabdomain] import %s', self.modname)
            import_matlab_type(self.modname, basedir)
            parent = None
            obj = self.module = modules[self.modname]
            logger.debug('[sphinxcontrib-matlabdomain] => %r', obj)
            for part in self.objpath:
                parent = obj
                logger.debug('[sphinxcontrib-matlabdomain] getattr(_, %r)', part)
                obj = self.get_attr(obj, part)
                logger.debug('[sphinxcontrib-matlabdomain] => %r', obj)
                self.object_name = part

            if obj:
                self.parent = parent
                self.object = obj
                return True
            else:
                errmsg = '[sphinxcontrib-matlabdomain]: could not find %s %r in module %r' % \
                         (self.objtype, '.'.join(self.objpath), self.modname)
                logger.warning(errmsg)
                return False
        # this used to only catch SyntaxError, ImportError and AttributeError,
        # but importing modules with side effects can raise all kinds of errors
        except Exception:
            if self.objpath:
                errmsg = '[sphinxcontrib-matlabdomain]: failed to import %s %r from module %r' % \
                         (self.objtype, '.'.join(self.objpath), self.modname)
            else:
                errmsg = '[sphinxcontrib-matlabdomain]: failed to import %s %r' % \
                         (self.objtype, self.fullname)
            errmsg += '; the following exception was raised:\n%s' % \
                      traceback.format_exc()
            logger.warning(errmsg)
            self.env.note_reread()
            return False

    def add_content(self, more_content, get_doc=True):
        """Add content from docstrings, attribute documentation and user."""
        # set sourcename and add content from attribute documentation
        if self.analyzer:
            # prevent encoding errors when the file name is non-ASCII
            if not isinstance(self.analyzer.srcname, str):
                filename = str(self.analyzer.srcname)
            else:
                filename = self.analyzer.srcname
            sourcename = '%s:docstring of %s' % (filename, self.fullname)

            attr_docs = self.analyzer.find_attr_docs()
            if self.objpath:
                key = ('.'.join(self.objpath[:-1]), self.objpath[-1])
                if key in attr_docs:
                    get_doc = False
                    docstrings = [sphinx.util.docstrings.prepare_docstring(attr_docs[key])]
        else:
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


    def get_object_members(self, want_all):
        """Return `(members_check_module, members)` where `members` is a
        list of `(membername, member)` pairs of the members of *self.object*.

        If *want_all* is True, return all members.  Else, only return those
        members given by *self.options.members* (which may also be none).
        """
        analyzed_member_names = set()
        if self.analyzer:
            attr_docs = self.analyzer.find_attr_docs()  # TODO already called in generate()
            namespace = '.'.join(self.objpath)
            for item in attr_docs.items():
                if item[0][0] == namespace:
                    analyzed_member_names.add(item[0][1])

        if not want_all:
            if not self.options.members:
                return False, []
            # specific members given
            members = []
            for mname in self.options.members:
                try:
                    members.append((mname, self.get_attr(self.object, mname)))
                except AttributeError:
                    if mname not in analyzed_member_names:
                        logger.warn('missing attribute %s in object %s'
                                            % (mname, self.fullname))
        elif self.options.inherited_members:
            # safe_getmembers() uses dir() which pulls in members from all
            # base classes
            members = inspect.get_members(self.object, attr_getter=self.get_attr)
        else:
            # __dict__ contains only the members directly defined in
            # the class (but get them via getattr anyway, to e.g. get
            # unbound method objects instead of function objects);
            # using keys() because apparently there are objects for which
            # __dict__ changes while getting attributes
            try:
                obj_dict = self.get_attr(self.object, '__dict__')
            except AttributeError:
                members = []
            else:
                members = [(mname, self.get_attr(self.object, mname, None))
                           for mname in list(obj_dict.keys())]
        membernames = set(m[0] for m in members)
        # add instance attributes from the analyzer
        for aname in analyzed_member_names:
            if aname not in membernames and \
               (want_all or aname in self.options.members):
                members.append((aname, INSTANCEATTR))
        return False, sorted(members)

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
        def member_is_special(member):
            # TODO implement special matlab methods: disp, subsref, etc.
            return False

        def member_is_private(member):
            attrs = self.get_attr(member, 'attrs', None)
            if attrs:
                access = attrs.get('Access', None)
                get_access = attrs.get('GetAccess', None)
                if access:
                    if access == 'private':
                        return True
                elif get_access:
                    if get_access == 'private':
                        return True
                return False
            else:
                return False

        def member_is_protected(member):
            attrs = self.get_attr(member, 'attrs', None)
            if attrs:
                access = attrs.get('Access', None)
                get_access = attrs.get('GetAccess', None)
                if access:
                    if access == 'protected':
                        return True
                elif get_access:
                    if get_access == 'protected':
                        return True
                return False
            else:
                return False

        def member_is_hidden(member):
            attrs = self.get_attr(member, 'attrs', None)
            if attrs:
                hidden = attrs.get('Hidden', None)
                # It is either None or True
                if hidden:
                    return True
                return False
            else:
                return False

        def member_is_friend(member):
            attrs = self.get_attr(member, 'attrs', None)
            if attrs:
                access = attrs.get('Access', None)
                if access:
                    # Only friend meta classes define access lists
                    if isinstance(access, list):
                        return True
                    elif access:
                        # This is a friend meta class
                        return access[0] == '?'
                return False
            else:
                return False

        def member_is_friend_of(member, friends):
            attrs = self.get_attr(member, 'attrs', None)
            if attrs:
                access = attrs.get('Access', None)
                if not isinstance(access, list):
                    access = [access]
                for has_access in access:
                    if has_access in friends:
                        return True
                else:
                    return False
            else:
                return False

        ret = []

        # search for members in source code too
        namespace = '.'.join(self.objpath)  # will be empty for modules

        if self.analyzer:
            attr_docs = self.analyzer.find_attr_docs()
        else:
            attr_docs = {}

        # process members and determine which to skip
        for (membername, member) in members:
            # if isattr is True, the member is documented as an attribute
            isattr = False

            doc = self.get_attr(member, '__doc__', None)
            # if the member __doc__ is the same as self's __doc__, it's just
            # inherited and therefore not the member's doc
            cls = self.get_attr(member, '__class__', None)
            if cls:
                cls_doc = self.get_attr(cls, '__doc__', None)
                if cls_doc == doc:
                    doc = None
            has_doc = bool(doc)

            keep = False
            if want_all and member_is_special(member):
                # special methods
                if self.options.special_members is ALL:
                    keep = has_doc or self.options.undoc_members
                elif self.options.special_members and \
                    self.options.special_members is not ALL and \
                        membername in self.options.special_members:
                    keep = has_doc or self.options.undoc_members
            elif want_all and member_is_private(member):
                # ignore private members
                if self.options.private_members is ALL:
                    keep = has_doc or self.options.undoc_members
                elif self.options.private_members and \
                    self.options.private_members is not ALL and \
                        membername in self.options.private_members:
                    keep = has_doc or self.options.undoc_members
            elif want_all and member_is_protected(member):
                # ignore protected members
                if self.options.protected_members is ALL:
                    keep = has_doc or self.options.undoc_members
                elif self.options.protected_members and \
                    self.options.protected_members is not ALL and \
                        membername in self.options.protected_members:
                    keep = has_doc or self.options.undoc_members
            elif want_all and member_is_hidden(member):
                # ignore hidden members
                if self.options.hidden_members is ALL:
                    keep = has_doc or self.options.undoc_members
                elif self.options.hidden_members and \
                    self.options.hidden_members is not ALL and \
                        membername in self.options.hidden_members:
                    keep = has_doc or self.options.undoc_members
            elif want_all and member_is_friend(member):
                # ignore friend members
                if self.options.friend_members is ALL:
                    keep = has_doc or self.options.undoc_members
                elif self.options.friend_members and \
                        self.options.friend_members is not ALL and \
                        member_is_friend_of(member, self.options.friend_members):
                    keep = has_doc or self.options.undoc_members
            elif (namespace, membername) in attr_docs:
                # keep documented attributes
                keep = True
                isattr = True
            else:
                # ignore undocumented members if :undoc-members: is not given
                keep = has_doc or self.options.undoc_members

            # give the user a chance to decide whether this member
            # should be skipped
            if self.env.app:
                # let extensions preprocess docstrings
                skip_user = self.env.app.emit_firstresult(
                    'autodoc-skip-member', self.objtype, membername, member,
                    not keep, self.options)
                if skip_user is not None:
                    keep = not skip_user

            if keep:
                ret.append((membername, member, isattr))

        return ret

    def document_members(self, all_members=False):
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
        members_check_module, members = self.get_object_members(want_all)

        # remove members given by exclude-members
        if self.options.exclude_members:
            members = [
                (membername, member)
                for (membername, member) in members if membername not in self.options.exclude_members
            ]

        # document non-skipped members
        memberdocumenters = []
        matdocumenters = [cls for (name, cls) in self.documenters.items() if name.startswith('mat:')]

        for (mname, member, isattr) in self.filter_members(members, want_all):

            # TODO This should just be a one to one mapping

            classes = [cls for cls in matdocumenters if cls.can_document_member(member, mname, isattr, self)]

            if not classes: # don't know how to document this member
                continue

            # prefer the documenter with the highest priority
            classes.sort(key=lambda cls: cls.priority)
            # give explicitly separated module name, so that members
            # of inner classes can be documented
            full_mname = self.modname + '::' + '.'.join(self.objpath + [mname])
            documenter = classes[-1](self.directive, full_mname, self.indent)
            memberdocumenters.append((documenter, isattr))

        #################################################################################
        # Sort members

        member_order = self.options.member_order or self.env.config.autodoc_member_order
        if member_order == 'groupwise':
            # sort by group; relies on stable sort to keep items in the
            # same group sorted alphabetically
            memberdocumenters.sort(key=lambda e: e[0].member_order)
        elif member_order == 'bysource' and self.analyzer:
            # sort by source order, by virtue of the module analyzer
            tagorder = self.analyzer.tagorder

            def keyfunc(entry):
                fullname = entry[0].name.split('::')[1]
                return tagorder.get(fullname, len(tagorder))

            memberdocumenters.sort(key=keyfunc)

        for documenter, isattr in memberdocumenters:
            documenter.generate(
                all_members=True, real_modname=self.real_modname, check_module=members_check_module and not isattr
            )

        # reset current objects
        self.env.temp_data['autodoc:module'] = None
        self.env.temp_data['autodoc:class'] = None

    def generate(self, more_content=None, real_modname=None,
                 check_module=False, all_members=False):
        """Generate reST for the object given by *self.name*, and possibly for
        its members.

        If *more_content* is given, include that content. If *real_modname* is
        given, use that module name to find attribute docs. If *check_module* is
        True, only generate if the object is defined in the module name it is
        imported from. If *all_members* is True, document all members.
        """
        if not self.parse_name():
            # need a module to import
            logger.warn(
                'don\'t know which module to import for autodocumenting '
                '%r (try placing a "module" or "currentmodule" directive '
                'in the document, or giving an explicit module name)'
                % self.name)
            return

        # now, import the module and get object to document
        if not self.import_object():
            return

        # If there is no real module defined, figure out which to use.
        # The real module is used in the module analyzer to look up the module
        # where the attribute documentation would actually be found in.
        # This is used for situations where you have a module that collects the
        # functions and classes of internal submodules.
        self.real_modname = real_modname or self.get_real_modname()

        # try to also get a source code analyzer for attribute docs
        try:
            self.analyzer = MatModuleAnalyzer.for_module(self.real_modname)
            # parse right now, to get PycodeErrors on parsing (results will
            # be cached anyway)
            self.analyzer.find_attr_docs()
        except PycodeError as err:
            self.env.app.debug('[sphinxcontrib-matlabdomain] module analyzer failed: %s', err)
            # no source file -- e.g. for builtin and C modules
            self.analyzer = None
            # at least add the module.__file__ as a dependency
            if hasattr(self.module, '__file__') and self.module.__file__:
                self.directive.record_dependencies.add(self.module.__file__)
        else:
            self.directive.record_dependencies.add(self.analyzer.srcname)

        # check __module__ of object (for members not given explicitly)
        if check_module:
            if not self.check_module():
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


class MatModuleDocumenter(MatlabDocumenter, PyModuleDocumenter):

    def parse_name(self):
        ret = super().parse_name()
        if self.args or self.retann:
            logger.warn('signature arguments or return annotation '
                                'given for automodule %s' % self.fullname)
        return ret

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
        for mname in memberlist:
            try:
                attr = self.get_attr(self.object, mname, None)
                if attr:
                    ret.append((mname, attr))
                else:
                    raise AttributeError
            except AttributeError:
                logger.warn(
                    'missing attribute mentioned in :members: or __all__: '
                    'module %s, attribute %s' % (
                    sphinx.util.inspect.safe_getattr(self.object, '__name__', '???'), mname))
        return False, ret


class MatModuleLevelDocumenter(MatlabDocumenter):
    """
    Specialized Documenter subclass for objects on module level (functions,
    classes, data/constants).
    """
    def resolve_name(self, modname, parents, path, base):
        if modname is None:
            if path:
                modname = path.rstrip('.')
            else:
                # if documenting a toplevel object without explicit module,
                # it can be contained in another auto directive ...
                modname = self.env.temp_data.get('autodoc:module')
                # ... or in the scope of a module directive
                if not modname:
                    modname = self.env.temp_data.get('mat:module')

                if not modname and self.env.config.matlab_direct_search:
                    modname = "*"
                # ... else, it stays None, which means invalid
        return modname, parents + [base]


class MatClassLevelDocumenter(MatlabDocumenter):
    """
    Specialized Documenter subclass for objects on class level (methods,
    attributes).
    """
    def resolve_name(self, modname, parents, path, base):
        if modname is None:
            if path:
                mod_cls = path.rstrip('.')
            else:
                mod_cls = None
                # if documenting a class-level object without path,
                # there must be a current class, either from a parent
                # auto directive ...
                mod_cls = self.env.temp_data.get('autodoc:class')
                # ... or from a class directive
                if mod_cls is None:
                    mod_cls = self.env.temp_data.get('mat:class')
                # ... if still None, there's no way to know
                if mod_cls is None:
                    return None, []
            modname, _,  cls = mod_cls.rpartition('.')
            parents = [cls]
            # if the module name is still missing, get it like above
            if not modname:
                modname = self.env.temp_data.get('autodoc:module')
            if not modname:
                modname = self.env.temp_data.get('mat:module')
            # ... else, it stays None, which means invalid
        return modname, parents + [base]


class MatDocstringSignatureMixin(object):
    """
    Mixin for FunctionDocumenter and MethodDocumenter to provide the
    feature of reading the signature from the docstring.
    """

    def _find_signature(self):
        docstrings = MatlabDocumenter.get_doc(self)
        if len(docstrings) != 1:
            return
        doclines = docstrings[0]
        setattr(self, '__new_doclines', doclines)
        if not doclines:
            return
        # match first line of docstring against signature RE
        match = mat_ext_sig_re.match(doclines[0])
        if not match:
            return
        exmod, path, base, args, retann = match.groups()
        # the base name must match ours
        if not self.objpath or base != self.objpath[-1]:
            return
        # re-prepare docstring to ignore indentation after signature
        docstrings = MatlabDocumenter.get_doc(self)
        doclines = docstrings[0]
        # ok, now jump over remaining empty lines and set the remaining
        # lines as the new doclines
        i = 1
        while i < len(doclines) and not doclines[i].strip():
            i += 1
        setattr(self, '__new_doclines', doclines[i:])
        return args, retann

    def get_doc(self):
        lines = getattr(self, '__new_doclines', None)
        if lines is not None:
            return [lines]
        return MatlabDocumenter.get_doc(self)

    def format_signature(self):
        if self.args is None and self.env.config.autodoc_docstring_signature:
            # only act if a signature is not explicitly given already, and if
            # the feature is enabled
            result = self._find_signature()
            if result is not None:
                self.args, self.retann = result
        return MatlabDocumenter.format_signature(self)

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


class MatFunctionDocumenter(MatDocstringSignatureMixin, MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for functions.
    """
    objtype = 'function'
    member_order = 30
    option_spec = {'invert-conf-argument-docstring': bool_option}

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return type(member) is MatFunction

    def format_args(self):
        if self.object.args:
            return '(' + ', '.join(self.object.args) + ')'
        else:
            return None

    def document_members(self, *args, **kwargs):
        pass


def make_baseclass_links(obj):
    """ Returns list of base class links """
    obj_bases = obj.__bases__
    links = []
    if len(obj_bases):
        base_classes = obj_bases.items()
        for b, v in base_classes:
            if not v:
                links.append(':class:`%s`' % b)
            else:
                mod_name = v.__module__
                if mod_name.startswith('+'):
                    links.append(':class:`+%s`' % b)
                else:
                    links.append(':class:`%s.%s`' % (mod_name, b))
    return links


class MatClassDocumenter(MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for classes.
    """
    objtype = 'class'
    member_order = 20
    option_spec = {
        'members': members_option, 'undoc-members': bool_option,
        'noindex': bool_option, 'inherited-members': bool_option,
        'show-inheritance': bool_option, 'member-order': identity,
        'exclude-members': members_option, 'special-members': members_option,
        'private-members': members_option, 'protected-members': members_option,
        'hidden-members': members_option,
        'friend-members': members_option,
    }

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return isinstance(member, MatClass)

    def import_object(self):
        ret = super().import_object()
        # if the class is documented under another name, document it
        # as data/attribute
        if ret:
            if hasattr(self.object, '__name__'):
                self.doc_as_attr = (self.objpath[-1] != self.object.__name__)
            else:
                self.doc_as_attr = True
        return ret

    def format_args(self):
        # for classes, the relevant signature is the "constructor" method,
        # which has the same name as the class definition
        initmeth = self.get_attr(self.object, self.object.name, None)
        # classes without constructor method, default constructor or
        # constructor written in C?
        if initmeth is None or not isinstance(initmeth, MatMethod):
            return None
        if initmeth.args:
            if initmeth.args[0] == 'obj':
                return '(' + ', '.join(initmeth.args[1:]) + ')'
            else:
                return '(' + ', '.join(initmeth.args) + ')'
        else:
            return None

    def format_signature(self):
        if self.doc_as_attr:
            return ''

        # get constructor method signature from docstring
        if self.env.config.autodoc_docstring_signature:
            # only act if the feature is enabled
            init_doc = MatMethodDocumenter(self.directive, self.object.name)
            init_doc.object = self.get_attr(self.object, self.object.name, None)
            init_doc.objpath = [self.object.name]
            result = init_doc._find_signature()
            if result is not None:
                # use args only for Class signature
                return '(%s)' % result[0]

        return super().format_signature()

    def add_directive_header(self, sig):
        if self.doc_as_attr:
            self.directivetype = 'attribute'
        super(MatlabDocumenter, self).add_directive_header(sig)

        # add inheritance info, if wanted
        if not self.doc_as_attr and self.options.show_inheritance:
            self.add_line('', '<autodoc>')
            base_class_links = make_baseclass_links(self.object)
            if base_class_links:
                self.add_line(_('   Bases: %s') % ', '.join(base_class_links), '<autodoc>')

    def get_doc(self):
        content = self.env.config.autoclass_content

        docstrings = []
        attrdocstring = self.get_attr(self.object, '__doc__', None)
        if attrdocstring:
            docstrings.append(attrdocstring)

        # for classes, what the "docstring" is can be controlled via a
        # config value; the default is only the class docstring
        if content in ('both', 'init'):
            # get __init__ method document from __init__.__doc__
            if self.env.config.autodoc_docstring_signature:
                # only act if the feature is enabled
                init_doc = MatMethodDocumenter(self.directive, self.object.name)
                init_doc.object = self.get_attr(self.object, self.object.name,
                                                None)
                init_doc.objpath = [self.object.name]
                init_doc._find_signature()  # this effects to get_doc() result
                initdocstring = '\n'.join(
                    ['\n'.join(l) for l in init_doc.get_doc()])
            else:
                initdocstring = self.get_attr(
                    self.get_attr(self.object, self.object.name, None),
                    '__doc__')
            # for new-style classes, no __init__ means default __init__
            if initdocstring == object.__init__.__doc__:
                initdocstring = None
            if initdocstring:
                if content == 'init':
                    docstrings = [initdocstring]
                else:
                    docstrings.append(initdocstring)
        doc = []
        for docstring in docstrings:
            doc.append(sphinx.util.docstrings.prepare_docstring(docstring))
        return doc

    def add_content(self, more_content, **kwargs):
        if self.doc_as_attr:
            classname = sphinx.util.inspect.safe_getattr(self.object, '__name__', None)
            if classname:
                content = ViewList(
                    [_('alias of :class:`%s`') % classname], source='')
                super().add_content(content, get_doc=False)
        else:
            super().add_content(more_content)

    def document_members(self, *args, **kwargs):
        if self.doc_as_attr:
            return
        super().document_members(*args, **kwargs)


class MatDataDocumenter(MatModuleLevelDocumenter, PyDataDocumenter):

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return isinstance(member, MatScript)


class MatMethodDocumenter(MatDocstringSignatureMixin, MatClassLevelDocumenter):
    """
    Specialized Documenter subclass for methods (normal, static and class).
    """
    objtype = 'method'
    member_order = 50
    priority = 1  # must be more than FunctionDocumenter

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return type(member) is MatMethod

    def import_object(self):
        ret = super().import_object()
        if self.object.attrs.get('Static'):
            self.directivetype = 'staticmethod'
            # document class and static members before ordinary ones
            self.member_order = self.member_order - 1
        else:
            self.directivetype = 'method'
        return ret

    def format_args(self):
        if self.object.args:
            if self.object.args[0] == 'obj':
                return '('+ ', '.join(self.object.args[1:]) + ')'
            else:
                return '('+ ', '.join(self.object.args) + ')'

    def document_members(self, *args, **kwargs):
        pass


class MatAttributeDocumenter(MatClassLevelDocumenter):
    """
    Specialized Documenter subclass for attributes.
    """
    objtype = 'attribute'
    member_order = 60
    option_spec = dict(MatModuleLevelDocumenter.option_spec)
    option_spec["annotation"] = annotation_option

    # must be higher than the MethodDocumenter, else it will recognize
    # some non-data descriptors as methods
    priority = 10

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return type(member) is MatProperty

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

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return isinstance(member, MatScript)

    def document_members(self, *args, **kwargs):
        pass

class MatApplicationDocumenter(MatModuleLevelDocumenter):
    """
    Specialized Documenter subclass for Matlab Applications (.mlapp)
    """
    objtype = 'application'

    @classmethod
    def can_document_member(cls, member, *args, **kwargs):
        return isinstance(member, MatApplication)

    def document_members(self, *args, **kwargs):
        pass
