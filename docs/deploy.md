# Putting Beaver Bot on the web

This is the step-by-step for hosting the site on [Render](https://render.com)'s free web service, so anyone with
the link can use it. You don't need to know how to code. Allow about 45 minutes the first time.

Three things live in three different places, on purpose:

| What | Where it lives | Public? |
|---|---|---|
| The code | The public GitHub repository | Yes |
| The OSU page data, the search index, the sample class database | One archive file, in a **private** place | No. Never in the public repository. |
| The keys (the model's, and the one that unlocks the data download) | Typed into Render's dashboard | No. Never in any file. |

## What it costs

- **Render:** the free web service is $0. No card is needed for it.
- **The model (Anthropic):** a typical question costs about a third of a cent with Claude Haiku 5.5. The site stops
  paying for answers after about **$1 a day** and switches to its free offline answers until the next day.
- **Web search backup (Brave):** off. Leave it off on the host (see "Limits to know about").

## Before you start

You need:

1. A GitHub account, with the public repository for the code already made.
2. A second, **private** GitHub repository to hold the data file. Call it something like `beaverbot-data`. It can be
   empty apart from a README.
3. An Anthropic API key (from <https://console.anthropic.com>).
4. A Render account (step 4 below).

## Step 1. Set a monthly spending limit with Anthropic (do this first)

The site keeps its own daily budget, but that budget is only an estimate kept in the site's memory. The limit that
truly cannot be passed is the one Anthropic enforces.

1. Sign in at <https://console.anthropic.com>.
2. Open **Settings**, then **Limits** (it may be under **Billing**).
3. Set a **monthly spend limit** you are comfortable with. $10 is plenty for a class project.
4. Turn **auto-reload off**, so the account can never top itself up.

## Step 2. Build the data file

On the computer that has the project and its `data/` folder, in a terminal opened in the project folder:

```bash
python -m deploy.hostdata pack
```

It takes about 20 seconds and prints something like:

```
Wrote data\serve\beaverbot-data.tar.gz: 106.8 MB
SHA-256: 9d78...f34
```

Copy the long SHA-256 value somewhere; you need it in step 5. The file is the "serving copy": only what the site
reads to answer questions (158 MB of page data instead of the full 582 MB), plus the search index and the sample
class database. Making it does not change `data/osu.sqlite` and does not touch `data/raw`.

## Step 3. Upload the data file somewhere private

Using the private repository from "Before you start" (replace `YOUR-NAME`):

```bash
gh release create data-v1 data/serve/beaverbot-data.tar.gz --repo YOUR-NAME/beaverbot-data --title "Site data" --notes "Private."
```

Then ask GitHub for the file's download address:

```bash
gh release view data-v1 --repo YOUR-NAME/beaverbot-data --json assets --jq ".assets[0].apiUrl"
```

It prints an address that starts with `https://api.github.com/repos/` and ends in a number. That is your
**DATA_URL**.

The host needs permission to download from a private repository, so make it a key that can do only that:

1. On GitHub: your picture (top right), **Settings**, **Developer settings**, **Personal access tokens**,
   **Fine-grained tokens**, **Generate new token**.
2. **Repository access:** "Only select repositories", and pick `beaverbot-data` only.
3. **Permissions:** Repository permissions, **Contents: Read-only**. Nothing else.
4. Give it an expiry date, generate it, and copy it. That is your **DATA_TOKEN**. GitHub shows it once.

(No GitHub CLI? On the private repository's page choose **Releases**, **Draft a new release**, attach the file and
publish. You still need the address from the `gh release view` command above, or ask whoever set up the repository.)

## Step 4. Create the Render account and connect the repository

1. Go to <https://render.com> and sign up with your GitHub account.
2. Click **New**, then **Blueprint**.
3. Pick the public Beaver Bot repository. If it isn't listed, click **Configure account** and give Render access
   to that one repository only.
4. Render reads `render.yaml` from the repository and shows one service, **beaver-bot**, on the **Free** plan.

## Step 5. Fill in the four private values

Render asks for the values that `render.yaml` deliberately leaves blank:

| Name | What to paste |
|---|---|
| `DATA_URL` | The address from step 3 |
| `DATA_SHA256` | The SHA-256 from step 2 |
| `DATA_TOKEN` | The GitHub token from step 3 |
| `ANTHROPIC_API_KEY` | Your Anthropic key |

Click **Apply**. The first build takes about 5 to 10 minutes: it installs two packages, downloads the data file,
checks the SHA-256, unpacks it and fetches the small search model. If the SHA-256 doesn't match, the build stops
and nothing is unpacked.

Everything else is already set in `render.yaml` and can be changed later under the service's **Environment** tab:

| Name | Set to | What it does |
|---|---|---|
| `ASSISTANT_PROVIDER` | `anthropic` | Use the model. Change to `guide` for free, offline answers only. |
| `ASSISTANT_MODEL` | `claude-haiku-5-5` | Which model. |
| `BEAVERBOT_DAILY_BUDGET_USD` | `1` | Estimated model spend per day before the site answers offline. `0` turns paid answers off. |
| `BEAVERBOT_ASK_LIMITS` | `20/600,6/30` | Each visitor: 20 questions per 10 minutes, and no more than 6 in 30 seconds. |
| `BEAVERBOT_LIVE_SEARCH` | `off` | The Brave web-search backup. Leave off. |
| `BEAVERBOT_PROXY_HOPS` | `1` | See step 7. |
| `PYTHON_VERSION` | `3.13.5` | The Python the site was tested on. |

## Step 6. Open the site

When the build finishes, Render shows the address, like `https://beaver-bot.onrender.com`. Open it and ask a
question. To check the site is up without opening it, visit the same address with `/healthz` on the end; it shows
`{"ok": true}`.

## Step 7. Check the visitor count (once)

The per-visitor limit works by telling visitors apart by their network address. Render passes that address along in
a list, and the site needs to know which entry in the list is the visitor. This could not be confirmed from
Render's documentation, so check it once:

1. After you have asked one question on the live site, open the service's **Logs** tab in Render.
2. Find the line `[proxy] X-Forwarded-For carries N address(es); BEAVERBOT_PROXY_HOPS is 1`.
3. If N is 1, you're done. If N is 2 or 3, open **Environment**, set `BEAVERBOT_PROXY_HOPS` to that number, and save.

If this is set wrong, nothing breaks and nothing costs more (the daily budget does not depend on it), but visitors
may end up sharing one allowance and see "That's a lot of messages" sooner than they should.

## What the logs show

The logs never contain a question or anyone's address. They show the page that was asked for (like
`POST /api/ask 200`) and, every 20 questions, a line of counts:

```
[budget] counts: questions=40 slowed=1 answered_offline=0 estimated=$0.1312 of $1.00 today
```

`slowed` is how many questions were turned away by the per-visitor limit. `answered_offline` is how many were
answered without the model because the day's budget was used.

## Limits to know about

- **The site sleeps.** Render's free service goes to sleep after 15 minutes with no visitors. The next visitor
  waits about a minute while it wakes up. Open the site a couple of minutes before a demo.
- **Sleeping resets the site's memory.** That means demo sign-ins end, and the day's spending estimate starts
  again from zero. This is why the Anthropic limit in step 1 matters: it is the one that always holds.
- **Feedback is not kept.** Ratings and "report a wrong answer" are saved to a file on the host, and Render's free
  service wipes its files whenever it sleeps or restarts.
- **Keep Brave off here.** Its monthly counter is also a file on the host, so on the free service it would reset
  and could not hold the 900-a-month ceiling. The switch is off in `render.yaml`.
- **Memory.** The free service has 512 MB. On the project laptop the site used about 300 MB when idle and peaked
  near 320 MB while answering ten questions at once. That was measured on Windows, not on Render itself, so treat
  it as a good sign rather than proof. If Render's **Events** tab ever shows "out of memory", set
  `BEAVERBOT_SEMANTIC` to `off` in **Environment**. That turns off the meaning-based half of search and frees about
  180 MB; answers get a little worse at matching different wordings ("meal plan" vs "dining plan") but the site
  stays free. The paid alternative is a larger Render plan with more memory; check Render's pricing page for the
  current price.
- **750 free hours a month.** One always-awake service uses about 730, so one free service fits. Two would not.

## Updating later

- **New code:** in Render, open the service and click **Manual Deploy**, **Deploy latest commit**. (Automatic
  deploys are off so nothing goes live by accident.)
- **New data** (after a re-crawl): repeat steps 2 and 3 with a new release name such as `data-v2`, then change
  `DATA_URL` and `DATA_SHA256` in **Environment** and deploy again.
- **Turn paid answers off quickly:** set `BEAVERBOT_DAILY_BUDGET_USD` to `0`, or `ASSISTANT_PROVIDER` to `guide`.
- **Take the site down:** in the service's **Settings**, choose **Suspend**.

## What must never go in the public repository

`.gitignore` already keeps these out; `tests/test_deploy.py` checks the list.

- `data/` (the page database, `data/raw`, the search index, the sample database, logs, the data archive)
- `crawler.toml` and `beaverbot.local.toml` (this computer's settings)
- `Community Engagement - Filled.pdf`
- Any key or token
