       >>source format free
identification division.
program-id. MD-SALES.
environment division.
data division.
working-storage section.
01 validation-value                  pic x(256).
01 validation-kind                   pic x(8).
01 validation-maximum                binary-long.
01 validation-ok                     binary-long.
01 validation-field                  binary-long.
01 validation-label                  pic x(80).
01 invoice-index                     binary-long.
01 customer-index                    binary-long.
01 item-index                        binary-long.
01 account-index                     binary-long.
01 loop-index                        binary-long.
01 scan-index                        binary-long.
01 line-index                        binary-long.
01 payment-index                     binary-long.
01 required-kind                     pic x(10).
01 account-field                     binary-long.
01 search-invoice                    pic x(24).
01 search-customer                   pic x(12).
01 search-item                       pic x(12).
01 quantity-input                    pic 9(9) comp-3.
01 price-input                       pic 9(10) comp-3.
01 tax-input                         pic 9(4) comp-3.
01 amount-input                      pic 9(12) comp-3.
01 wide-net                          pic 9(22) comp-3.
01 wide-tax                          pic 9(22) comp-3.
01 wide-product                      pic 9(22) comp-3.
01 wide-total                        pic 9(22) comp-3.
01 wide-cogs                         pic 9(22) comp-3.
01 inventory-demands.
   05 demand-quantity occurs 500      pic 9(12) comp-3.
01 movement-reference                pic x(32).
01 line-ordinal                      pic 9(3).
01 post-amount                       pic 9(12) comp-3.
01 post-debit                        pic x(12).
01 post-credit                       pic x(12).
01 post-reference                    pic x(32).
01 post-date                         pic 9(8).
01 post-memo                         pic x(100).
01 email-value                       pic x(100).
01 email-length                      binary-long.
01 email-at-position                 binary-long.
01 email-at-count                    binary-long.
01 email-domain-dot                  binary-long.
01 output-pointer                    binary-long.
01 row-buffer                        pic x(1024).
01 number-one                        pic z(21)9.
01 number-two                        pic z(21)9.
01 number-three                      pic z(21)9.
01 number-four                       pic z(21)9.
01 number-five                       pic z(21)9.
01 number-six                        pic z(21)9.
01 age-days                          binary-long.
01 age-bucket                        pic x(8).
01 age-slot                          binary-long.
01 aging-totals.
   05 age-total occurs 5              pic 9(22) comp-3.
01 age-count                         binary-long.
copy "request.cpy" replacing
    ==command-request== by ==posting-request==
    ==field-count== by ==posting-field-count==
    ==command-field== by ==posting-field==.
copy "result.cpy" replacing
    ==operation-result== by ==posting-result==
    ==result-code== by ==posting-code==
    ==result-mutating== by ==posting-mutating==
    ==result-message== by ==posting-message==
    ==result-output== by ==posting-output==.
linkage section.
copy "state.cpy".
copy "request.cpy".
copy "result.cpy".
procedure division using app-state command-request operation-result.
main.
    initialize operation-result
    move 1 to output-pointer
    evaluate function trim(command-field(1))
        when "CUSTOMER" perform create-customer
        when "INVOICE" perform create-invoice
        when "LINE" perform add-line
        when "ISSUE" perform issue-invoice
        when "PAY" perform receive-payment
        when "VOID" perform void-invoice
        when "CUSTOMERS" perform list-customers
        when "INVOICES" perform list-invoices
        when "INVOICE-SHOW" perform show-invoice
        when "AGING" perform show-aging
        when other
            move "Unknown sales command" to result-message
            perform fail-operation
    end-evaluate
    goback.

fail-operation.
    move 2 to result-code
    move 0 to result-mutating.

validate-field.
    move command-field(validation-field) to validation-value
    call "MD-VALIDATE" using validation-value validation-kind
        validation-maximum validation-ok
    end-call
    if validation-ok not = 1
        move spaces to result-message
        string "Invalid " function trim(validation-label)
            into result-message
        end-string
        perform fail-operation
    end-if.

lookup-invoice.
    move 0 to invoice-index
    perform varying scan-index from 1 by 1
        until scan-index > invoice-count
        if invoice-id(scan-index) = search-invoice
            move scan-index to invoice-index
            exit perform
        end-if
    end-perform.

lookup-customer.
    move 0 to customer-index
    perform varying scan-index from 1 by 1
        until scan-index > customer-count
        if customer-id(scan-index) = search-customer
            move scan-index to customer-index
            exit perform
        end-if
    end-perform.

lookup-item.
    move 0 to item-index
    perform varying scan-index from 1 by 1
        until scan-index > item-count
        if item-id(scan-index) = search-item
            move scan-index to item-index
            exit perform
        end-if
    end-perform.

require-invoice.
    move 2 to validation-field
    move "ID" to validation-kind
    move 24 to validation-maximum
    move "invoice ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:24) to search-invoice
    perform lookup-invoice
    if invoice-index = 0
        move "Invoice does not exist" to result-message
        perform fail-operation
    end-if.

require-draft.
    if invoice-status(invoice-index) not = "DRAFT"
        move "Invoice must be a draft" to result-message
        perform fail-operation
    end-if.

validate-account.
    move account-field to validation-field
    move "ID" to validation-kind
    move 12 to validation-maximum
    move "account ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 0 to account-index
    perform varying scan-index from 1 by 1
        until scan-index > account-count
        if account-id(scan-index) = command-field(account-field)
            move scan-index to account-index
            exit perform
        end-if
    end-perform
    if account-index = 0
        move "Account does not exist" to result-message
        perform fail-operation
    else
        if account-kind(account-index) not = required-kind
            move spaces to result-message
            string "Account must have kind "
                function trim(required-kind) into result-message
            end-string
            perform fail-operation
        end-if
    end-if.

create-customer.
    if field-count not = 4
        move "CUSTOMER expects 3 arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 2 to validation-field
    move "ID" to validation-kind
    move 12 to validation-maximum
    move "customer ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 3 to validation-field
    move "TEXT" to validation-kind
    move 80 to validation-maximum
    move "customer name" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 4 to validation-field
    move 100 to validation-maximum
    move "customer email" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move command-field(4)(1:100) to email-value
    move function length(function trim(email-value)) to email-length
    move 0 to email-at-count email-at-position email-domain-dot
    perform varying loop-index from 1 by 1
        until loop-index > email-length
        evaluate email-value(loop-index:1)
            when "@"
                add 1 to email-at-count end-add
                move loop-index to email-at-position
            when space
                move "Invalid customer email" to result-message
                perform fail-operation
            when "."
                if email-at-position > 0
                    and loop-index > email-at-position + 1
                    and loop-index < email-length
                    move 1 to email-domain-dot
                end-if
        end-evaluate
    end-perform
    if email-at-count not = 1 or email-at-position < 2
        or email-at-position >= email-length
        or email-domain-dot = 0
        move "Invalid customer email" to result-message
        perform fail-operation
    end-if
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:12) to search-customer
    perform lookup-customer
    if customer-index > 0
        move "Customer ID already exists" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if customer-count >= 500
        move "Customer capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    add 1 to customer-count end-add
    move command-field(2)(1:12) to customer-id(customer-count)
    move command-field(3)(1:80) to customer-name(customer-count)
    move command-field(4)(1:100) to customer-email(customer-count)
    move 1 to result-mutating
    move "Customer created" to result-message.

create-invoice.
    if field-count not = 5
        move "INVOICE expects 4 arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 2 to validation-field
    move "ID" to validation-kind
    move 24 to validation-maximum
    move "invoice ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 3 to validation-field
    move 12 to validation-maximum
    move "customer ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 4 to validation-field
    move "DATE" to validation-kind
    move 8 to validation-maximum
    move "invoice date" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 5 to validation-field
    move "due date" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    if command-field(5)(1:8) < command-field(4)(1:8)
        move "Due date cannot precede invoice date" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move command-field(2)(1:24) to search-invoice
    perform lookup-invoice
    if invoice-index > 0
        move "Invoice ID already exists" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move command-field(3)(1:12) to search-customer
    perform lookup-customer
    if customer-index = 0
        move "Customer does not exist" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if invoice-count >= 500
        move "Invoice capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    add 1 to invoice-count end-add
    initialize invoices(invoice-count)
    move command-field(2)(1:24) to invoice-id(invoice-count)
    move command-field(3)(1:12) to invoice-customer(invoice-count)
    move command-field(4)(1:8) to invoice-date(invoice-count)
    move command-field(5)(1:8) to invoice-due(invoice-count)
    move "DRAFT" to invoice-status(invoice-count)
    move 1 to result-mutating
    move "Invoice draft created" to result-message.

add-line.
    if field-count not = 6
        move "LINE expects 5 arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform require-invoice
    if result-code not = 0 exit paragraph end-if
    perform require-draft
    if result-code not = 0 exit paragraph end-if
    move 3 to validation-field
    move "ID" to validation-kind
    move 12 to validation-maximum
    move "SKU" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 4 to validation-field
    move "UINT" to validation-kind
    move 9 to validation-maximum
    move "line quantity" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(4)) to quantity-input
    if quantity-input = 0
        move "Line quantity must be positive" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 5 to validation-field
    move 10 to validation-maximum
    move "unit price" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(5)) to price-input
    if price-input = 0
        move "Unit price must be positive" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 6 to validation-field
    move 4 to validation-maximum
    move "tax basis points" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(6)) to tax-input
    move command-field(3)(1:12) to search-item
    perform lookup-item
    if item-index = 0
        move "Item does not exist" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if invoice-line-count(invoice-index) >= 30
        move "Invoice line capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    compute wide-net = quantity-input * price-input
    end-compute
    if wide-net > 999999999999
        move "Invoice amount exceeds monetary limit" to result-message
        perform fail-operation
        exit paragraph
    end-if
    compute wide-product = wide-net * tax-input + 5000 end-compute
    compute wide-tax = function integer(wide-product / 10000) end-compute
    compute wide-total = invoice-total(invoice-index)
        + wide-net + wide-tax
    end-compute
    if wide-net > 999999999999 or wide-tax > 999999999999
        or wide-total > 999999999999
        move "Invoice amount exceeds monetary limit" to result-message
        perform fail-operation
        exit paragraph
    end-if
    add 1 to invoice-line-count(invoice-index) end-add
    move invoice-line-count(invoice-index) to line-index
    move search-item to line-item(invoice-index, line-index)
    move quantity-input to line-quantity(invoice-index, line-index)
    move price-input to line-price(invoice-index, line-index)
    move tax-input to line-tax-bps(invoice-index, line-index)
    compute line-net(invoice-index, line-index) = wide-net end-compute
    compute line-tax(invoice-index, line-index) = wide-tax end-compute
    add wide-net to invoice-net(invoice-index) end-add
    add wide-tax to invoice-tax(invoice-index) end-add
    compute invoice-total(invoice-index) = wide-total end-compute
    move 1 to result-mutating
    move "Invoice line added" to result-message.

issue-invoice.
    if field-count not = 7
        move "ISSUE expects 6 arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform require-invoice
    if result-code not = 0 exit paragraph end-if
    perform require-draft
    if result-code not = 0 exit paragraph end-if
    if invoice-line-count(invoice-index) = 0
        move "Cannot issue an empty invoice" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if invoice-date(invoice-index) <= closed-through
        move "Invoice date is in a closed period" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 3 to account-field
    move "ASSET" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    move 4 to account-field
    move "REVENUE" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    move 5 to account-field
    move "LIABILITY" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    move 6 to account-field
    move "EXPENSE" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    move 7 to account-field
    move "ASSET" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    if command-field(3) = command-field(7)
        move "Receivables and inventory accounts must differ"
            to result-message
        perform fail-operation
        exit paragraph
    end-if
    if movement-count + invoice-line-count(invoice-index) > 4096
        move "Inventory movement capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 2 to quantity-input
    if invoice-tax(invoice-index) > 0
        add 1 to quantity-input end-add
    end-if
    if entry-count + quantity-input > 4096
        move "Ledger entry capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    initialize inventory-demands
    move 0 to wide-cogs
    perform varying line-index from 1 by 1
        until line-index > invoice-line-count(invoice-index)
        or result-code not = 0
        move line-item(invoice-index, line-index) to search-item
        perform lookup-item
        if item-index = 0
            move "Invoice item does not exist" to result-message
            perform fail-operation
        else
            add line-quantity(invoice-index, line-index)
                to demand-quantity(item-index)
            end-add
            compute wide-product =
                line-quantity(invoice-index, line-index)
                * item-cost(item-index)
            end-compute
            add wide-product to wide-cogs end-add
            if wide-cogs > 999999999999
                move "Cost of goods exceeds monetary limit"
                    to result-message
                perform fail-operation
            end-if
        end-if
        perform build-movement-reference
        perform varying loop-index from 1 by 1
            until loop-index > movement-count
            or result-code not = 0
            if movement-ref(loop-index) = movement-reference
                move "Invoice movement reference already exists"
                    to result-message
                perform fail-operation
            end-if
        end-perform
    end-perform
    if result-code not = 0 exit paragraph end-if
    perform varying loop-index from 1 by 1 until loop-index > item-count
        if demand-quantity(loop-index) > item-quantity(loop-index)
            move spaces to result-message
            string "Insufficient stock for "
                function trim(item-id(loop-index)) into result-message
            end-string
            perform fail-operation
            exit perform
        end-if
    end-perform
    if result-code not = 0 exit paragraph end-if
    move invoice-date(invoice-index) to post-date
    move "Invoice revenue" to post-memo
    move spaces to post-reference
    string function trim(invoice-id(invoice-index)) "_REV"
        into post-reference end-string
    move command-field(3)(1:12) to post-debit
    move command-field(4)(1:12) to post-credit
    move invoice-net(invoice-index) to post-amount
    perform post-to-ledger
    if result-code not = 0 exit paragraph end-if
    if invoice-tax(invoice-index) > 0
        move spaces to post-reference
        string function trim(invoice-id(invoice-index)) "_TAX"
            into post-reference end-string
        move "Invoice sales tax" to post-memo
        move command-field(5)(1:12) to post-credit
        move invoice-tax(invoice-index) to post-amount
        perform post-to-ledger
    end-if
    if result-code not = 0 exit paragraph end-if
    move spaces to post-reference
    string function trim(invoice-id(invoice-index)) "_COGS"
        into post-reference end-string
    move command-field(6)(1:12) to post-debit
    move command-field(7)(1:12) to post-credit
    move "Invoice cost of goods" to post-memo
    compute post-amount = wide-cogs end-compute
    perform post-to-ledger
    if result-code not = 0 exit paragraph end-if
    perform varying line-index from 1 by 1
        until line-index > invoice-line-count(invoice-index)
        move line-item(invoice-index, line-index) to search-item
        perform lookup-item
        subtract line-quantity(invoice-index, line-index)
            from item-quantity(item-index)
        end-subtract
        perform build-movement-reference
        add 1 to movement-count end-add
        move movement-reference to movement-ref(movement-count)
        move invoice-date(invoice-index) to movement-date(movement-count)
        move search-item to movement-item(movement-count)
        compute movement-quantity(movement-count) =
            0 - line-quantity(invoice-index, line-index)
        end-compute
        move spaces to movement-reason(movement-count)
        string "Invoice " function trim(invoice-id(invoice-index))
            into movement-reason(movement-count) end-string
    end-perform
    move "OPEN" to invoice-status(invoice-index)
    move 1 to result-mutating
    move "Invoice issued" to result-message.

build-movement-reference.
    compute line-ordinal = line-index end-compute
    move spaces to movement-reference
    string function trim(invoice-id(invoice-index)) "_" line-ordinal
        into movement-reference end-string.

post-to-ledger.
    initialize posting-request posting-result
    move 7 to posting-field-count
    move "POST" to posting-field(1)
    move post-reference to posting-field(2)
    move post-date to posting-field(3)
    move post-debit to posting-field(4)
    move post-credit to posting-field(5)
    move post-amount to number-one
    move function trim(number-one) to posting-field(6)
    move post-memo to posting-field(7)
    call "MD-LEDGER" using app-state posting-request posting-result
    end-call
    if posting-code not = 0
        move posting-message to result-message
        perform fail-operation
    else
        if command-field(1) = "PAY"
            move "PAYMENT" to entry-source(entry-count)
        else
            move "INVOICE" to entry-source(entry-count)
        end-if
    end-if.

receive-payment.
    if field-count not = 7
        move "PAY expects 6 arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 2 to validation-field
    move "ID" to validation-kind
    move 32 to validation-maximum
    move "payment reference" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move 3 to validation-field
    move 24 to validation-maximum
    move "invoice ID" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move command-field(3)(1:24) to search-invoice
    perform lookup-invoice
    if invoice-index = 0
        move "Invoice does not exist" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if invoice-status(invoice-index) not = "OPEN"
        move "Only open invoices accept payments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 4 to validation-field
    move "DATE" to validation-kind
    move 8 to validation-maximum
    move "payment date" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    if command-field(4)(1:8) < invoice-date(invoice-index)
        move "Payment date cannot precede invoice date"
            to result-message
        perform fail-operation
        exit paragraph
    end-if
    if function numval(command-field(4)) <= closed-through
        move "Payment date is in a closed period" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 5 to validation-field
    move "UINT" to validation-kind
    move 12 to validation-maximum
    move "payment amount" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    move function numval(command-field(5)) to amount-input
    if amount-input = 0
        move "Payment amount must be positive" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if amount-input > invoice-total(invoice-index)
        - invoice-paid(invoice-index)
        move "Payment exceeds outstanding invoice amount"
            to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 6 to account-field
    move "ASSET" to required-kind
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    move 7 to account-field
    perform validate-account
    if result-code not = 0 exit paragraph end-if
    if command-field(6) = command-field(7)
        move "Cash and receivables accounts must differ"
            to result-message
        perform fail-operation
        exit paragraph
    end-if
    move spaces to post-reference
    string function trim(invoice-id(invoice-index)) "_REV"
        into post-reference end-string
    move 0 to account-index
    perform varying loop-index from 1 by 1
        until loop-index > entry-count
        if entry-ref(loop-index) = post-reference
            move loop-index to account-index
            exit perform
        end-if
    end-perform
    if account-index = 0
        move "Invoice revenue posting is missing" to result-message
        perform fail-operation
        exit paragraph
    end-if
    if entry-debit(account-index) not = command-field(7)
        move "Payment must use the invoice receivables account"
            to result-message
        perform fail-operation
        exit paragraph
    end-if
    if payment-count >= 2048
        move "Payment capacity reached" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform varying loop-index from 1 by 1
        until loop-index > payment-count
        if payment-ref(loop-index) = command-field(2)
            move "Payment reference already exists" to result-message
            perform fail-operation
            exit perform
        end-if
    end-perform
    if result-code not = 0 exit paragraph end-if
    move command-field(2)(1:32) to post-reference
    move command-field(4)(1:8) to post-date
    move command-field(6)(1:12) to post-debit
    move command-field(7)(1:12) to post-credit
    move amount-input to post-amount
    move spaces to post-memo
    string "Payment for " function trim(invoice-id(invoice-index))
        into post-memo end-string
    perform post-to-ledger
    if result-code not = 0 exit paragraph end-if
    add 1 to payment-count end-add
    move command-field(2)(1:32) to payment-ref(payment-count)
    move invoice-id(invoice-index) to payment-invoice(payment-count)
    move command-field(4)(1:8) to payment-date(payment-count)
    move amount-input to payment-amount(payment-count)
    add amount-input to invoice-paid(invoice-index) end-add
    if invoice-paid(invoice-index) = invoice-total(invoice-index)
        move "PAID" to invoice-status(invoice-index)
    end-if
    move 1 to result-mutating
    move "Payment recorded" to result-message.

void-invoice.
    if field-count not = 2
        move "VOID expects 1 argument" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform require-invoice
    if result-code not = 0 exit paragraph end-if
    perform require-draft
    if result-code not = 0 exit paragraph end-if
    move "VOID" to invoice-status(invoice-index)
    move 1 to result-mutating
    move "Invoice draft voided" to result-message.

append-row.
    string function trim(row-buffer trailing) x"0a"
        into result-output with pointer output-pointer
        on overflow
            move "Response capacity exceeded" to result-message
            perform fail-operation
    end-string.

list-customers.
    if field-count not = 1
        move "CUSTOMERS expects no arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform varying customer-index from 1 by 1
        until customer-index > customer-count or result-code not = 0
        move spaces to row-buffer
        string "CUSTOMER|" function trim(customer-id(customer-index))
            "|" function trim(customer-name(customer-index))
            "|" function trim(customer-email(customer-index))
            into row-buffer end-string
        perform append-row
    end-perform
    if result-code = 0 move "Customers" to result-message end-if.

build-invoice-row.
    move invoice-net(invoice-index) to number-one
    move invoice-tax(invoice-index) to number-two
    move invoice-total(invoice-index) to number-three
    move invoice-paid(invoice-index) to number-four
    compute wide-total = invoice-total(invoice-index)
        - invoice-paid(invoice-index)
    end-compute
    move wide-total to number-five
    move invoice-line-count(invoice-index) to number-six
    move spaces to row-buffer
    string "INVOICE|" function trim(invoice-id(invoice-index)) "|"
        function trim(invoice-customer(invoice-index)) "|"
        invoice-date(invoice-index) "|" invoice-due(invoice-index) "|"
        function trim(invoice-status(invoice-index)) "|"
        function trim(number-one) "|" function trim(number-two) "|"
        function trim(number-three) "|" function trim(number-four) "|"
        function trim(number-five) "|" function trim(number-six)
        into row-buffer end-string.

list-invoices.
    if field-count not = 1
        move "INVOICES expects no arguments" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform varying invoice-index from 1 by 1
        until invoice-index > invoice-count or result-code not = 0
        perform build-invoice-row
        perform append-row
    end-perform
    if result-code = 0 move "Invoices" to result-message end-if.

show-invoice.
    if field-count not = 2
        move "INVOICE-SHOW expects 1 argument" to result-message
        perform fail-operation
        exit paragraph
    end-if
    perform require-invoice
    if result-code not = 0 exit paragraph end-if
    perform build-invoice-row
    perform append-row
    perform varying line-index from 1 by 1
        until line-index > invoice-line-count(invoice-index)
        or result-code not = 0
        move line-index to number-one
        move line-quantity(invoice-index, line-index) to number-two
        move line-price(invoice-index, line-index) to number-three
        move line-tax-bps(invoice-index, line-index) to number-four
        move line-net(invoice-index, line-index) to number-five
        move line-tax(invoice-index, line-index) to number-six
        move spaces to row-buffer
        string "LINE|" function trim(number-one) "|"
            function trim(line-item(invoice-index, line-index)) "|"
            function trim(number-two) "|" function trim(number-three) "|"
            function trim(number-four) "|" function trim(number-five) "|"
            function trim(number-six) into row-buffer end-string
        perform append-row
    end-perform
    perform varying payment-index from 1 by 1
        until payment-index > payment-count or result-code not = 0
        if payment-invoice(payment-index) = invoice-id(invoice-index)
            move payment-amount(payment-index) to number-one
            move spaces to row-buffer
            string "PAYMENT|"
                function trim(payment-ref(payment-index)) "|"
                payment-date(payment-index) "|"
                function trim(number-one) into row-buffer end-string
            perform append-row
        end-if
    end-perform
    if result-code = 0 move "Invoice details" to result-message end-if.

show-aging.
    if field-count not = 2
        move "AGING expects 1 argument" to result-message
        perform fail-operation
        exit paragraph
    end-if
    move 2 to validation-field
    move "DATE" to validation-kind
    move 8 to validation-maximum
    move "aging date" to validation-label
    perform validate-field
    if result-code not = 0 exit paragraph end-if
    initialize aging-totals
    move 0 to age-count
    perform varying invoice-index from 1 by 1
        until invoice-index > invoice-count or result-code not = 0
        if invoice-status(invoice-index) = "OPEN"
            compute wide-total = invoice-total(invoice-index)
                - invoice-paid(invoice-index)
            end-compute
            compute age-days = function integer-of-date(
                function numval(command-field(2)))
                - function integer-of-date(invoice-due(invoice-index))
            end-compute
            evaluate true
                when age-days <= 0
                    move "CURRENT" to age-bucket
                    move 1 to age-slot
                    move 0 to age-days
                when age-days <= 30
                    move "1-30" to age-bucket
                    move 2 to age-slot
                when age-days <= 60
                    move "31-60" to age-bucket
                    move 3 to age-slot
                when age-days <= 90
                    move "61-90" to age-bucket
                    move 4 to age-slot
                when other
                    move "OVER90" to age-bucket
                    move 5 to age-slot
            end-evaluate
            add wide-total to age-total(age-slot) end-add
            add 1 to age-count end-add
            move age-days to number-one
            move wide-total to number-two
            move spaces to row-buffer
            string "AGE|"
                function trim(invoice-customer(invoice-index)) "|"
                function trim(invoice-id(invoice-index)) "|"
                invoice-due(invoice-index) "|"
                function trim(number-one) "|"
                function trim(age-bucket) "|"
                function trim(number-two) into row-buffer end-string
            perform append-row
        end-if
    end-perform
    if result-code not = 0 exit paragraph end-if
    move age-total(1) to number-one
    move age-total(2) to number-two
    move age-total(3) to number-three
    move age-total(4) to number-four
    move age-total(5) to number-five
    move age-count to number-six
    move spaces to row-buffer
    string "AGE-TOTAL|" function trim(number-one) "|"
        function trim(number-two) "|" function trim(number-three) "|"
        function trim(number-four) "|" function trim(number-five) "|"
        function trim(number-six) into row-buffer end-string
    perform append-row
    if result-code = 0 move "Current receivables aging" to result-message
        end-if.
end program MD-SALES.
