# Cloud Accounts and Budgets

Who owns the shared Azure resources, when the credits run out, and how we avoid overspending.
Everything runs on Azure (we dropped Google Cloud: the account couldn't be used).

> **Never put passwords, keys, tokens, card numbers or subscription secrets in this file.**
> IDs below are fine to share inside the team. Secrets go in Azure Key Vault.

Status: **deployed 2026-10-31**, teammates have access. Remaining blanks: credit amount and expiry.

## Decision

| | Azure |
|---|---|
| Hosted on whose account | Tabarek (tjs3201@wmich.edu) |
| Offer / credit type | Azure for Students |
| Subscription name | Azure for Students |
| Subscription ID (not secret) | e8fb3009-935e-458c-8a9f-5ddef82f3155 |
| Starting credit | ____ |
| Credit expiry date | ____ |
| Region we use | `canadacentral` (the subscription only allows canadacentral, francecentral, belgiumcentral, denmarkeast, mexicocentral) |

Why this account: ____ (for example the most credit left, or the latest expiry date)

## Access

Granted 2026-10-31. Everyone is in the WMU tenant, so no guest invitations were needed.

| Teammate | GitHub | Roles |
|---|---|---|
| Tabarek Al Ghnaimawi (owner) | @Tabarek92 | **Owner** of the subscription |
| Ruth Bahre | @ruthbah | Reader (subscription), Contributor (`rg-clinicportal`), Storage Blob Data Contributor (Terraform state), Key Vault Secrets Officer (`kv-clinicportal`), Cognitive Services OpenAI User (`oai-clinicportal`) |
| Tilok Jahan | @TilokJahan | same as Ruth |

What the roles allow:

| Role | Scope | Lets them |
|---|---|---|
| Reader | whole subscription | See everything (also other projects in the subscription, read-only); Terraform needs it to check resource-provider registrations |
| Contributor | `rg-clinicportal` | Manage the app's resources: start/stop AKS and PostgreSQL, push images, deploy, see costs |
| Storage Blob Data Contributor | `clinicportaltf9d0ae9` (Terraform state) | Run `terraform plan` / `apply` against the shared state |
| Key Vault Secrets Officer | `kv-clinicportal` | Let Terraform manage the database URL and demo-token secrets |
| Cognitive Services OpenAI User | `oai-clinicportal` | Run `scripts/evaluate_ai.py` from a laptop with `az login` |

Only the owner can grant access to others or apply Terraform changes that create new role
assignments (Contributor can't assign roles).

Getting started for teammates:

```bash
az login
az account set --subscription e8fb3009-935e-458c-8a9f-5ddef82f3155
terraform -chdir=infra/terraform init -backend-config="storage_account_name=clinicportaltf9d0ae9"
terraform -chdir=infra/terraform plan   # should say "No changes"
```

## Budget alerts

| Cloud | Budget amount | Alert thresholds | Who gets the email | Set up on | Test alert received? |
|---|---|---|---|---|---|
| Azure | ____ | 25%, 50%, 80%, 100% | all three | ____ | ☐ |

Budget alerts only **send emails**. They do **not** stop spending. Terraform (`infra/terraform`) creates the budget for you. See "Cost safety habits" below.

## Restrictions we hit

Write down anything that blocked us and what we did instead, for example:
- Guest invites blocked by the university tenant: ____
- App registrations (needed later for GitHub Actions OIDC) blocked: ____
- Budgets page unavailable for this offer type: ____

## Checklist (issue #4)

- [ ] Decided which Azure subscription hosts the shared resources
- [x] Other two teammates added as Contributor
- [ ] Each teammate confirmed they can see the resource group
- [ ] Budget alerts active on Azure
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

## Cost safety habits

- Tag or label every resource with `project=clinic-portal`, so costs can be filtered.
- Biggest risks for this project: an **AKS cluster** and a **PostgreSQL server** left running.
  Use the smallest tiers, and stop or delete them when not demoing.
- Before the credit expiry date, delete everything with
  `terraform destroy` and check that nothing is left in the portals.
- Anyone who gets a budget email posts it in the team chat the same day.
