       01 app-state.
          05 closed-through             pic 9(8).
          05 account-count              binary-long.
          05 accounts occurs 200.
             10 account-id              pic x(12).
             10 account-kind            pic x(10).
             10 account-name            pic x(80).
             10 account-balance         pic s9(14) comp-3.
          05 entry-count                binary-long.
          05 entries occurs 4096.
             10 entry-ref               pic x(32).
             10 entry-date              pic 9(8).
             10 entry-debit             pic x(12).
             10 entry-credit            pic x(12).
             10 entry-amount            pic 9(12) comp-3.
             10 entry-memo              pic x(100).
             10 entry-reversed-by       pic x(32).
             10 entry-source            pic x(10).
          05 item-count                 binary-long.
          05 items occurs 500.
             10 item-id                 pic x(12).
             10 item-name               pic x(80).
             10 item-quantity           pic 9(9) comp-3.
             10 item-cost               pic 9(10) comp-3.
             10 item-reorder            pic 9(9) comp-3.
          05 movement-count             binary-long.
          05 movements occurs 4096.
             10 movement-ref            pic x(32).
             10 movement-date           pic 9(8).
             10 movement-item           pic x(12).
             10 movement-quantity       pic s9(9) comp-3.
             10 movement-reason         pic x(80).
          05 customer-count             binary-long.
          05 customers occurs 500.
             10 customer-id             pic x(12).
             10 customer-name           pic x(80).
             10 customer-email          pic x(100).
          05 invoice-count              binary-long.
          05 invoices occurs 500.
             10 invoice-id              pic x(24).
             10 invoice-customer        pic x(12).
             10 invoice-date            pic 9(8).
             10 invoice-due             pic 9(8).
             10 invoice-status          pic x(8).
             10 invoice-line-count      binary-long.
             10 invoice-net             pic 9(12) comp-3.
             10 invoice-tax             pic 9(12) comp-3.
             10 invoice-total           pic 9(12) comp-3.
             10 invoice-paid            pic 9(12) comp-3.
             10 invoice-lines occurs 30.
                15 line-item            pic x(12).
                15 line-quantity        pic 9(9) comp-3.
                15 line-price           pic 9(10) comp-3.
                15 line-tax-bps         pic 9(4) comp-3.
                15 line-net             pic 9(12) comp-3.
                15 line-tax             pic 9(12) comp-3.
          05 payment-count              binary-long.
          05 payments occurs 2048.
             10 payment-ref             pic x(32).
             10 payment-invoice         pic x(24).
             10 payment-date            pic 9(8).
             10 payment-amount          pic 9(12) comp-3.
