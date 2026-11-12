# VIZCRM functional spec

What the system must *do*, written from reference screenshots of how an existing
laundry POS behaves (`screenshots/`, not committed). This records behavior, data
and rules only — layout, styling, icons and wording are ours to design.

Coverage: all 113 screenshots reviewed.

---

## 1. Core concepts

| Concept | Notes |
|---|---|
| **Company** | Name and primary contact details (contact, phone, email, website). Owns one or more stores, which share its catalog (sections, products, price lists, upcharges) and customers. Order numbers count across the company. |
| **Store** | Name, address, phone, tax ID, hours, shifts, turnaround and order settings, including its express-price multiplier; its own orders. Can set its own price for a product or not sell it. |
| **Station** | A till/register in a store (e.g. "Station 1"). Cash-ups are per station. |
| **Section** | Top-level product grouping and order-entry tab: Dry Cleaning, Laundry, Pressed/Ironed, Repairs, Alterations, Retail. |
| **Product** | A sellable item in a section (Suit, Duvet, Laundry per lb…). |
| **Price list** | Named set of prices ("Default", per business, per customer). |
| **Customer** | Individual or linked to a **Business account**. Shared by the company's stores; remembers the store they were added at. |
| **Order** | Items + due date + status + payments. Types: in-store, quick drop, pickup & delivery, retail sale. |
| **Item / garment** | One physical piece within an order line, with its own attributes and barcode. |
| **Rack slot** | Numbered storage location for finished orders (1–N, or codes like "A-42"). |
| **Route** | Delivery area: geofence polygon + time slots + closed dates. |

---

## 2. Order lifecycle

```
Created ──► Detailing (optional) ──► Cleaning ──► Ready (racked) ──► Collected / Delivered
                  │                       │
                  └────── Issue raised ◄──┘   (issue has stage, text, reporter, solved flag)
```

- **Detailing stage** is optional (setting). Which orders go there is configurable:
  all / only quick-drop / limited to sections; pickup & delivery orders can be
  sent to detailing.
- **Mark Cleaned** can prompt for: rack location (default on), number of bags and
  hanging items, re-weigh of weight-priced products.
- **Ready** orders show rack, bags, pieces, hanging count, days waiting, paid status.
- **Collected** closes the order; payment is taken here if unpaid.
- Orders can be archived automatically after N days (setting, default never).
- Every change is recorded in an order **timeline** (status, edits, payments, messages).
- **Order edits** and **order deletions** are audited (who, when, what). An edit-log row is a
  snapshot: summary, total, status, discount, credit, price list, payment, ready-by, editor, time;
  the creation snapshot reads "Created by". Deletions record a **reason**.
- Photos can be attached to an order (or one of its items).

### Order board (staff)
- Tabs per stage: Detailing · Cleaning · Ready · Issues.
- Each tab: filter by section, filter by due date, search; totals for
  orders / pieces / weight (and unpaid $ on Ready).
- Columns: ID, customer, summary ("3 pieces, 2 bags"), inline-editable notes,
  bags, pieces, paid, ready-by; row actions: print ticket, edit, stage action
  (Detail / Cleaned / Payment).
- Bulk select rows; pagination with rows-per-page.
- **Issues** tab: open/all, search; columns ID, customer, issue text, stage,
  ready-by, reported (time + staff); action Mark Solved, which asks for an
  **explanation** of how it was resolved. "New Issue" button picks the order.

### Order detail
- Header: order #, customer, status, rack, due date, total, paid state, invoice state.
- Actions: edit, report issue, more menu, primary next-step (e.g. Collected).
- Items table (item, garment barcode ID, notes), order notes, collapsible timeline.

---

## 3. Order entry (POS)

### Start
- Home has a single search box: customer name or phone. Also **Add Customer**,
  **Retail Sale** (anonymous "Retail Customer"), and a promo/discount shortcut.
- Home summary cards: Detailing (pieces, bags, orders), Cleaning (overdue / due
  today / due tomorrow, toggle orders · pieces · kg), Tasks (mine / all staff),
  and the last order with edit/print/detail.
- From a customer: **New Order** → choose **In-Store Order**, **Quick Drop**
  (take bag without itemising; itemise later in Detailing), or **Pickup & Delivery**.

### Item selection
- Section tabs with a count badge of items selected per section.
- Product grid: tap to add (+1), minus to remove; quantity badge per tile.
  Tiles: Custom Item (free-text name + price), Photo (attach image).
- Weight-priced products (e.g. "Laundry per lb") prompt for weight / use a scale.
- Search products; promo/discount button.

### Cart panel
- Customer name, loyalty points.
- **Price list** selector (defaults from customer, else store default).
- **Express** toggle → uses each product's express price and express turnaround.
- Lines: qty, product, per-piece attribute summary, line total.
- Order notes; due date/time (auto from turnaround rules, editable).
- Total (expandable for subtotal / tax / discount); **Create Order** with piece count.

### Item details (per garment)
Opened by tapping a line. Quantity N creates N individual pieces ("Suit 1…3"),
each selectable and editable separately (or apply to all checked). Copy / delete piece.

| Attribute | Behavior |
|---|---|
| Colors | Quick list + "More" (≈40 total), **max 2**, some with swatches |
| Upcharges | Product-specific extra charges |
| Notes | Free text ("extra starch") |
| Barcode ID | Scan or type the garment tag |
| Damage | Pick list, **max 3** (hole, tear, missing button, iron shine, faded…) |
| Stains | Pick list, **max 3** |
| Brand | One brand, from a long searchable list |
| Materials, Patterns, Style | Pick lists, **max 3** each |

- Price total for the line, with manual price **Edit** (permission-controlled).
- Product setting **Request Item Details**: when to force this screen (e.g. quick, when pressed).

### Retail sale
- Retail section only (e.g. lint roller), anonymous customer; option to require payment.

---

## 4. Assembly / racks
- Rack table 1…N: rack #, order, customer, garment IDs, items (x of y), status.
- Scan/enter a **garment ID** → assign to its order's slot; status shows
  completeness as pieces arrive.
- **Empty a slot** when collected.
- Product fields used by assembly / conveyor: slot space, conveyor priority,
  conveyor bag (bag item / …), skip conveyor, require heat-seal tag.
- Settings: use assisted assembly (rack garments by scanning, grouped by order);
  number of rack locations; pieces per rack location; remove order from assembly
  when (e.g. order completed); automatically mark cleaned when all garments
  scanned; automatically print receipt then; use pre-printed barcode labels.

---

## 5. Customers

### Customer profile
- Active orders (status, due date, total), View All.
- Overview: total orders, lifetime value, average order, unpaid; tenure (days as customer).
- Customer list: name, phone, address, days as customer, last review; search; rows per page.
- Details: route, subscription, repeat pickups, loyalty points, store credit,
  business account, groups, tenure; **Print Barcode** (customer card).
- Communication thread: automated notifications (order created / cleaned) plus
  two-way messages; reply via email / SMS.

### Edit customer (tabs)
- **General:** name*, telephone*, email, default notification method, marketing opt-in, delete.
- **Billing:** business account (+ add), default price list, default payment type,
  discount %, credit $ (both permission-controlled).
- **Address**, **Preferences**, **Notes**.

### Business accounts
- A business (e.g. a hotel) whose customers' orders are billed together. No departments.

### Customer groups
- Named groups used for pricing/marketing (Settings → Workflow → Customers).

---

## 6. Products & pricing
- Product fields: name*, section*, type* (normal / weight / …), active in price lists,
  button image, overlay text, price*, express price*, cost price, minimum price,
  minimum quantity, pieces per product*, extra days (turnaround), ID/SKU,
  assembly fields (see §4), active, available online.
- Button image is picked from an icon library (black / white / colour garment icons,
  plus supplies: stain removers, softeners, detergents) or uploaded.
- Retail goods count **0 pieces**.
- Products menu also has Item Notes, Preferences and Barcode Labels pages (not captured).
- Product lists per section, with a price list picker to show that list's prices;
  drag to reorder; **bulk update** (pick products by section; price, express, cost,
  minimum price, extra days, active, online, request item details; "Review changes"
  shows old → new before submitting).
- Price lists; product discount rules (by time / day).
- Order pricing defaults: default price list, first-order discount %, minimum order,
  minimum for express.
- Turnaround: default (e.g. "2 days, 5pm"), express turnaround, excluded weekdays,
  store closed dates — due dates skip these.
- Split tickets: every X pieces, by slot space, by section.

---

## 7. Payments, cash & invoicing

### Payment settings
- Default payment method (e.g. **Pay Later**), optional methods (cash, card, …).
- Auto-charge saved card when order cleaned (none / P&D only / all).
- Round order total (rule + scope); cash payment discount %.
- Require saved card to create order; require payment for retail.
- Card provider integration with terminal; ask for tip on terminal; let customers add
  a card in the app. Laundromat machine payment systems (later).
- Tips: accept tips (split among the staff who handled the order); calculate with payroll;
  **tip split %**: staff who created / cleaned / completed the order, pickup driver,
  delivery driver. Type (amount / % / both), preset amounts and percentages.
- Cash-up settings: enable cash-ups; force starting cash at beginning of shift;
  track cash drawer payouts (shown in cash-ups and a Payouts report).

### Cash register
- Per station: open register (opening cash), estimated cash, activity this period
  (orders, invoices, pay-ins, pay-outs), **Complete Cash Up** (count vs expected → variance).
- History of cash-ups. Permissions control seeing expected/variance.

### Invoices (business / account customers)
- New invoice: bill-to account; date range **Monthly** (billing month) / **Custom** /
  **All Unpaid**; payment due date; invoice date; which order date to use
  (cleaned / created); discount %; tax calculation method.
- Live preview: store header, invoice #, dates, bill-to, orders, subtotal, total.
- Invoices list (filter business / customer, status): ID, recipient, reference (e.g.
  "October 2026"), date, due date (red when overdue), status (Unpaid / Paid (Card) + date),
  sent, total; actions pay, view, download, email, delete.
- **Drafts**: business accounts with unpaid orders (count, total) → Create Invoice.
- **Scheduled**: recipient, frequency (monthly), day of month, days to pay, discount %,
  order date source, automatically email, automatically charge saved card.
- **Statements** (customer or business): period (this month / last month / this quarter /
  custom), opening balance, invoiced, payments, balance due, account activity; email it.
- Settings: invoice style (group by orders), pay-by-invoice only for business accounts,
  allow partial payment, show order summaries / notes, skip repeat invoice with no
  orders, invoice prefix, payment terms (default NET 30); for customer and business
  invoices separately: payment due days, overdue reminders, payment instructions.
- Email when invoice paid.

### Discounts & promos
- Loyalty points scheme (points convert to store credit); referral codes.
- Promo codes: code, type (e.g. % for one order), discount, max uses, show in POS,
  expiry, where usable (account create / in-store / P&D / lockers), assign customer to business.
- Product discount rules: name, discount, scope, date range, time, weekdays.
- Promo carousels for the customer app: title, text, active.

### Tax
- Up to 3 named tax rates; tax added on top of price or included; tax/VAT ID.

---

## 8. Pickup & delivery

### Delivery board
- Tabs: **Orders** (by day), **Scheduled** (repeat pickups), **Driver History**.
- Date picker; totals: pickups done/total, deliveries done/total, bags, pieces, late, reschedule.
- List / **Map** view; filter; search; New Pickup.
- Columns: ID, customer, address, route, bags, pieces, summary, status, type
  (pickup / delivery), time slot, driver + ETA; edit, detail.

### Routes (settings)
- Route: general, **geofence** (draw polygon; generate from point as circle of
  diameter km/mi or by drive time; drag/add/remove corners), **time slots**
  per weekday (e.g. 8–10 AM, "pickup & delivery", max 10 per slot),
  **closed dates**. View out-of-service-area requests. Reassign customers to routes.
- Closed date: optionally reschedule repeat pickups to another date; apply to all routes.
- Scheduled tab has a map with pan / circle / polygon selection; Driver History shows
  each driver's path and stops on a map for a day.
- General P&D settings; Uber courier integration.

### General settings
- Enable P&D (own drivers). Account creation: create-order-before-account flow, assign
  route on signup by geofence, address check before signup, preferences to ask for,
  where to show the promo box, terms & conditions.
- Customer order flow (choose items, or just book), ask how many bags.
- Turnaround: customers book a delivery slot; days of slots shown; earliest pickup
  (today / anytime); minimum hours between pickup and delivery; days to skip.
- Customer changes: cancel up to X h before pickup, edit order X h before, edit
  delivery slot X h before. Optional app features: sell gift cards, pricing page.

### Pricing & fees
- P&D default price list, minimum order, first-order discount, allow customer price lists.
- Delivery fee $ for orders under $X; super-express and express fees ($ or %) by turnaround hours;
  exclude delivery fee from discounts; delivery fee tax exemptions; "nothing to pick up" fee.
- Tips for P&D: type (amount / % / both, default shown), preset amounts and percentages.

### Repeat pickups
- Enable; price list; default flow (e.g. auto-create order 24h before);
  discount scheme (%, extra % from repeat order, stop after N orders).

### Driver app settings
- Track driver location; show rack location for deliveries; messenger; require
  photo (off / pickup / delivery / both); extra advance notification;
  allow payment (delivery only / …); station to assign payment to; hide cash option.

### Lockers
- Enable; minimum order; delivery fee and threshold; when to prompt for locker & code;
  locker locations (name, address, # lockers, range, active).

---

## 9. Wash & fold / machines
- Optional tracking: assign orders to washers, dryers, ironing and folding locations.
- Ask for washer/dryer cycle; auto-recommend free machine; optional stages; default
  action when complete; sections shown; label machines by name/number.
- Machine payouts from cash drawer, amount increment; machine notifications; maintenance reminders.
- Washers/dryers: default cycle, time, selectable times, amount; lists of machines,
  cycles, sub-cycles, modifiers.
- Third-party machine integrations (later).

---

## 10. Communication
- Notifications per order type (in-store, P&D): default channel (SMS / email / push),
  which events to send (order created, cleaned/ready, edited & total changed,
  driver on the way, …), staff alert email/SMS for new pickups.
- Reminders if ready > 7 days (email / SMS).
- Push via customer app with email/SMS fallback.
- SMS credit balance, auto top-up, delay SMS after cleaned. WhatsApp (later).
- Payment notices: email when invoice paid; tell customer when auto-charge fails.
- **Reviews** settings: send requests by (channel), max requests per customer, delay,
  minimum first rating before asking for a public review; Google / Yelp / Facebook /
  Nextdoor review URLs. Reviews page: total, average, NPS, rating trend by month,
  ratings by section, recent reviews (customer, order, section, rating, comment, channel, date).
- **Inbox:** Inbox / Sent / Deleted; mark read, delete; new message to a customer by SMS
  or email, with attachments and a 160-character counter for SMS.

---

## 11. Marketing
- Channels: Email (with templates), SMS, Push; automated flows; scheduled messages; history.
- Compose: message (160-char SMS counter, credits per message, `%REFERRAL_CODE%`
  placeholder), type (informational / marketing), exclude business accounts,
  send test.
- **Audience rule builder** (AND of rules, with "in the last N days"):
  account-created anniversary, lifetime order count, signed-up date, route,
  has online account / repeat pickup / subscription, customer group, source store,
  has left review, first-order anniversary, order count, in-store order count,
  order count in a section, total spend, average order value, odd customer IDs (A/B).
  Live "N customers match" with view list.
- Email: subject, title, message, call-to-action button (none / use a promo code, with
  label and codes); live preview with unsubscribe link.
- Marketing groups: name, description, contacts (import CSV / add manually / later).
  Loyalty points and referral program settings.
- Promo codes: code, type (% for one order, …), discount, max uses, show in POS,
  expiry, where usable (on account create, in-store, P&D, lockers), assign to business.
- Promo carousel (customer app).

---

## 12. Staff & permissions
- Users: general info, **permissions**, payroll (later). Role presets + per-permission toggles:
  - Orders: edit, edit completed, edit paid, delete, refunds, apply discounts, hide prices
  - Cash: access & submit cash-ups, edit cash-ups, confirm, open drawer, see expected/variance
  - Customers: add, edit, manage discounts, manage credits
  - Products: manage products & prices, assign price lists
  - Staff: manage users, manage payroll, bypass clock-in
  - Reports: view metrics, manage invoices, data export, audits
  - Admin: admin page, bypass IP restriction
  - Other: manage marketing, manage printers
- New user: name*, email*, password*, PIN, phone, access mode, limit driver app to
  routes, training mode (page guides). Payroll: contractor, payment type (salary /
  hourly), salary, weekly hours, prefill payroll from clock-in times.
- Login history (user, action, time, IP, device); user hours (clock in / out with IPs,
  notes, hours; totals; add a shift by hand); order edits log; order deletions log.
- Store security: force clock-in at start of shift (staff, and separately admins);
  require PIN after inactivity; IP restriction; list of active sessions.
- Business hours and store shifts per weekday; shift reports (email at end of shift,
  prompt at clock-out).

---

## 13. Reports (Metrics)
- Date + time range filter; tabs: Production, Financial, Customers, Unpaid,
  Promotions, Shift Reports, Export.
- **Financial:** total revenue (money received), total sales (value of orders),
  orders created, tips; revenue by payment method; top sections; top items
  (qty, sales); cash-ups (staff, count, variance); refunds (reason, staff);
  discounts given; pay-ins; tips by staff. Each table downloadable.
- **Production:** orders cleaned, pieces cleaned, weight processed, overdue orders;
  order issues; overdue orders; deleted orders (with reason); team activity per staff
  (new orders, orders cleaned, pieces cleaned, weight, orders completed, hours);
  driver statistics (pickups, deliveries).
- **Customers:** active customers, average order value, average sales value, average
  order frequency; top customers; new customers; products sold to top customers;
  at-risk customers (last order, days since, lifetime orders / value); new customers
  without orders.
- **Unpaid:** total outstanding with aging (current, 1–30, 31–60, 61–90, 90+ days);
  per customer: orders, invoices, total due by bucket; filter by customer type and status.
- **Promotions:** promo codes used, referral codes used, loyalty point claims, reviews.

---

## 14. Inventory
- Stock for retail products: product, section, SKU, status, quantity; low-stock warning
  level; barcode; filter by section / status; search; activity log.

---

## 15. Online & integrations (later)
- Website booking tool: hosted link, or embed on a new / existing page of the store's site.
- Directory listing: store description, services offered (wash & fold, self-serve,
  dry cleaning, alterations, shoe cleaning / repair…), amenities (parking, wifi,
  kids area, wheelchair access, coffee).
- Hosted website, AI agent; API keys and webhooks for third parties.
- The vendor's own subscription billing page does not apply to us.
