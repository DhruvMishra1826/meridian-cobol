       >>source format free
identification division.
program-id. MD-INVENTORY.
environment division.
configuration section.
repository. function all intrinsic.
data division.
working-storage section.
01 ws-index binary-long.
01 ws-item binary-long.
01 ws-account-found binary-long.
01 ws-field binary-long.
01 ws-limit binary-long.
01 ws-valid binary-long.
01 ws-kind pic x(8).
01 ws-value pic x(256).
01 ws-quantity pic s9(9) comp-3.
01 ws-new-quantity pic s9(10) comp-3.
01 ws-stock-value pic 9(20) comp-3.
01 ws-post-amount pic 9(20) comp-3.
01 ws-cost pic 9(10) comp-3.
01 ws-reorder pic 9(9) comp-3.
01 ws-number pic 9(20) comp-3.
01 ws-edited pic z(19)9.
01 ws-text pic x(20).
01 ws-quantity-text pic x(20).
01 ws-cost-text pic x(20).
01 ws-stock-text pic x(20).
01 ws-reorder-text pic x(20).
01 ws-date pic 9(8).
01 ws-pointer binary-long.
01 ws-row pic x(320).
copy "request.cpy" replacing
    ==command-request== by ==ws-ledger-request==
    ==field-count== by ==lr-count==
    ==command-field== by ==lr-field==.
copy "result.cpy" replacing
    ==operation-result== by ==ws-ledger-result==
    ==result-code== by ==lr-code==
    ==result-mutating== by ==lr-mutating==
    ==result-message== by ==lr-message==
    ==result-output== by ==lr-output==.
linkage section.
copy "state.cpy".
copy "request.cpy".
copy "result.cpy".
procedure division using app-state command-request operation-result.
main.
    initialize operation-result
    move 1 to ws-pointer
    evaluate trim(command-field(1))
        when "ITEM" perform create-item
        when "RECEIVE" perform receive-stock
        when "ADJUST" perform adjust-stock
        when "STOCK" perform stock-report
        when "MOVEMENTS" perform movement-report
        when "REORDER" perform reorder-report
        when other
            move 2 to result-code
            move "Unknown inventory command" to result-message
    end-evaluate
    goback.

create-item.
    if field-count not = 5
        move "ITEM requires sku, name, cost and reorder point"
            to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 2 to ws-field
    move "ID" to ws-kind
    move 12 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 3 to ws-field
    move "TEXT" to ws-kind
    move 80 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 4 to ws-field
    move "UINT" to ws-kind
    move 10 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(4)) to ws-cost
    if ws-cost = 0
        move "Standard cost must be positive" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 5 to ws-field
    move 9 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(5)) to ws-reorder
    move command-field(2) to ws-value
    perform find-item
    if ws-item not = 0
        move "Item already exists" to result-message
        perform reject-operation
        exit paragraph
    end-if
    if item-count >= 500
        move "Item capacity reached" to result-message
        perform reject-operation
        exit paragraph
    end-if
    add 1 to item-count end-add
    initialize items(item-count)
    move command-field(2)(1:12) to item-id(item-count)
    move command-field(3)(1:80) to item-name(item-count)
    move ws-cost to item-cost(item-count)
    move ws-reorder to item-reorder(item-count)
    move 1 to result-mutating
    move "Item created" to result-message.

receive-stock.
    perform validate-movement-fields
    if result-code not = 0 exit paragraph end-if
    move 5 to ws-field
    move "UINT" to ws-kind
    move 9 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(5)) to ws-quantity
    if ws-quantity = 0
        move "Quantity must be positive" to result-message
        perform reject-operation
        exit paragraph
    end-if
    perform apply-movement
    if result-code = 0
        move "Stock received" to result-message
    end-if.

adjust-stock.
    perform validate-movement-fields
    if result-code not = 0 exit paragraph end-if
    move command-field(5) to ws-value
    if ws-value(1:1) = "-"
        move command-field(5)(2:) to ws-value
    end-if
    move "UINT" to ws-kind
    move 9 to ws-limit
    call "MD-VALIDATE" using ws-value ws-kind ws-limit ws-valid end-call
    if ws-valid not = 1
        move "Adjustment must be a nonzero signed integer"
            to result-message
        perform reject-operation
        exit paragraph
    end-if
    move function numval(ws-value) to ws-quantity
    if ws-quantity = 0
        move "Adjustment must be nonzero" to result-message
        perform reject-operation
        exit paragraph
    end-if
    if command-field(5)(1:1) = "-"
        compute ws-quantity = 0 - ws-quantity end-compute
    end-if
    perform apply-movement
    if result-code = 0
        move "Stock adjusted" to result-message
    end-if.

validate-movement-fields.
    if field-count not = 8
        move "Movement requires reference, date, sku, quantity,"
            & " accounts and memo" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 2 to ws-field
    move "ID" to ws-kind
    move 32 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    perform varying ws-index from 1 by 1
        until ws-index > movement-count
        if movement-ref(ws-index) = command-field(2)
            move "Movement reference already exists" to result-message
            perform reject-operation
            exit paragraph
        end-if
    end-perform
    if movement-count >= 4096
        move "Movement capacity reached" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 3 to ws-field
    move "DATE" to ws-kind
    move 8 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(3)) to ws-date
    move 4 to ws-field
    move "ID" to ws-kind
    move 12 to ws-limit
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move command-field(4) to ws-value
    perform find-item
    if ws-item = 0
        move "Item does not exist" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 6 to ws-field
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 7 to ws-field
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    perform validate-movement-accounts
    if result-code not = 0 exit paragraph end-if
    move 8 to ws-field
    move "TEXT" to ws-kind
    move 80 to ws-limit
    perform validate-field.

validate-movement-accounts.
    if command-field(6) = command-field(7)
        move "Inventory and offset accounts must differ" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 0 to ws-account-found
    perform varying ws-index from 1 by 1 until ws-index > account-count
        if account-id(ws-index) = command-field(6)
            move 1 to ws-account-found
            if account-kind(ws-index) not = "ASSET"
                move "Inventory account must have kind ASSET"
                    to result-message
                perform reject-operation
                exit paragraph
            end-if
            exit perform
        end-if
    end-perform
    if ws-account-found = 0
        move "Inventory account does not exist" to result-message
        perform reject-operation
        exit paragraph
    end-if
    move 0 to ws-account-found
    perform varying ws-index from 1 by 1 until ws-index > account-count
        if account-id(ws-index) = command-field(7)
            move 1 to ws-account-found
            exit perform
        end-if
    end-perform
    if ws-account-found = 0
        move "Offset account does not exist" to result-message
        perform reject-operation
    end-if.

apply-movement.
    compute ws-new-quantity = item-quantity(ws-item) + ws-quantity
        end-compute
    if ws-new-quantity < 0
        move "Adjustment would make stock negative" to result-message
        perform reject-operation
        exit paragraph
    end-if
    if ws-new-quantity > 999999999
        move "Stock quantity exceeds limit" to result-message
        perform reject-operation
        exit paragraph
    end-if
    compute ws-stock-value = ws-new-quantity * item-cost(ws-item)
        end-compute
    if ws-stock-value > 999999999999
        move "Stock value exceeds limit" to result-message
        perform reject-operation
        exit paragraph
    end-if
    compute ws-post-amount = abs(ws-quantity) * item-cost(ws-item)
        end-compute
    if ws-post-amount > 999999999999
        move "Movement posting exceeds limit" to result-message
        perform reject-operation
        exit paragraph
    end-if
    initialize ws-ledger-request ws-ledger-result
    move 7 to lr-count
    move "POST" to lr-field(1)
    move command-field(2) to lr-field(2)
    move command-field(3) to lr-field(3)
    if ws-quantity > 0
        move command-field(6) to lr-field(4)
        move command-field(7) to lr-field(5)
    else
        move command-field(7) to lr-field(4)
        move command-field(6) to lr-field(5)
    end-if
    move ws-post-amount to ws-number
    perform format-number
    move ws-text to lr-field(6)
    move command-field(8) to lr-field(7)
    call "MD-LEDGER" using app-state ws-ledger-request ws-ledger-result
        end-call
    if lr-code not = 0
        move ws-ledger-result to operation-result
        exit paragraph
    end-if
    move "INVENTORY" to entry-source(entry-count)
    compute item-quantity(ws-item) = ws-new-quantity end-compute
    add 1 to movement-count end-add
    initialize movements(movement-count)
    move command-field(2)(1:32) to movement-ref(movement-count)
    move ws-date to movement-date(movement-count)
    move command-field(4)(1:12) to movement-item(movement-count)
    move ws-quantity to movement-quantity(movement-count)
    move command-field(8)(1:80) to movement-reason(movement-count)
    move 1 to result-mutating.

stock-report.
    perform validate-query
    if result-code not = 0 exit paragraph end-if
    perform varying ws-index from 1 by 1 until ws-index > item-count
        move item-quantity(ws-index) to ws-number
        perform format-number
        move ws-text to ws-quantity-text
        move item-cost(ws-index) to ws-number
        perform format-number
        move ws-text to ws-cost-text
        compute ws-number = item-cost(ws-index) * item-quantity(ws-index)
            end-compute
        perform format-number
        move ws-text to ws-stock-text
        move item-reorder(ws-index) to ws-number
        perform format-number
        move ws-text to ws-reorder-text
        move spaces to ws-row
        string "STOCK|" trim(item-id(ws-index)) "|"
            trim(item-name(ws-index)) "|" trim(ws-quantity-text) "|"
            trim(ws-cost-text) "|" trim(ws-stock-text) "|"
            trim(ws-reorder-text) into ws-row
        end-string
        perform append-row
        if result-code not = 0 exit paragraph end-if
    end-perform
    move "Stock report" to result-message.

movement-report.
    perform validate-query
    if result-code not = 0 exit paragraph end-if
    perform varying ws-index from 1 by 1
        until ws-index > movement-count
        compute ws-number = abs(movement-quantity(ws-index)) end-compute
        perform format-number
        move spaces to ws-quantity-text
        if movement-quantity(ws-index) < 0
            string "-" trim(ws-text) into ws-quantity-text end-string
        else
            move ws-text to ws-quantity-text
        end-if
        move movement-date(ws-index) to ws-date
        move spaces to ws-row
        string "MOVEMENT|" trim(movement-ref(ws-index)) "|" ws-date "|"
            trim(movement-item(ws-index)) "|" trim(ws-quantity-text) "|"
            trim(movement-reason(ws-index)) into ws-row
        end-string
        perform append-row
        if result-code not = 0 exit paragraph end-if
    end-perform
    move "Movement report" to result-message.

reorder-report.
    perform validate-query
    if result-code not = 0 exit paragraph end-if
    perform varying ws-index from 1 by 1 until ws-index > item-count
        if item-quantity(ws-index) < item-reorder(ws-index)
            move item-quantity(ws-index) to ws-number
            perform format-number
            move ws-text to ws-quantity-text
            move item-reorder(ws-index) to ws-number
            perform format-number
            move ws-text to ws-reorder-text
            compute ws-number = item-reorder(ws-index)
                - item-quantity(ws-index) end-compute
            perform format-number
            move spaces to ws-row
            string "REORDER|" trim(item-id(ws-index)) "|"
                trim(item-name(ws-index)) "|" trim(ws-quantity-text) "|"
                trim(ws-reorder-text) "|" trim(ws-text) into ws-row
            end-string
            perform append-row
            if result-code not = 0 exit paragraph end-if
        end-if
    end-perform
    move "Reorder report" to result-message.

validate-query.
    if field-count not = 1
        move "Inventory report accepts no arguments" to result-message
        perform reject-operation
    end-if.

validate-field.
    move command-field(ws-field) to ws-value
    call "MD-VALIDATE" using ws-value ws-kind ws-limit ws-valid end-call
    if ws-valid not = 1
        move spaces to result-message
        string "Invalid inventory field: " trim(command-field(ws-field))
            into result-message
        end-string
        perform reject-operation
    end-if.

find-item.
    move 0 to ws-item
    perform varying ws-index from 1 by 1 until ws-index > item-count
        if item-id(ws-index) = ws-value
            move ws-index to ws-item
            exit perform
        end-if
    end-perform.

format-number.
    move ws-number to ws-edited
    move trim(ws-edited) to ws-text.

append-row.
    string trim(ws-row trailing) x"0a" into result-output
        with pointer ws-pointer
        on overflow
            move spaces to result-output
            move "Report exceeds output capacity" to result-message
            perform reject-operation
    end-string.

reject-operation.
    move 2 to result-code
    move 0 to result-mutating.
end program MD-INVENTORY.
