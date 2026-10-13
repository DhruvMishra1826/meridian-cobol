       >>source format free
identification division.
program-id. meridian.
data division.
working-storage section.
copy 'state.cpy'.
copy 'request.cpy'.
copy 'result.cpy'.
copy 'state.cpy' replacing ==app-state== by ==backup-state==.
01 journal-path pic x(1024).
01 original-input pic x(8192).
01 input-buffer pic x(8192).
01 command-buffer pic x(4096).
01 argument-count binary-long.
01 native-status binary-long.
01 path-length binary-long.
01 input-length binary-long.
01 command-length binary-long.
01 batch-length binary-long.
01 field-position binary-long.
01 i binary-long.
01 j binary-long.
01 part-start binary-long.
01 batch-count binary-long.
01 replay-mode pic 9.
01 replay-finished pic 9.
01 output-number pic Z(10)9.
procedure division.
    initialize app-state command-request operation-result
    accept argument-count from argument-number end-accept
    if argument-count not = 2
        display 'ERROR|Usage: meridian JOURNAL COMMAND' end-display
        move 2 to return-code
        goback
    end-if
    accept journal-path from argument-value end-accept
    accept original-input from argument-value end-accept
    compute path-length = function length(function trim(journal-path))
    end-compute
    compute input-length = function length(function trim(original-input trailing))
    end-compute
    if path-length < 1 or path-length > 1023
       or input-length < 1 or input-length > 4096
        display 'ERROR|Invalid path or command length' end-display
        move 2 to return-code
        goback
    end-if
    call static 'md_store_open' using by reference journal-path
        by value path-length returning native-status end-call
    if native-status not = 0
        display 'ERROR|Cannot open journal: lock, permissions, header or incomplete tail' end-display
        move 3 to return-code
        goback
    end-if
    move 1 to replay-mode
    perform until replay-finished = 1
        move spaces to input-buffer
        call static 'md_store_next' using by reference input-buffer
            by value 4096 returning native-status end-call
        evaluate true
            when native-status > 0
                perform process-input
                if result-code not = 0 or result-mutating not = 1
                    display 'ERROR|Invalid journal business event; restore a verified backup' end-display
                    call static 'md_store_close' end-call
                    move 3 to return-code
                    goback
                end-if
            when native-status = 0
                move 1 to replay-finished
            when native-status < 0
                display 'ERROR|Journal checksum, sequence or encoding failure' end-display
                call static 'md_store_close' end-call
                move 3 to return-code
                goback
        end-evaluate
    end-perform
    move 0 to replay-mode
    move original-input to input-buffer
    perform process-input
    if result-code = 0 and result-mutating = 1
        call static 'md_store_append' using by reference original-input
            by value input-length returning native-status end-call
        if native-status not = 0
            move 3 to result-code
            move 'Journal durability failure; operation was not acknowledged' to result-message
            move spaces to result-output
        end-if
    end-if
    if result-code = 0
        display 'OK|' function trim(result-message) end-display
        if result-output not = spaces
            display function trim(result-output trailing) with no advancing end-display
        end-if
    else
        display 'ERROR|' function trim(result-message) end-display
    end-if
    call static 'md_store_close' end-call
    move result-code to return-code
    goback.

process-input.
    move app-state to backup-state
    initialize operation-result
    if input-buffer(1:6) = 'BATCH|'
        move 0 to batch-count
        move 7 to part-start
        compute batch-length = function length(function trim(input-buffer trailing))
        end-compute
        perform varying j from 7 by 1 until j > batch-length + 1
            if j > batch-length or input-buffer(j:1) = '~'
                if j = part-start or batch-count >= 64
                    move 2 to result-code
                    move 'Batch requires 1..64 nonempty mutation commands' to result-message
                    exit perform
                end-if
                move spaces to command-buffer
                move input-buffer(part-start:j - part-start) to command-buffer
                perform dispatch-command
                if result-code not = 0 exit perform end-if
                if result-mutating not = 1
                    move 2 to result-code
                    move 'Batch accepts mutation commands only' to result-message
                    exit perform
                end-if
                add 1 to batch-count end-add
                compute part-start = j + 1 end-compute
            end-if
        end-perform
        if result-code = 0
            move 1 to result-mutating
            move spaces to result-output
            move batch-count to output-number
            move 'Atomic batch committed' to result-message
            string 'BATCH|' function trim(output-number) x'0a'
                into result-output end-string
        end-if
    else
        move input-buffer(1:4096) to command-buffer
        perform dispatch-command
    end-if
    if result-code not = 0
        move backup-state to app-state
        move 0 to result-mutating
        move spaces to result-output
    end-if.

dispatch-command.
    initialize command-request operation-result
    move 1 to field-count field-position
    compute command-length = function length(function trim(command-buffer trailing))
    end-compute
    perform varying i from 1 by 1 until i > command-length
        evaluate command-buffer(i:1)
            when '|'
                if field-position = 1 or field-count >= 16
                    move 2 to result-code
                    move 'Invalid field count or empty field' to result-message
                    exit paragraph
                end-if
                add 1 to field-count end-add
                move 1 to field-position
            when other
                if field-position > 256
                    move 2 to result-code
                    move 'Field exceeds 256 characters' to result-message
                    exit paragraph
                end-if
                move command-buffer(i:1) to command-field(field-count)(field-position:1)
                add 1 to field-position end-add
        end-evaluate
    end-perform
    if field-position = 1
        move 2 to result-code
        move 'Empty final field' to result-message
        exit paragraph
    end-if
    evaluate function trim(command-field(1))
        when 'ACCOUNT' when 'POST' when 'REVERSE' when 'CLOSE'
        when 'ACCOUNTS' when 'TRIAL' when 'JOURNAL' when 'STATEMENT' when 'SUMMARY'
            call 'MD-LEDGER' using app-state command-request operation-result end-call
        when 'ITEM' when 'RECEIVE' when 'ADJUST'
        when 'STOCK' when 'MOVEMENTS' when 'REORDER'
            call 'MD-INVENTORY' using app-state command-request operation-result end-call
        when 'CUSTOMER' when 'INVOICE' when 'LINE' when 'ISSUE' when 'PAY' when 'VOID'
        when 'CUSTOMERS' when 'INVOICES' when 'INVOICE-SHOW' when 'AGING'
            call 'MD-SALES' using app-state command-request operation-result end-call
        when other
            move 2 to result-code
            move 'Unknown command' to result-message
    end-evaluate.
end program meridian.
