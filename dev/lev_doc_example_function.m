function output = lev_doc_example_function(arg1, arg2)
    % The example documentation for a function. 
    %
    % In the second paragraph and on, a more elaborate explanation of the function
    % can be given. 
    %
    % Parameters
    % ----------
    % arg1 : double
    %   The first argument
    % arg2 : logical
    %   The second argument
    %
    % Returns
    % -------
    % output : float
    %   The output variable

    arguments (Input, Repeating)
        arg1 (1,1) double {MustBePositive} = 1
        arg2 (1,1) logical {MustBeReal} = True
    end

    arguments(Output)
        output (1,1) float {MustBeInteger}
    end

    disp(arg1)
    output = double(arg2);
end