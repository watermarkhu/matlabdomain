import sphinx.util
from sphinx.ext.autodoc.directive import AutodocDirective, DummyOptionSpec, DocumenterBridge
from sphinx.ext.autodoc.directive import process_documenter_options, parse_generated_content


MAT_DOM = 'sphinxcontrib-matlabdomain'
logger = sphinx.util.logging.getLogger('matlab-domain')


class MatlabAutodocDirective(AutodocDirective):
    """A directive class for all MATLAB autodoc directives.

    Modified version of the Python AutodocDirective

    It works as a dispatcher of Documenters. It invokes a Documenter on running.
    After the processing, it parses and returns the generated content by
    Documenter.
    """
    option_spec = DummyOptionSpec()
    has_content = True
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True

    def run(self):
        reporter = self.state.document.reporter

        try:
            source, lineno = reporter.get_source_and_line(self.lineno)  # type: ignore
        except AttributeError:
            source, lineno = (None, None)
        logger.debug('[%s] %s:%s: input:\n%s', MAT_DOM, source, lineno, self.block_text)

        # look up target Documenter
        objtype = self.name.replace('auto', '')  # Removes auto
        doccls = self.env.app.registry.documenters[objtype]

        # process the options with the selected documenter's option_spec
        try:
            documenter_options = process_documenter_options(doccls, self.config, self.options)
        except (KeyError, ValueError, TypeError) as exc:
            # an option is either unknown or has a wrong type
            logger.error('An option to %s is either unknown or has an invalid value: %s' %
                         (self.name, exc), location=(source, lineno))
            return []

        # generate the output
        directive = DocumenterBridge(self.env, reporter, documenter_options, lineno, self.state)
        documenter = doccls(directive, self.arguments[0])
        documenter.generate(more_content=self.content)
        if not directive.result:
            return []

        logger.debug('[%s] output:\n%s', MAT_DOM, '\n'.join(directive.result))

        # record all filenames as dependencies -- this will at least
        # partially make automatic invalidation possible
        for fn in directive.record_dependencies:
            self.state.document.settings.record_dependencies.add(fn)

        result = parse_generated_content(self.state, directive.result, documenter)
        return result
