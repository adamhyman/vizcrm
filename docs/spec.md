# VIZCRM product spec (draft)

Our own design for a laundry / dry-cleaning management system: a web back office,
a REST API, and four mobile apps. The feature list is based on general industry
practice and on competitors' public marketing pages (no code, API, or logged-in
app was used). Screens and implementation are our own.

Mark each feature: `[ ]` undecided · `[MVP]` first release · `[Later]` · `[No]`

---

## 1. Web back office (Django)

### Customers (CRM)
- [ ] Customer records: name, phone, email, addresses, notes
- [ ] Care preferences (starch, folding, hangers, detergent, fragrance-free)
- [ ] Business / account customers billed periodically
- [ ] Search by name, phone, or order number
- [ ] Signed waivers / release forms stored on the customer profile
- [ ] Two-way SMS messaging with customers
- [ ] Marketing opt-in and message history

### Orders
- [ ] Order list with filters (status, date, store, customer)
- [ ] Order detail: items, prices, status history, payments, notes, photos
- [ ] Configurable status workflow (received → in production → ready → out for delivery → completed)
- [ ] Due dates; express / same-day surcharges
- [ ] Split an order into multiple tickets
- [ ] Automatic "order ready" notifications (SMS, email, push, WhatsApp)

### Catalog and pricing
- [ ] Services (dry clean, wash & fold, alterations, household items)
- [ ] Per-item and per-weight pricing
- [ ] Price lists per store or per business customer
- [ ] Upcharges (stain, delicate, leather), discounts, promo codes
- [ ] Taxes

### Stores and staff
- [ ] Multiple store locations; shared catalog and customers across stores
- [ ] Staff accounts with roles and permissions
- [ ] Activity log of staff actions
- [ ] Clock in / out, hours and overtime
- [ ] Machine maintenance log (issue, repair, cost)

### Pickup and delivery
- [ ] Service zones drawn on a map; pickup only offered inside zones
- [ ] Bookable time slots
- [ ] Recurring / subscription pickups with reminders
- [ ] Route planning and optimization; assign stops to drivers
- [ ] Live driver tracking on a map
- [ ] Third-party courier integration (DoorDash / Uber Direct)

### Payments and invoicing
- [ ] Payment records (card, cash, account balance, prepaid card)
- [ ] Invoices and statements; automatic invoicing for business customers
- [ ] Refunds
- [ ] Prepaid laundry cards / store credit
- [ ] Saved cards on customer accounts (via payment provider)

### Marketing
- [ ] SMS / email / push campaigns with customer segments
- [ ] Automated flows (welcome series, win-back, loyalty milestones)
- [ ] Loyalty points
- [ ] Referral codes
- [ ] Automatic review requests (Google, Yelp, Facebook)

### Reports
- [ ] Dashboard: revenue, orders, top services, per store or all stores
- [ ] Sales, tax, discounts, payouts by store / service / date range
- [ ] Staff activity and hours
- [ ] Cash-up reports
- [ ] Store-to-store comparison
- [ ] Export to Excel / CSV

---

## 2. POS app (iOS / Android, tablet-first)

- [ ] Find or create a customer fast (phone number first); flag first-time customers
- [ ] Build an order: catalog items, quantities, upcharges, care notes, condition notes
- [ ] Garment / damage photos at drop-off
- [ ] Customer-facing second screen showing items, prices, promos, pickup date
- [ ] On-screen signature for waivers / release forms
- [ ] Weight scale input for per-weight services
- [ ] Print receipts, garment tags, bag labels (Star / Epson printers)
- [ ] Scan barcodes at intake
- [ ] Card payments via card reader (payment provider SDK), cash, prepaid card
- [ ] Split payments
- [ ] Collection: find order, take balance, mark collected
- [ ] Cash drawer: payouts by employee, end-of-day cash-up
- [ ] Works offline when the internet drops

## 3. Scanner app (iOS / Android, phone or mounted tablet)

- [ ] Scan garment tag / ticket barcode
- [ ] Move items through configurable production stages
- [ ] Quality-control checkpoints at chosen stages
- [ ] Assign washer / dryer; track machine activity
- [ ] Assign finished orders to a rack slot
- [ ] Assembly: confirm every item of an order is present before bagging
- [ ] Flag issues (missing item, stain remaining, damage)
- [ ] Batch scan mode
- [ ] Central plant view: orders from multiple drop-off stores and routes
- [ ] Locker integration for after-hours drop-off / collection

## 4. Driver app (iOS / Android, phone)

- [ ] Today's jobs: ordered list of pickups and deliveries, map view
- [ ] New-pickup alerts
- [ ] Navigate to stop (hand off to Apple / Google Maps)
- [ ] Mark pickup / delivery done; proof of delivery (photo, signature)
- [ ] Scan bags at pickup and delivery
- [ ] Take payment on delivery
- [ ] Chat with the customer
- [ ] Share live location while on shift

## 5. VIZCRM app (iOS / Android) — purpose to confirm

Assumed: the **customer-facing** app.

- [ ] Sign up / log in
- [ ] Book a pickup (address in service zone, time slot, instructions)
- [ ] Recurring pickups / subscriptions
- [ ] Track order status in real time; live driver map
- [ ] Message the driver / store
- [ ] Saved cards; pay invoices
- [ ] Order history, re-order
- [ ] Loyalty points and referral code
- [ ] Push notifications

## 6. Customer website (optional)

- [ ] Online booking page for pickups
- [ ] "Book" button from Google Business Profile
- [ ] Store info, prices, reviews

---

## Proposed data model (Django apps)

| App             | Main models                                                             |
|-----------------|-------------------------------------------------------------------------|
| `accounts`      | User (role), Store, StaffShift, ActivityLog                             |
| `contacts`      | Customer, Address, CarePreference, Waiver                               |
| `catalog`       | Service, Product, PriceList, PriceListItem, Upcharge, Discount, PromoCode |
| `orders`        | Order, Ticket, OrderItem, OrderStatusEvent, OrderPhoto                  |
| `production`    | Stage, Tag (barcode), ScanEvent, Rack, RackSlot, Machine, MaintenanceLog |
| `deliveries`    | Zone, TimeSlot, Subscription, Route, Stop, DriverLocation, ProofOfDelivery |
| `payments`      | Payment, Refund, Invoice, PrepaidCard, CashDrawerEvent                  |
| `marketing`     | Campaign, Flow, LoyaltyAccount, Referral, ReviewRequest                 |
| `notifications` | MessageTemplate, MessageLog                                             |

Changes from the current skeleton: remove `deals`; rename `scanning` → `production`;
add `catalog`, `orders`, `marketing`, `notifications`.

## Open questions
1. What is the VIZCRM app for — customers, or managers on the go?
2. One store or several? A central cleaning plant?
3. Card payment provider / card reader (Stripe Terminal, Square, other)?
4. Receipt / tag printer and scale models?
5. Pickup and delivery: own drivers, couriers (DoorDash / Uber), or both?
6. Which country / currency / tax rules?
