# CRM retention practice: RFM, lifecycle and repeat purchases

A practice project on a public dataset. I wanted to answer a question every
online shop has: **which customers bring the revenue, who is about to leave,
and what should the CRM team send to each group?**

The data is 36,969 orders from 5,878 customers of a UK online retailer
(UCI *Online Retail II*, December 2009 to December 2011, in pounds). It is not
client work.

**[Open the live page](https://errer441122.github.io/digital-campaign-performance-dashboard/)**

[![The live page: headline figures and RFM segments](assets/web_dashboard.png)](https://errer441122.github.io/digital-campaign-performance-dashboard/)

## What the data says

- **Champions are 26% of customers and 71% of revenue.** Keeping them matters
  more than finding new customers.
- **588 customers are "at risk".** Their last order was 91 to 180 days ago and
  they have spent £1.06M so far. That is the win-back list.
- **About one new customer in five orders again the following month** (21%),
  and the share is still 18% six months later.
- **Half of the customers who come back do it within 71 days.** 41% of new
  customers order again within 90 days and 69% within a year. That is the
  window for a second-order email.
- **A customer in Germany has spent 48% more than one in the UK** (£3,986
  against £2,700 per customer).

Full tables: [RFM segments, repeat purchases and value by country](analysis/crm_retention.md) ·
[lifecycle stages](analysis/crm_lifecycle.md).

## The marketing concepts I used

| Concept | In plain words | What it is for |
| --- | --- | --- |
| **RFM segmentation** | Score each customer on how recently, how often and how much they buy | Decide who gets which message |
| **Lifecycle stages** | New, Repeat, At risk, Dormant, Churned, based on the date of the last order | Trigger the right flow at the right time |
| **Cohort retention** | Of the customers who first bought in a given month, how many come back in the next months | See whether customers return, and how fast they stop |
| **Time to second order** | How many days pass between a customer's first and second order | Decide when the second-order email goes out |
| **Revenue per customer by country** | Total spend divided by the number of customers | Compare how much a customer is worth in each market |

The lifecycle rules are the same ones my
[Lifecycle Automation Lab](https://github.com/errer441122/lifecycle-automation-lab)
uses to trigger a win-back flow in Klaviyo.

## Real-World Business Application (Next Steps)

This is what I would do with these numbers in a real shop. They are
recommendations, not results: the dataset has no email or advertising data, so
nothing here has been tested on customers.

1. **Stop sending the same discount to everyone.** RFM shows who needs a
   reason to come back and who does not. The offer goes to the win-back group
   (At risk, Can't lose them). Champions get early access or a thank-you
   instead: they would have bought anyway, so a discount only costs margin.
   Long-inactive, low-value customers get one cheap reminder and then leave
   the mailing list, which also protects deliverability.
2. **Time the second-order email with the data.** Half of the customers who
   come back within a year place their second order within 71 days, and 41% of
   new customers have already ordered again by day 90. A reminder without a
   discount belongs before day 71; the discount waits for the customers still
   missing after day 90.
3. **Start the win-back at day 91, not after a year.** The at-risk group is a
   short list with a recent purchase history. The group silent for more than a
   year is 2.7 times larger, and the longer the silence, the harder the return.
4. **Set the acquisition budget by market.** If a customer in Germany spends
   48% more over time, paying more to acquire one there can still make sense.
   One blended target for every country hides that.
5. **Measure it on real data.** The next step is to run this on a real store
   export (Shopify orders, Klaviyo campaigns) and compare repeat purchases
   between customers who received a flow and customers who did not.

## What is in here

| Path | What it does |
| --- | --- |
| `analysis/` | The result tables, in Markdown and JSON |
| `docs/index.html` | The live page, generated from the results |
| `dashboard/crm_dashboard.xlsx` | The same tables as an Excel workbook |
| `src/` | The Python scripts that clean the data and build everything above |
| `notebooks/cross_check.ipynb` | A second calculation of the main numbers, to catch mistakes |
| `tests/` | Automatic checks that run on every change |

## Run it

```bash
python -m pip install -r requirements.txt
python src/validate_data.py
python src/crm_retention.py
python src/crm_lifecycle.py
python src/build_dashboard.py
python src/build_web_dashboard.py
python -m pytest -q
```

## Data and limits

Chen, D. (2019). *Online Retail II*. UCI Machine Learning Repository, CC BY 4.0.
Source and cleaning rules are in
[`data/REAL_DATA_PROVENANCE.md`](data/REAL_DATA_PROVENANCE.md).

- This is a public dataset that many people practise on. It has no
  advertising, web analytics or email data, so nothing here measures a
  campaign.
- "Revenue per customer" is what customers have spent so far, not a forecast.
- The numbers describe what happened. They do not prove what caused it.
- Earlier versions of this repository also had campaign reports built on data
  I had simulated. I removed them in November 2026, because numbers I generated
  myself cannot show how a campaign performs. The repository keeps its original
  name so existing links keep working.

## How I built this

I am a Digital Marketing student, not a developer. I built this with AI coding
assistants: they wrote most of the code. My part was choosing the question and
the data, defining the segments and the rules, checking the results against
the source data and deciding what to report.
