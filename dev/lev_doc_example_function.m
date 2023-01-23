function output = lev_doc_example_function(arg1, arg2)
    % The example documentation for a function. 
    %
    % In the second paragraph and on, a more elaborate explanation of the function
    % can be given. 
    % It does not matter when a new line is used in the MATLAB docstring. 
    %
    % Only if there is a empty line in between, a new paragraph is started. 
    arguments (Input)
        arg1 (1,1) double {MustBePositive} = 1
        arg2 (1,1) logical {MustBeReal} = True
    end

    arguments(Output)
        output (1,1) float {MustBeInteger}
    end

    disp(arg1)
    output = double(arg2);
end