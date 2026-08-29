---
name: Inventory alerting
description: Turn stock levels into a small number of decisions with a lead time attached.
category: analytics
---

# Alerting on stock

A list of low items is not an alert. A decision with a date is.

## Rank by days of cover, not by units

Units remaining divided by recent daily rate, then compared with the supplier's
lead time. Forty units with a fourteen-day lead time and a six-a-day rate is
urgent; four hundred of something that sells once a week is not.

## Three buckets

**Order today** — cover is below lead time. **Order this week** — cover is below
lead time plus safety. **Watch** — trending toward the line.

## Say what to order

Quantity, based on the rate and the lead time, and the minimum order quantity if
there is one. An alert that leaves the buyer to do the arithmetic gets deferred.

## Flag separately

Anything with a promotion or a seasonal peak inside the lead-time window, where
the recent rate is the wrong basis.

## Never

Alert on every low item, or use a fixed unit threshold across products that sell
at completely different rates.
