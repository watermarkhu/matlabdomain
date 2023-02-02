function [output] = lev_doc_example_function(arg1, arg2 )
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

    arguments (Input)
        arg1 (1,1) double {MustBePositive, MustBeSomething(arg1, 1)} = 1  % This is the comment for arg1
        arg2 (1,1) logical {MustBeReal} = True                            
        % This is the comment for arg2
        % split over multiple lines
    end

    arguments(Output, Repeating)
        output (1,1) float {MustBeInteger};
    end

    disp(arg1)
    output = double(arg1);
    output2 = logical(arg2);
end