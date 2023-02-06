Classes 
-------

```{mermaid}
classDiagram
 class sphinxApplication {
  +directory SphinxComponentRegistry
  +env sphinxBuildEnvironment
  +config sphinxConfig
 }
 class SphinxComponentRegistry{
  +domains MABLABDomain
  +documenters MablabDocumenter
  +domain_directives MatlabAutodocDirective
 }
 class sphinxConfig {
 }
 class sphinxBuildEnvironment {
  +app sphinxApplication
  +config sphinxConfig
  +temp_data
  +docname
  +domaindata
  +domains MABLABDomain
  +srcdir
  +titles
  +tocs
 }
    class sphinxDocumenterBridge {
        +state
        +result
    }
 
 sphinxBuildEnvironment <-- sphinxConfig
 sphinxApplication <-- SphinxComponentRegistry
 sphinxApplication <-- sphinxBuildEnvironment
 
 class MABLABDomain {
  +bool is
 }
 class MatlabDocumenter {
  +modname
  +real_modname
  +obj_path: list
  +args
  +retann
  +fullname
        +directive sphinxDocumenterBridge
  +env sphinxBuildEnvironment
  resolve_name()*
  +parse_name()
  +import_object()
  +format_signature()
  +add_directive_header()
  +document_members()
  +add_content(more_content, no_docstring:bool)
  +get_object_members(want_all:bool)
  +filter_members(members, want_all:bool)
  +document_members(all_members:bool)
  +generate(more_content, real_modname, check_module, all_members)
 }
 class MatlabAutodocDirective {
  +env sphinxBuildEnvironment
  +lineo
  +name 
  +state
  +arguments
  +content
  +run()
 }

 SphinxComponentRegistry <-- MABLABDomain
 SphinxComponentRegistry <-- MatlabDocumenter
 SphinxComponentRegistry <-- MatlabAutodocDirective

    MatlabDocumenter <-- sphinxDocumenterBridge
 MatlabDocumenter <-- sphinxBuildEnvironment
 MatlabAutodocDirective <-- sphinxBuildEnvironment

 class MatObject {
        +__module__
        +matlabify(objname)
 }

 MatlabDocumenter -- MatObject
```