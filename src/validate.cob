       >>source format free
identification division.
program-id. MD-VALIDATE.
data division.
working-storage section.
01 n binary-long.
01 i binary-long.
01 ordinal binary-long.
01 date-number pic 9(8).
linkage section.
01 input-value pic x(256).
01 input-kind pic x(8).
01 input-maximum binary-long.
01 valid-result binary-long.
procedure division using input-value input-kind input-maximum valid-result.
    move 0 to valid-result
    compute n = function length(function trim(input-value trailing))
    end-compute
    if n < 1 or n > input-maximum goback end-if
    evaluate function trim(input-kind)
        when 'ID'
            perform varying i from 1 by 1 until i > n
                if not (input-value(i:1) >= 'A' and <= 'Z')
                   and not (input-value(i:1) >= '0' and <= '9')
                   and input-value(i:1) not = '-'
                   and input-value(i:1) not = '_'
                    goback
                end-if
            end-perform
        when 'TEXT'
            if input-value(1:1) = space goback end-if
            perform varying i from 1 by 1 until i > n
                compute ordinal = function ord(input-value(i:1)) - 1
                end-compute
                if ordinal < 32 or ordinal > 126
                   or input-value(i:1) = '|' or '~'
                    goback
                end-if
            end-perform
        when 'UINT'
            if n > 1 and input-value(1:1) = '0' goback end-if
            perform varying i from 1 by 1 until i > n
                if input-value(i:1) < '0' or > '9' goback end-if
            end-perform
        when 'DATE'
            if n not = 8 goback end-if
            if input-value(1:8) is not numeric goback end-if
            move input-value(1:8) to date-number
            if date-number < 16010101 or > 99991231 goback end-if
            if function test-date-yyyymmdd(date-number) not = 0
                goback
            end-if
        when other
            goback
    end-evaluate
    move 1 to valid-result
    goback.
end program MD-VALIDATE.
