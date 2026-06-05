// Phase A — one typed function reads an AP document (receipt/invoice) image into
// structured fields AND decides its kind + payment state in a single cheap-model call.
// Folds the OCR extractor and the receipt/invoice classifier into one read.

enum DocKind {
  Receipt      @description("proof of a COMPLETED purchase / point-of-sale slip")
  Invoice      @description("a bill / request for payment owed")
  Statement
  CreditNote
  Other
}

enum PaymentState {
  Paid
  Unpaid
  Unknown
}

class LineItem {
  description  string
  quantity     float?
  unit_price   float?
  amount       float
  tax_amount   float?  @description("per-line tax if shown")
}

class Receipt {
  merchant       string
  merchant_ref   string?  @description("stable match key: address, domain, or store #")
  doc_number     string?  @description("invoice or receipt number, as printed")
  date           string?
  currency       string?  @description("ISO-4217 code if shown; else null")
  line_items     LineItem[]
  subtotal       float?
  tax            float?
  total          float?
  card_last4     string?
  kind           DocKind
  payment_state  PaymentState
  confidence     float    @description("overall 0-1 read confidence")
}

client<llm> CheapVision {
  provider "anthropic"
  options {
    model "claude-haiku-4-5-20251001"
    api_key env.ANTHROPIC_API_KEY
  }
}

function ReadReceipt(doc: image) -> Receipt {
  client CheapVision
  prompt #"
    {{ _.role("user") }}
    Read this accounts-payable document and extract its data exactly as printed.
    Pull: merchant name; a stable merchant reference (address / domain / store #);
    date; currency; EVERY line item (description, quantity, unit price, amount,
    per-line tax if shown); sales tax; subtotal; total; card last-4 if present.
    Then decide `kind` and `payment_state` from the content (a completed/paid
    point-of-sale slip is a Receipt; a bill with an amount due is an Invoice).
    Judge only from what is printed. Give an overall 0-1 confidence.

    {{ doc }}

    {{ ctx.output_format }}
  "#
}

function ReadReceiptPdf(doc: pdf) -> Receipt {
  client CheapVision
  prompt #"
    {{ _.role("user") }}
    Read this accounts-payable document and extract its data exactly as printed.
    Pull: merchant name; a stable merchant reference (address / domain / store #);
    invoice/receipt number; date; currency; EVERY line item (description, quantity,
    unit price, amount, per-line tax if shown); sales tax; subtotal; total; card last-4.
    Then decide `kind` and `payment_state` from the content. Give a 0-1 confidence.

    {{ doc }}

    {{ ctx.output_format }}
  "#
}
