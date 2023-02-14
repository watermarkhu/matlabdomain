Algorithm flow
==============

```{mermaid}
flowchart
 subgraph "main"
  m0(sphinx.Sphinx)
  m1(sphinx.Sphinx.build)
  m0 --> m1
 end

 subgraph "matlab.setup(app)"
  %%direction TB%%
  n0(app.add_domain)
  n1(app.add_config_value)
  n2(app.registry.add_documenter)
  n3(app.add_directive_do_tomain)
  n4(app.add_autodoc_attrgetter)
  n0 --> n1
  n1 --> n2
  n2 --> n3
  n3 --> n2
  n3 --> n4
 end
 m0 ==> n0

 subgraph "MatlabAutodocDirective"
  ma0(run)
 end
 subgraph modulesSpace
  datam[(modules)]
  subgraph "MablabDocumenter"
   md0(generate)
   subgraph generate
    md1(parse_name)
    md2(resolve_name)
    md3(import_object)
    md4(format_signature)
    md5(add_directive_header)
    md6(document_members)
    md7(get_object_members)
   end
   md0 --> md1
   md1 ==> md2
   md1 --> md3
   md3 --> md4
   md4 --> md5
   md5 --> md6
   md6 --> md7
  end
  m1 == "once per mat:autodirective" ==> ma0
  ma0 ==> md0
 
  subgraph "MatObject (mat_types)"
   mo0(import_matlab_type)
  end
  mo0 -.-> datam
  subgraph "MatModuleAnalyzer (mat_types)"
   mma0(find_attr_docs)
  end
  md7 ==> mma0 
 end
 md3 ==> mo0
```