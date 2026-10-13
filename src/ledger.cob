       >>source format free
identification division.
program-id. MD-LEDGER.
data division.
working-storage section.
01 ledger-work.
   05 i binary-long.
   05 j binary-long.
   05 debit-index binary-long.
   05 credit-index binary-long.
   05 account-index binary-long.
   05 entry-index binary-long.
   05 original-index binary-long.
   05 output-pointer binary-long.
   05 ref-value pic x(32).
   05 date-value pic 9(8).
   05 debit-value pic x(12).
   05 credit-value pic x(12).
   05 amount-value pic 9(12) comp-3.
   05 memo-value pic x(100).
   05 new-debit pic s9(16) comp-3.
   05 new-credit pic s9(16) comp-3.
   05 total-debits pic 9(16) comp-3.
   05 total-credits pic 9(16) comp-3.
   05 kind-total pic s9(16) comp-3.
   05 net-income pic s9(16) comp-3.
   05 current-kind pic x(10).
   05 amount-edit pic -(16)9.
   05 second-edit pic -(16)9.
   05 third-edit pic -(16)9.
   05 count-edit pic Z(10)9.
   05 identifier-value pic x(32).
01 valid-input binary-long.
01 maximum-size binary-long.
01 validation-value pic x(256).
01 validation-kind pic x(8).
linkage section.
copy 'state.cpy'.
copy 'request.cpy'.
copy 'result.cpy'.
procedure division using app-state command-request operation-result.
    initialize ledger-work operation-result
    move 1 to output-pointer
    evaluate function trim(command-field(1))
        when 'ACCOUNT' perform create-account
        when 'POST' perform create-post
        when 'REVERSE' perform reverse-post
        when 'CLOSE' perform close-period
        when 'ACCOUNTS' perform list-accounts
        when 'TRIAL' perform trial-balance
        when 'JOURNAL' perform list-journal
        when 'STATEMENT' perform account-statement
        when 'SUMMARY' perform ledger-summary
        when other
            move 2 to result-code
            move 'Unknown ledger command' to result-message
    end-evaluate
    if result-code not = 0
        move spaces to result-output
        move 0 to result-mutating
    end-if
    goback.

check-value.
    call 'MD-VALIDATE' using validation-value validation-kind
        maximum-size valid-input end-call
    if valid-input not = 1
        move 2 to result-code
        move 'Invalid field: expected canonical ID, text, integer or date' to result-message
    end-if.

find-account.
    move 0 to account-index
    perform varying i from 1 by 1 until i > account-count
        if account-id(i) = identifier-value
            move i to account-index
            exit perform
        end-if
    end-perform.

create-account.
    if field-count not = 4
        move 2 to result-code
        move 'ACCOUNT requires id, kind and name' to result-message
        exit paragraph
    end-if
    move command-field(2) to validation-value
    move 'ID' to validation-kind
    move 12 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    if command-field(3) not = 'ASSET' and not = 'LIABILITY'
       and not = 'EQUITY' and not = 'REVENUE' and not = 'EXPENSE'
        move 2 to result-code
        move 'Account kind must be ASSET, LIABILITY, EQUITY, REVENUE or EXPENSE' to result-message
        exit paragraph
    end-if
    move command-field(4) to validation-value
    move 'TEXT' to validation-kind
    move 80 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:32) to identifier-value
    perform find-account
    if account-index > 0 or account-count >= 200
        move 2 to result-code
        move 'Account already exists or account capacity reached' to result-message
        exit paragraph
    end-if
    add 1 to account-count end-add
    move command-field(2)(1:12) to account-id(account-count)
    move command-field(3)(1:10) to account-kind(account-count)
    move command-field(4)(1:80) to account-name(account-count)
    move 0 to account-balance(account-count)
    move 1 to result-mutating
    move 'Account created' to result-message.

create-post.
    if field-count not = 7
        move 2 to result-code
        move 'POST requires reference, date, debit, credit, amount and memo' to result-message
        exit paragraph
    end-if
    move command-field(2) to validation-value
    move 'ID' to validation-kind
    move 32 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:32) to ref-value
    move command-field(3) to validation-value
    move 'DATE' to validation-kind
    move 8 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(3)(1:8) to date-value
    move command-field(4) to validation-value
    move 'ID' to validation-kind
    move 12 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(4)(1:12) to debit-value
    move command-field(5) to validation-value
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(5)(1:12) to credit-value
    move command-field(6) to validation-value
    move 'UINT' to validation-kind
    move 12 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    compute amount-value = function numval(command-field(6)) end-compute
    move command-field(7) to validation-value
    move 'TEXT' to validation-kind
    move 100 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(7)(1:100) to memo-value
    perform validate-post
    if result-code = 0 perform apply-post end-if.

validate-post.
    if amount-value = 0 or date-value <= closed-through
       or debit-value = credit-value
        move 2 to result-code
        move 'Posting needs a positive amount, distinct accounts and an open date' to result-message
        exit paragraph
    end-if
    if entry-count >= 4096
        move 2 to result-code
        move 'Ledger entry capacity reached' to result-message
        exit paragraph
    end-if
    perform varying i from 1 by 1 until i > entry-count
        if entry-ref(i) = ref-value
            move 2 to result-code
            move 'Posting reference already exists' to result-message
            exit paragraph
        end-if
    end-perform
    move debit-value to identifier-value
    perform find-account
    move account-index to debit-index
    move credit-value to identifier-value
    perform find-account
    move account-index to credit-index
    if debit-index = 0 or credit-index = 0
        move 2 to result-code
        move 'Both posting accounts must exist' to result-message
        exit paragraph
    end-if
    compute new-debit = account-balance(debit-index) + amount-value end-compute
    compute new-credit = account-balance(credit-index) - amount-value end-compute
    if function abs(new-debit) > 99999999999999
       or function abs(new-credit) > 99999999999999
        move 2 to result-code
        move 'Account balance limit exceeded' to result-message
    end-if.

apply-post.
    add 1 to entry-count end-add
    move ref-value to entry-ref(entry-count)
    move date-value to entry-date(entry-count)
    move debit-value to entry-debit(entry-count)
    move credit-value to entry-credit(entry-count)
    move amount-value to entry-amount(entry-count)
    move memo-value to entry-memo(entry-count)
    move spaces to entry-reversed-by(entry-count)
    move 'MANUAL' to entry-source(entry-count)
    compute account-balance(debit-index) = new-debit end-compute
    compute account-balance(credit-index) = new-credit end-compute
    move 1 to result-mutating
    move 'Balanced posting committed' to result-message.

reverse-post.
    if field-count not = 5
        move 2 to result-code
        move 'REVERSE requires original reference, new reference, date and memo' to result-message
        exit paragraph
    end-if
    move 'ID' to validation-kind
    move 32 to maximum-size
    move command-field(2) to validation-value
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move 0 to original-index
    perform varying i from 1 by 1 until i > entry-count
        if entry-ref(i) = command-field(2)
            move i to original-index
            exit perform
        end-if
    end-perform
    if original-index = 0
        move 2 to result-code
        move 'Original posting not found' to result-message
        exit paragraph
    end-if
    if entry-reversed-by(original-index) not = spaces
        move 2 to result-code
        move 'Posting has already been reversed' to result-message
        exit paragraph
    end-if
    if entry-source(original-index) not = 'MANUAL'
        move 2 to result-code
        move 'Integrated subledger postings cannot be reversed with a manual journal command' to result-message
        exit paragraph
    end-if
    move command-field(3) to validation-value
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(3)(1:32) to ref-value
    move command-field(4) to validation-value
    move 'DATE' to validation-kind
    move 8 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(4)(1:8) to date-value
    if date-value < entry-date(original-index)
        move 2 to result-code
        move 'Reversal date cannot precede original posting' to result-message
        exit paragraph
    end-if
    move command-field(5) to validation-value
    move 'TEXT' to validation-kind
    move 100 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(5)(1:100) to memo-value
    move entry-credit(original-index) to debit-value
    move entry-debit(original-index) to credit-value
    move entry-amount(original-index) to amount-value
    perform validate-post
    if result-code = 0
        perform apply-post
        move ref-value to entry-reversed-by(original-index)
        move 'Reversal committed with original preserved' to result-message
    end-if.

close-period.
    if field-count not = 2
        move 2 to result-code
        move 'CLOSE requires a through date' to result-message
        exit paragraph
    end-if
    move command-field(2) to validation-value
    move 'DATE' to validation-kind
    move 8 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:8) to date-value
    if date-value <= closed-through
        move 2 to result-code
        move 'Close date must advance beyond the current closed period' to result-message
        exit paragraph
    end-if
    move date-value to closed-through
    move 1 to result-mutating
    move 'Period closed; backdated postings are blocked' to result-message.

require-query.
    if field-count not = 1
        move 2 to result-code
        move 'Query takes no additional fields' to result-message
    end-if.

list-accounts.
    perform require-query
    if result-code not = 0 exit paragraph end-if
    perform varying i from 1 by 1 until i > account-count
        move account-balance(i) to amount-edit
        string 'ACCOUNT|' function trim(account-id(i)) '|'
            function trim(account-kind(i)) '|' function trim(account-name(i)) '|'
            function trim(amount-edit) x'0a' into result-output
            with pointer output-pointer on overflow perform output-overflow end-string
    end-perform
    move 'Chart of accounts; balances are debit minus credit' to result-message.

trial-balance.
    perform require-query
    if result-code not = 0 exit paragraph end-if
    perform varying i from 1 by 1 until i > account-count
        move 0 to new-debit new-credit
        if account-balance(i) >= 0
            move account-balance(i) to new-debit
            add new-debit to total-debits end-add
        else
            compute new-credit = 0 - account-balance(i) end-compute
            add new-credit to total-credits end-add
        end-if
        move new-debit to amount-edit
        move new-credit to second-edit
        string 'TRIAL|' function trim(account-id(i)) '|'
            function trim(account-name(i)) '|' function trim(amount-edit) '|'
            function trim(second-edit) x'0a' into result-output with pointer output-pointer
            on overflow perform output-overflow end-string
    end-perform
    move total-debits to amount-edit
    move total-credits to second-edit
    string 'TOTAL|' function trim(amount-edit) '|' function trim(second-edit) x'0a'
        into result-output with pointer output-pointer on overflow perform output-overflow end-string
    move 'Trial balance in integer minor units' to result-message.

list-journal.
    perform require-query
    if result-code not = 0 exit paragraph end-if
    perform varying j from 1 by 1 until j > entry-count or result-code not = 0
        perform emit-entry
    end-perform
    move 'Immutable double-entry postings' to result-message.

emit-entry.
    move entry-amount(j) to amount-edit
    string 'ENTRY|' function trim(entry-ref(j)) '|' entry-date(j) '|'
        function trim(entry-debit(j)) '|' function trim(entry-credit(j)) '|'
        function trim(amount-edit) '|' function trim(entry-memo(j)) '|'
        function trim(entry-reversed-by(j)) x'0a'
        into result-output with pointer output-pointer on overflow perform output-overflow end-string.

account-statement.
    if field-count not = 2
        move 2 to result-code
        move 'STATEMENT requires an account ID' to result-message
        exit paragraph
    end-if
    move command-field(2) to validation-value
    move 'ID' to validation-kind
    move 12 to maximum-size
    perform check-value
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:32) to identifier-value
    perform find-account
    if account-index = 0
        move 2 to result-code
        move 'Account not found' to result-message
        exit paragraph
    end-if
    perform varying j from 1 by 1 until j > entry-count or result-code not = 0
        if entry-debit(j) = command-field(2) or entry-credit(j) = command-field(2)
            perform emit-entry
        end-if
    end-perform
    move account-balance(account-index) to amount-edit
    string 'BALANCE|' function trim(command-field(2)) '|'
        function trim(amount-edit) x'0a' into result-output with pointer output-pointer
        on overflow perform output-overflow end-string
    move 'Account statement and current balance' to result-message.

ledger-summary.
    perform require-query
    if result-code not = 0 exit paragraph end-if
    perform varying j from 1 by 1 until j > 5
        evaluate j
            when 1 move 'ASSET' to current-kind
            when 2 move 'LIABILITY' to current-kind
            when 3 move 'EQUITY' to current-kind
            when 4 move 'REVENUE' to current-kind
            when 5 move 'EXPENSE' to current-kind
        end-evaluate
        move 0 to kind-total
        perform varying i from 1 by 1 until i > account-count
            if account-kind(i) = current-kind
                add account-balance(i) to kind-total end-add
            end-if
        end-perform
        if current-kind = 'LIABILITY' or 'EQUITY' or 'REVENUE'
            compute kind-total = 0 - kind-total end-compute
        end-if
        if current-kind = 'REVENUE' add kind-total to net-income end-add end-if
        if current-kind = 'EXPENSE' subtract kind-total from net-income end-subtract end-if
        move kind-total to amount-edit
        string 'SUMMARY|' function trim(current-kind) '|' function trim(amount-edit) x'0a'
            into result-output with pointer output-pointer on overflow perform output-overflow end-string
    end-perform
    move net-income to amount-edit
    string 'RESULT|' function trim(amount-edit) x'0a' 'PERIOD|' closed-through x'0a'
        into result-output with pointer output-pointer on overflow perform output-overflow end-string
    move account-count to count-edit
    string 'COUNTS|' function trim(count-edit) into result-output with pointer output-pointer end-string
    move entry-count to count-edit
    string '|' function trim(count-edit) into result-output with pointer output-pointer end-string
    move item-count to count-edit
    string '|' function trim(count-edit) into result-output with pointer output-pointer end-string
    move customer-count to count-edit
    string '|' function trim(count-edit) into result-output with pointer output-pointer end-string
    move invoice-count to count-edit
    string '|' function trim(count-edit) x'0a' into result-output with pointer output-pointer end-string
    move 'Current financial summary in natural account signs' to result-message.

output-overflow.
    move 2 to result-code
    move 'Report exceeds output capacity' to result-message.
end program MD-LEDGER.
