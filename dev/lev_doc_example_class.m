classdef (Abstract) lev_doc_example_class < handle & superclass
% The example documentation for a class
%
% Directly under the classdef definition, there should be a section detailing the function 
% of the class. Any examples can also be added here. If the class has a constructor (in this case
% :meth:`lev_doc_example_class`), then the documention of the constructor should be put there, 
% e.g. this section should not have a 'PARAMETERS' or 'RETURNS' section.
%
% An example can be added by defining a *code* block as below. The example should show how the class
% should be used. The newlines in between the ``.. code ::`` and the code itself is necessary. 
%
% .. code-block::
%
%   exampleClass = lev_doc_example(args);
%  

properties
    documentedProp   (1,1) double {MustBePositive} = 1  % If a comment is defined for a (public) property, it will be added to the documentation. 
    undocumentedProp (1,1) double {MustBePositive} = 2
end

properties (Access=private)
    privateProp        % Private properties are not documented.
end

methods
    function obj = lev_doc_example_class(arg)
    % Constructor of the example class.
    %
    % Since constructors in MATLAB are just public class methods (never make a construtor private), 
    % it should be clear from the description that this method is the constructor. The short-description
    % should preferably 'Constructor of ...'.
    %
    % Parameters
    % ----------
    % arg : type
    %   The input argument
    %
    % Returns
    % -------
    % obj : lev_doc_example_class
    %   The example class. This returns section is optional, as it is clear what the constructor does.
        arguments
            arg (1,1) logical {MustBeReal} = True
        end
        obj.documentedProp = arg;
    end

    function out = example_method(obj, arg)
    % Some class method of the example class
        out = arg;
    end
end

methods (Static)
    function out = static_method(arg)
        % Some class method of the example class
        %
        % Parameters
        % ----------
        % arg : type
        %   Input argument
            arguments
                arg (1,1) logical {MustBeReal} = True
            end
            out = arg;
        end
end

methods (Access=private)
    function out = private_method(arg)
    % Private methods are not documented.
        out = arg;
    end
end

end