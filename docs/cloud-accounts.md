# Cloud Accounts and Budgets

Who owns the shared cloud resources, when the credits run out, and how we avoid overspending.

> **Never put passwords, keys, tokens, card numbers or subscription secrets in this file.**
> IDs below are fine to share inside the team. Secrets go in Azure Key Vault.

Status: **TODO**. Fill in the blanks (`____`) as each step is done, then tick the checklist.

## Decision

| | Azure | Google Cloud |
|---|---|---|
| Hosted on whose account | ____ | ____ |
| Offer / credit type (e.g. Azure for Students, GCP education credits) | ____ | ____ |
| Subscription name / Billing account name | ____ | ____ |
| Subscription ID / Project ID (not secret) | ____ | ____ |
| Starting credit | ____ | ____ |
| Credit expiry date | ____ | ____ |
| Region we use | ____ | `us-central1` (see `.env.example`) |

Why this account: ____ (for example the most credit left, or the latest expiry date)

## Access

| Teammate | GitHub | Azure role | Azure invite works? | GCP role | GCP invite works? |
|---|---|---|---|---|---|
| ____ (owner) | ____ | Owner | n/a | Owner | n/a |
| ____ | ____ | Contributor | ☐ | ____ | ☐ |
| ____ | ____ | Contributor | ☐ | ____ | ☐ |

## Budget alerts

| Cloud | Budget amount | Alert thresholds | Who gets the email | Set up on | Test alert received? |
|---|---|---|---|---|---|
| Azure | ____ | 25%, 50%, 80%, 100% | all three | ____ | ☐ |
| Google Cloud | ____ | 25%, 50%, 80%, 100% | all three | ____ | ☐ |

Budget alerts only **send emails**. They do **not** stop spending. See "Cost safety habits" below.

## Restrictions we hit

Write down anything that blocked us and what we did instead, for example:
- Guest invites blocked by the university tenant: ____
- App registrations (needed later for GitHub Actions OIDC) blocked: ____
- Budgets page unavailable for this offer type: ____

## Checklist (issue #4)

- [ ] Decided which Azure subscription and which GCP billing account host shared resources
- [ ] Other two teammates added as Contributor (Azure) and as IAM members (GCP)
- [ ] Each teammate confirmed they can see the resource group and the GCP project
- [ ] Budget alerts active on Azure
- [ ] Budget alerts active on Google Cloud
- [ ] Expiry dates, owners and restrictions filled in above

---

## How to do it

Console menus move around. If a step doesn't match what you see, search the portal for the
page name in **bold**.

### Azure

**1. Find the subscription and credit details**
1. Sign in to <https://portal.azure.com>, search for **Subscriptions**, open the one you'll use.
2. Copy the subscription name and ID into the table.
3. For Azure for Students, the remaining credit and expiry date are shown in the Azure
   Education Hub (search **Education** in the portal) or on the subscription's Overview page.

**2. Create a shared resource group**
1. Search **Resource groups**, then **Create**. Name it, for example, `rg-clinic-portal`, and pick
   the region.
2. Give teammates access to this resource group, not the whole subscription. That's enough for
   the project and safer.

**3. Add teammates as Contributor**
1. Open the resource group, then **Access control (IAM)**, then **Add**, then **Add role assignment**.
2. Role: **Contributor**. Members: **User, group, or service principal**, then **Select members**.
3. If the teammate isn't in your directory, invite them first: search **Microsoft Entra ID**,
   then **Users**, then **New user**, then **Invite external user**, and enter their email. After they
   accept, assign the role.
4. Ask them to sign in and confirm they can see the resource group. Note "Azure invite works?".
5. If invites are blocked (common in university tenants), record it under "Restrictions". The
   fallback is that each person uses their own subscription for experiments, and only the owner
   deploys shared resources.

**4. Set budget alerts**
1. Search **Cost Management**, then **Budgets**, then **Add**. Scope: the subscription.
2. Reset period **Monthly** (or **Annually** to match the credit), amount = the credit you want to
   guard (for example the full credit divided by the months left).
3. Add **Actual** alert conditions at 25%, 50%, 80% and 100%. Optionally add a **Forecasted**
   one at 100%.
4. Alert recipients: all three teammates' emails.
5. If Budgets isn't available for your offer type, note it under "Restrictions". As a fallback,
   check the credit balance in the Education Hub weekly.

### Google Cloud

**1. Find the billing account and credits**
1. Sign in to <https://console.cloud.google.com>, then **Billing**, and pick the billing account
   that holds the credits.
2. **Credits** (in the Billing menu) shows the remaining amount and expiry date. Copy them into
   the table.

**2. Create the project and link billing**
1. Project picker, then **New project**, for example `clinic-portal`. Copy the **Project ID**.
2. **Billing**, then **Account management**, and confirm the project is linked to the billing
   account with the credits.

**3. Add teammates**
1. In the project, go to **IAM & Admin**, then **IAM**, then **Grant access**.
2. Principal: the teammate's Google account email.
3. Role: **Editor** is the simplest for a class project. A tighter alternative is specific roles
   (Cloud SQL Admin, Vertex AI User, Storage Admin) added as we need them.
4. If they should see costs, also grant **Billing Account Viewer** on the billing account
   (**Billing**, then **Account management**, then **Add principal**).
5. Ask them to open the project and confirm. Note "GCP invite works?".

**4. Set budget alerts**
1. **Billing**, then **Budgets & alerts**, then **Create budget**.
2. Scope: the `clinic-portal` project (or the whole billing account).
3. Amount: a specified amount equal to the credit you want to guard. Decide whether the
   budget should count **credits**: if credits are subtracted from cost, alerts won't fire until
   real money is spent. For tracking credit usage, **untick** the credits so alerts fire on gross
   usage.
4. Thresholds: 25%, 50%, 80%, 100% of actual spend.
5. Notifications: billing admins and users get emails by default. To email the other teammates,
   connect **Cloud Monitoring email notification channels** for each teammate's email in the
   budget's "Manage notifications" section.

## Cost safety habits

- Tag or label every resource with `project=clinic-portal`, so costs can be filtered.
- Biggest risks for this project: an **AKS cluster** and a **Cloud SQL instance** left running.
  Use the smallest tiers, and stop or delete them when not demoing.
- Before the credit expiry date, delete everything with
  `terraform destroy` and check that nothing is left in the portals.
- Anyone who gets a budget email posts it in the team chat the same day.
