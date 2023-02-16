function [output, output2] = f_with_argument_blocks(arg1, arg2 )
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
    % output2 : logical
    %   The output variable

    arguments (Input)
        arg1 (1,1) double {MustBePositive, MustBeSomething(arg1, 1)} = 1  % This is the comment for arg1
        arg2.field1 (1,1) logical {MustBeReal} = True                            
        % This is the comment for arg2
        % split over multiple lines
        arg2.field2  = str2double('2') % Theother field
    end

    arguments(Output)
        output (1,1) float {MustBeInteger}
        output2 logical; % Second output
    end

    disp(arg1)
    output = double(arg1);
    output2 = logical(arg2);
end